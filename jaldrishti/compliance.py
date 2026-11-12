"""Company limit screening.

A company enters its own limits (min and/or max per parameter). The app compares the buoy readings with
those limits using fixed rules. There is no AI model, and the result is a screening, not a legal
compliance decision: the buoy measures the water where it floats, not the company's discharge.
Nothing is pre-filled because limits differ by company, site and policy.
"""
from dataclasses import dataclass, field
import hashlib
import json
import math
import os
import re
import tempfile
import numpy as np
import pandas as pd
from . import config
from .validation import usable

BASES = ("instant", "1h", "24h")
NEAR_FRACTION = 0.10
MAX_TEXT = {"name": 80, "relation": 200, "notes": 500, "reference": 200}


# ---------------------------------------------------------------- profiles (saved as JSON)
def _clean(text, limit):
    return " ".join(str(text or "").split())[:limit]


def profile_id(name):
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "company-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]


def load_profiles(path=None):
    path = path or config.COMPLIANCE_PATH
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("profiles", {})
    except (json.JSONDecodeError, OSError, AttributeError):
        return {}


def _write(profiles, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"profiles": profiles}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def save_profile(name, site_id, relation, notes, limits, path=None, now=None):
    path = path or config.COMPLIANCE_PATH
    profiles = load_profiles(path)
    pid = profile_id(_clean(name, MAX_TEXT["name"]))
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    profiles[pid] = {"name": _clean(name, MAX_TEXT["name"]), "site_id": _clean(site_id, 80),
                     "relation": _clean(relation, MAX_TEXT["relation"]), "notes": _clean(notes, MAX_TEXT["notes"]),
                     "limits": limits, "updated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    _write(profiles, path)
    return pid


def delete_profile(pid, path=None):
    path = path or config.COMPLIANCE_PATH
    profiles = load_profiles(path)
    if pid in profiles:
        del profiles[pid]
        _write(profiles, path)


def parse_limits(form):
    """form: {param: {"min": str, "max": str, "basis": str, "reference": str}} -> (limits, errors).

    errors are (code, param, extra) tuples that the UI turns into translated messages.
    """
    limits, errors = {}, []
    for p in config.PARAMS:
        row = form.get(p, {})
        vals = {}
        for bound in ("min", "max"):
            raw = str(row.get(bound, "")).strip().replace(",", ".")
            if not raw:
                continue
            try:
                v = float(raw)
            except ValueError:
                errors.append(("number", p, None))
                break
            if not math.isfinite(v):
                errors.append(("number", p, None))
                break
            lo, hi = config.PLAUSIBLE[p]
            if v < lo or v > hi:
                errors.append(("range", p, (lo, hi)))
                break
            vals[bound] = v
        else:
            if not vals:
                continue
            if "min" in vals and "max" in vals and vals["min"] >= vals["max"]:
                errors.append(("minmax", p, None))
                continue
            basis = row.get("basis", "instant")
            limits[p] = {"min": vals.get("min"), "max": vals.get("max"),
                         "basis": basis if basis in BASES else "instant",
                         "reference": _clean(row.get("reference", ""), MAX_TEXT["reference"])}
    if not limits and not errors:
        errors.append(("none", None, None))
    return limits, errors


# ---------------------------------------------------------------- screening
@dataclass
class Episode:
    param: str
    start: pd.Timestamp
    end: pd.Timestamp
    n_readings: int
    peak: float
    peak_time: pd.Timestamp
    duration_min: float
    sustained: bool
    unusual_event: bool = False


@dataclass
class ParamResult:
    param: str
    limit: dict
    status: str                    # outside | near | within | nodata
    latest: float = None
    latest_time: pd.Timestamp = None
    trend: str = None              # up | down | steady | None
    pct_outside: float = 0.0
    n_valid: int = 0
    usable_pct: float = 0.0
    episodes: list = field(default_factory=list)
    longest_min: float = 0.0
    peak: float = None
    peak_time: pd.Timestamp = None


@dataclass
class Result:
    overall: str                   # none | unavailable | outside | near | within
    params: dict
    period_hours: int
    latest_time: pd.Timestamp = None
    age_minutes: float = None
    counts: dict = field(default_factory=dict)


def _basis_series(s, basis, cad):
    per_hour = 60.0 / cad
    if basis == "1h":
        return s.rolling("1h", min_periods=max(1, int(0.5 * per_hour))).mean()
    if basis == "24h":
        return s.rolling("24h", min_periods=max(1, int(0.5 * per_hour * 24))).mean()
    return s


def _exceed(v, lim):
    out = pd.Series(0.0, index=v.index)
    if lim.get("max") is not None:
        out = np.maximum(out, v - lim["max"])
    if lim.get("min") is not None:
        out = np.maximum(out, lim["min"] - v)
    return out


def _margin(lim):
    if lim.get("min") is not None and lim.get("max") is not None:
        return NEAR_FRACTION * (lim["max"] - lim["min"])
    bound = lim.get("max") if lim.get("max") is not None else lim.get("min")
    return NEAR_FRACTION * (abs(bound) if bound else 1.0)


def _trend(s, param):
    last = s[s.index > s.index[-1] - pd.Timedelta(hours=1)]
    if len(last) < 4:
        return None
    x = (last.index - last.index[0]).total_seconds().to_numpy() / 3600.0
    slope = np.polyfit(x, last.to_numpy(), 1)[0]          # change per hour
    floor = config.MIN_SCALE[param]
    return "up" if slope > floor else "down" if slope < -floor else "steady"


def evaluate(df, limits, period_hours, cadence=5, events=(), now=None):
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    res = Result("none", {}, period_hours)
    if not limits:
        return res
    if df.empty:
        res.overall = "unavailable"
        res.params = {p: ParamResult(p, lim, "nodata") for p, lim in limits.items()}
        res.counts = {"outside": 0, "near": 0, "within": 0, "nodata": len(limits)}
        return res
    latest = df["timestamp"].max()
    res.latest_time, res.age_minutes = latest, (now - latest).total_seconds() / 60
    stale = res.age_minutes > max(config.STALE_AFTER_MINUTES, 6 * cadence)
    start = latest - pd.Timedelta(hours=period_hours)
    max_gap = pd.Timedelta(minutes=max(3 * cadence, 30))
    for p, lim in limits.items():
        s = pd.Series(usable(df, p).to_numpy(), index=pd.DatetimeIndex(df["timestamp"])).dropna().sort_index()
        s = s[~s.index.duplicated(keep="last")]
        pr = ParamResult(p, lim, "nodata")
        res.params[p] = pr
        if s.empty or stale:
            continue
        bs = _basis_series(s, lim.get("basis", "instant"), cadence).dropna()
        window = bs[bs.index > start]
        raw_window = s[s.index > start]
        expected = max(1, int(period_hours * 60 / cadence))
        pr.n_valid, pr.usable_pct = len(raw_window), min(100.0, 100.0 * len(raw_window) / expected)
        if window.empty:
            continue
        exc = _exceed(window, lim)
        outside = exc > 0
        pr.pct_outside = 100.0 * float(outside.sum()) / len(window)
        # periods outside the limit: consecutive readings, broken by gaps in the data
        times, flags, vals, dist = window.index, outside.to_numpy(), window.to_numpy(), exc.to_numpy()
        i = 0
        while i < len(times):
            if not flags[i]:
                i += 1
                continue
            j = i
            while j + 1 < len(times) and flags[j + 1] and times[j + 1] - times[j] <= max_gap:
                j += 1
            k = i + int(np.argmax(dist[i:j + 1]))
            dur = (times[j] - times[i]).total_seconds() / 60 + cadence
            ep = Episode(p, times[i], times[j], j - i + 1, float(vals[k]), times[k], dur, (j - i + 1) >= config.PERSIST_N)
            ep.unusual_event = any(p in e.params and e.start <= ep.end and e.end >= ep.start for e in events)
            pr.episodes.append(ep)
            i = j + 1
        if pr.episodes:
            pr.longest_min = max(e.duration_min for e in pr.episodes)
            worst = max(pr.episodes, key=lambda e: float(exc.loc[e.peak_time]))
            pr.peak, pr.peak_time = worst.peak, worst.peak_time
        pr.latest, pr.latest_time = float(bs.iloc[-1]), bs.index[-1]
        pr.trend = _trend(s, p)
        if _exceed(pd.Series([pr.latest]), lim).iloc[0] > 0:
            pr.status = "outside"
        else:
            m = _margin(lim)
            near = (lim.get("max") is not None and lim["max"] - pr.latest <= m) or \
                   (lim.get("min") is not None and pr.latest - lim["min"] <= m)
            pr.status = "near" if near else "within"
    counts = {k: sum(1 for r in res.params.values() if r.status == k) for k in ("outside", "near", "within", "nodata")}
    res.counts = counts
    if counts["nodata"] == len(res.params):
        res.overall = "unavailable"
    elif counts["outside"]:
        res.overall = "outside"
    elif counts["near"]:
        res.overall = "near"
    else:
        res.overall = "within"
    return res
