"""Interpretable alert logic (no machine-learning model).

For each parameter the baseline is the median of the previous BASELINE_HOURS, leaving out the most
recent EXCLUSION_HOURS so an ongoing event cannot hide inside its own baseline. A reading is unusual
when its robust z-score is beyond Z_THRESHOLD, and a flag needs PERSIST_N consecutive readings in the
same direction. Sensors with missing/invalid/implausible/constant values are excluded and reported
separately, so a sensor fault is never presented as a change in the water.
"""
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
from . import config
from .validation import usable


@dataclass
class Finding:
    param: str
    direction: str
    z: float
    value: float
    baseline: float
    strength: str


@dataclass
class Event:
    key: str
    start: pd.Timestamp
    end: pd.Timestamp
    params: list
    direction: dict
    max_z: float
    strength: str
    n_steps: int
    cadence: int
    ongoing: bool = False

    @property
    def duration_min(self):
        return self.n_steps * self.cadence


@dataclass
class Status:
    state: str            # normal | investigate | verified | unavailable
    reason: str           # ok | unusual | verified | no_data | stale | unreliable | insufficient_baseline
    latest_time: pd.Timestamp = None
    age_minutes: float = None
    findings: list = field(default_factory=list)
    sensor_issues: dict = field(default_factory=dict)
    event: Event = None
    cadence: int = 5


@dataclass
class Signals:
    grid: pd.DataFrame
    median: pd.DataFrame
    sigma: pd.DataFrame
    z: pd.DataFrame
    pers: pd.DataFrame
    cadence: int


@dataclass
class Analysis:
    signals: Signals
    events: list
    status: Status


def strength_for(z):
    for lower, name in config.STRENGTH_BANDS:
        if abs(z) >= lower:
            return name
    return "low"


def infer_cadence(df):
    if len(df) < 3:
        return 5
    d = df["timestamp"].sort_values().diff().dropna().dt.total_seconds() / 60
    d = d[d > 0]
    if d.empty:
        return 5
    return int(min(60, max(1, round(d.median()))))


def build_grid(df, cad):
    cols = config.PARAMS
    if df.empty:
        return pd.DataFrame(columns=cols, index=pd.DatetimeIndex([], tz="UTC"), dtype=float)
    start = df["timestamp"].max() - pd.Timedelta(days=config.ANALYSIS_DAYS) - pd.Timedelta(hours=config.BASELINE_HOURS)
    sub = df[df["timestamp"] >= start]
    vals = pd.DataFrame({p: usable(sub, p) for p in cols})
    vals.index = pd.DatetimeIndex(sub["timestamp"])
    return vals.sort_index().resample(f"{cad}min").mean()


def _mad(w):
    w = w[~np.isnan(w)]
    if w.size == 0:
        return np.nan
    return np.median(np.abs(w - np.median(w)))


def compute_signals(grid, cad):
    base_steps = int(round(config.BASELINE_HOURS * 60 / cad))
    excl = max(1, int(round(config.EXCLUSION_HOURS * 60 / cad)))
    min_p = max(10, int(config.MIN_BASELINE_FRACTION * base_steps))
    med, sig, zs, pers = {}, {}, {}, {}
    for p in config.PARAMS:
        roll = grid[p].shift(excl).rolling(base_steps, min_periods=min_p)
        m = roll.median()
        s = (roll.apply(_mad, raw=True) * 1.4826).clip(lower=config.MIN_SCALE[p])
        z = (grid[p] - m) / s
        up = (z > config.Z_THRESHOLD).astype(float).rolling(config.PERSIST_N).sum().eq(config.PERSIST_N)
        dn = (z < -config.Z_THRESHOLD).astype(float).rolling(config.PERSIST_N).sum().eq(config.PERSIST_N)
        med[p], sig[p], zs[p] = m, s, z
        pers[p] = up.astype(int) - dn.astype(int)
    return Signals(grid, pd.DataFrame(med), pd.DataFrame(sig), pd.DataFrame(zs), pd.DataFrame(pers), cad)


def detect_events(sig, site_id):
    n = config.PERSIST_N
    any_p = (sig.pers != 0).any(axis=1).to_numpy()
    idx = np.flatnonzero(any_p)
    if idx.size == 0:
        return []
    groups, cur = [], [idx[0]]
    for i in idx[1:]:
        if i - cur[-1] > config.EVENT_MERGE_GAP:
            groups.append(cur)
            cur = [i]
        else:
            cur.append(i)
    groups.append(cur)
    events = []
    last_pos = len(sig.grid) - 1
    for g in groups:
        first, last = g[0], g[-1]
        start_pos = max(0, first - (n - 1))
        params, direction, maxz = [], {}, 0.0
        for p in config.PARAMS:
            ps = sig.pers[p].iloc[first:last + 1]
            nz = ps[ps != 0]
            if nz.empty:
                continue
            params.append(p)
            direction[p] = "up" if nz.mean() > 0 else "down"
            maxz = max(maxz, float(sig.z[p].iloc[first:last + 1][ps != 0].abs().max()))
        start = sig.grid.index[start_pos]
        events.append(Event(
            key=f"{site_id}|{start.isoformat()}", start=start, end=sig.grid.index[last],
            params=params, direction=direction, max_z=maxz, strength=strength_for(maxz),
            n_steps=int(last - start_pos + 1), cadence=int(sig.cadence), ongoing=bool(last == last_pos)))
    return events


def sensor_issues(df):
    if df.empty:
        return {}
    row = df.loc[df["timestamp"].idxmax()]
    return {p: row[f"{p}_flag"] for p in config.PARAMS if row[f"{p}_flag"] != "ok"}


def latest_status(df, sig, events, verified_keys=(), now=None):
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    if df.empty:
        return Status("unavailable", "no_data")
    latest = df["timestamp"].max()
    age = (now - latest).total_seconds() / 60
    cad = sig.cadence
    issues = sensor_issues(df)
    base = dict(latest_time=latest, age_minutes=age, sensor_issues=issues, cadence=cad)
    if age > max(config.STALE_AFTER_MINUTES, 6 * cad):
        return Status("unavailable", "stale", **base)
    if len(issues) >= config.UNRELIABLE_IF_FAULTS_AT_LEAST:
        return Status("unavailable", "unreliable", **base)
    eligible = [p for p in config.PARAMS if p not in issues]
    if sig.median.empty:
        return Status("unavailable", "insufficient_baseline", **base)
    with_base = [p for p in eligible if not pd.isna(sig.median[p].iloc[-1])]
    if not with_base:
        return Status("unavailable", "insufficient_baseline", **base)
    findings = []
    for p in with_base:
        d = sig.pers[p].iloc[-1]
        if d != 0:
            z = float(sig.z[p].iloc[-1])
            findings.append(Finding(p, "up" if d > 0 else "down", z, float(sig.grid[p].iloc[-1]),
                                    float(sig.median[p].iloc[-1]), strength_for(z)))
    event = events[-1] if (findings and events and events[-1].ongoing) else None
    if findings:
        state, reason = "investigate", "unusual"
        if event is not None and event.key in set(verified_keys):
            state, reason = "verified", "verified"
        return Status(state, reason, findings=findings, event=event, **base)
    return Status("normal", "ok", **base)


def analyse(df_site, site_id, verified_keys=(), now=None):
    cad = infer_cadence(df_site)
    grid = build_grid(df_site, cad)
    sig = compute_signals(grid, cad) if len(grid) else Signals(grid, grid.copy(), grid.copy(), grid.copy(), grid.copy(), cad)
    events = detect_events(sig, site_id) if len(grid) else []
    status = latest_status(df_site, sig, events, verified_keys, now)
    return Analysis(sig, events, status)


def vs_usual(sig, param):
    """'higher' / 'lower' / 'similar' / 'unknown' for the latest few readings against the baseline."""
    if sig.grid.empty:
        return "unknown"
    recent = sig.grid[param].iloc[-config.PERSIST_N:].median()
    base, s = sig.median[param].iloc[-1], sig.sigma[param].iloc[-1]
    if pd.isna(recent) or pd.isna(base) or pd.isna(s):
        return "unknown"
    z = (recent - base) / s
    if z >= config.Z_THRESHOLD:
        return "higher"
    if z <= -config.Z_THRESHOLD:
        return "lower"
    return "similar"
