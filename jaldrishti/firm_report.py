import io
import math
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import alerts, config, oxygen
from .series_tools import usable_series

LABEL = {"ph": "pH", "turbidity": "Turbidity", "tds": "TDS", "do": "Dissolved oxygen", "temperature": "Temperature"}
UNIT = {"ph": "", "turbidity": "NTU", "tds": "mg/L", "do": "mg/L", "temperature": "°C"}
SUSTAINED_N = 3          # fewer readings than this in a row = brief excursion (same rule as METHODS.md)
CLOSE_SHARE = 0.10       # "close to the limit" = within 10 percent
MIN_EVAL = 5
MIN_COMPLETE = 0.25
LOW_SAT = 60.0           # percent saturation. CPCB uses 60 percent saturation for SW-I waters
HIGH_SAT = 120.0         # screening marker used in this report only, not a regulation


def fmt(v, p):
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return "-"
    return f"{v:.{config.DECIMALS.get(p, 2)}f}"


def val(v, p):
    u = UNIT.get(p, "")
    return fmt(v, p) + ((" " + u) if u else "")


def lab(p):
    u = UNIT.get(p, "")
    return LABEL[p] + (f" ({u})" if u else "")


def ist(ts, with_time=True):
    t = pd.Timestamp(ts).tz_convert(config.DISPLAY_TZ)
    return t.strftime("%d %b %Y %H:%M" if with_time else "%d %b %Y")


def hhmm(minutes):
    m = int(round(minutes))
    return f"{m // 60}:{m % 60:02d} h"


# ------------------------------------------------------------------ periods

def period_bounds(kind, now=None, start_date=None, end_date=None):
    tz = config.DISPLAY_TZ
    now_l = pd.Timestamp.now(tz=tz) if now is None else pd.Timestamp(now).tz_convert(tz)
    today = now_l.normalize()
    if kind == "today":
        s, e, label = today, now_l, "Today, " + today.strftime("%d %b %Y")
    elif kind == "month":
        s, e, label = today.replace(day=1), now_l, now_l.strftime("%B %Y") + " (month to date)"
    elif kind == "year":
        s, e, label = today.replace(month=1, day=1), now_l, f"{now_l.year} (year to date)"
    elif kind == "custom":
        s = pd.Timestamp(start_date).tz_localize(tz)
        e_day = pd.Timestamp(end_date).tz_localize(tz) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        e = min(e_day, now_l)
        label = f"{s:%d %b %Y} to {pd.Timestamp(end_date):%d %b %Y}"
        if s > now_l:
            raise ValueError("The start date is in the future.")
        if pd.Timestamp(end_date) < pd.Timestamp(start_date):
            raise ValueError("The end date is before the start date.")
    else:
        raise ValueError("unknown period")
    return {"kind": kind, "start": s, "end": e, "start_utc": s.tz_convert("UTC"), "end_utc": e.tz_convert("UTC"),
            "label": label, "now_utc": now_l.tz_convert("UTC")}


# ------------------------------------------------------------------ profile reading

ALIASES = {
    "ph": ["ph"],
    "turbidity": ["turbidity", "turbidity_ntu", "ntu"],
    "tds": ["tds", "tds_ppm", "tds_mgl", "total dissolved solids", "total_dissolved_solids"],
    "do": ["do", "do_mg_l", "dissolved oxygen", "dissolved_oxygen", "oxygen"],
    "temperature": ["temperature", "temperature_c", "temp"],
}
LO_KEYS = ["min", "minimum", "lower", "lo", "low", "min_value", "lower_limit", "min_limit", "lower_bound"]
HI_KEYS = ["max", "maximum", "upper", "hi", "high", "max_value", "upper_limit", "max_limit", "upper_bound"]
BASIS_KEYS = ["basis", "compare", "compare_as", "compared", "mode", "averaging", "average", "window", "method", "compare_by"]
REF_KEYS = ["policy", "policy_ref", "policy_reference", "reference", "ref", "source", "regulation", "standard"]
POLICY_KEYS = ["policies", "policy", "policy_reference", "regulation", "regulations", "obligations", "conditions",
               "requirements", "policy_notes", "other_policies", "notes", "consent_conditions"]
NAME_KEYS = ["name", "company", "company_name", "organisation", "organization", "firm", "firm_name", "profile_name"]


def _alias_param(key):
    k = re.sub(r"\(.*?\)", "", str(key)).strip().lower().replace("-", "_")
    k = re.sub(r"\s+(ntu|mg/l|ppm|c|°c)$", "", k).strip()
    for p, names in ALIASES.items():
        if k == p or k in names or k in [n.replace(" ", "_") for n in names] or k.replace(" ", "_") in names:
            return p
    return None


def _num(v):
    try:
        if v is None or v == "":
            return None
        x = float(v)
        return x if np.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _first(d, keys):
    low = {str(k).lower(): v for k, v in d.items()}
    for k in keys:
        if k in low and low[k] not in (None, ""):
            return low[k]
    return None


def _basis(v):
    s = str(v or "").lower()
    if "24" in s:
        return "mean_24h"
    if re.search(r"\b1\s*(h|hr|hour)", s) or "hourly" in s or s.strip() in ("1h", "1 h"):
        return "mean_1h"
    return "reading"


def _looks_like_profile(d):
    if not isinstance(d, dict):
        return False
    if isinstance(d.get("limits"), (dict, list)):
        return True
    return any(_alias_param(k) for k in d.keys())


def find_profiles(raw):
    # returns [(name, profile_dict)] from whatever shape the saved json has
    out = []
    if isinstance(raw, list):
        for i, item in enumerate(raw):
            if _looks_like_profile(item):
                out.append((str(_first(item, NAME_KEYS) or f"Profile {i + 1}"), item))
    elif isinstance(raw, dict):
        if _looks_like_profile(raw):
            out.append((str(_first(raw, NAME_KEYS) or "Profile"), raw))
        else:
            for k, v in raw.items():
                if isinstance(v, (dict, list)) and k not in ("meta", "version"):
                    if isinstance(v, dict) and _looks_like_profile(v):
                        out.append((str(_first(v, NAME_KEYS) or k), v))
                    else:
                        out.extend(find_profiles(v))
    return out


def normalise_profile(name, prof):
    # -> {"name", "limits": {param: dict}, "policies": [str], "warnings": [str]}
    limits, warns = {}, []
    box = prof.get("limits", prof)
    items = []
    if isinstance(box, dict):
        items = list(box.items())
    elif isinstance(box, list):
        for it in box:
            if isinstance(it, dict):
                items.append((_first(it, ["parameter", "param", "name", "key"]), it))
    for key, v in items:
        p = _alias_param(key)
        if p is None:
            continue
        if isinstance(v, (list, tuple)) and len(v) == 2:
            lo, hi, basis, ref = _num(v[0]), _num(v[1]), "reading", ""
        elif isinstance(v, dict):
            lo, hi = _num(_first(v, LO_KEYS)), _num(_first(v, HI_KEYS))
            basis, ref = _basis(_first(v, BASIS_KEYS)), str(_first(v, REF_KEYS) or "").strip()
        else:
            continue
        if lo is None and hi is None:
            continue
        if lo is not None and hi is not None and lo > hi:
            warns.append(f"{LABEL[p]}: the minimum is above the maximum, so this limit was skipped.")
            continue
        limits[p] = {"lo": lo, "hi": hi, "basis": basis, "ref": ref}
    pol = []
    for k in POLICY_KEYS:
        v = _first(prof, [k])
        if isinstance(v, str):
            pol += [x.strip(" -*\t") for x in re.split(r"[\n;]+", v) if x.strip(" -*\t")]
        elif isinstance(v, list):
            for x in v:
                if isinstance(x, str) and x.strip():
                    pol.append(x.strip())
                elif isinstance(x, dict):
                    t = " - ".join(str(y) for y in x.values() if y not in (None, ""))
                    if t:
                        pol.append(t)
        elif isinstance(v, dict) and k != "limits":
            for kk, x in v.items():
                if isinstance(x, str) and x.strip():
                    pol.append(f"{kk}: {x.strip()}")
    seen, uniq = set(), []
    for x in pol:
        if x.lower() not in seen:
            seen.add(x.lower())
            uniq.append(x)
    return {"name": name, "limits": limits, "policies": uniq, "warnings": warns}


def load_profiles(path=None):
    import json
    path = path or config.COMPLIANCE_PATH
    try:
        raw = json.loads(open(path, encoding="utf-8").read())
    except FileNotFoundError:
        return [], "no saved compliance profile found"
    except Exception as e:
        return [], f"the saved profile file could not be read ({e})"
    profs = [normalise_profile(n, p) for n, p in find_profiles(raw)]
    profs = [p for p in profs if p["limits"] or p["policies"]]
    return profs, ("" if profs else "the saved file has no limits that this report could read")


def pick_profile(profiles, org, strict=False):
    # strict = only a profile whose name matches the account's company name, never somebody else's
    if not profiles:
        return None
    o = (org or "").strip().lower()
    if o:
        for p in profiles:
            if p["name"].strip().lower() == o:
                return p
        for p in profiles:
            n = p["name"].strip().lower()
            if min(len(n), len(o)) >= 4 and (o in n or n in o):
                return p
    if strict:
        return None
    return profiles[0] if len(profiles) == 1 else None


# ------------------------------------------------------------------ statistics

def param_stats(series, start, end, eff_start, cad):
    expected = max(1.0, (end - eff_start).total_seconds() / 60.0 / cad)
    rows = []
    for p in config.PARAMS:
        s = series[p]
        s = s[(s.index >= start) & (s.index <= end)].dropna()
        r = {"param": p, "n": int(len(s)), "completeness": min(1.0, len(s) / expected)}
        if len(s):
            r.update(min=float(s.min()), min_at=s.idxmin(), max=float(s.max()), max_at=s.idxmax(), mean=float(s.mean()),
                     median=float(s.median()), std=float(s.std(ddof=1)) if len(s) > 1 else float("nan"),
                     p05=float(s.quantile(0.05)), p95=float(s.quantile(0.95)), last=float(s.iloc[-1]), last_at=s.index[-1])
        rows.append(r)
    return rows


def daily_table(series, start, end):
    cols = {}
    for p in config.PARAMS:
        s = series[p]
        s = s[(s.index >= start) & (s.index <= end)].dropna()
        if s.empty:
            continue
        loc = s.copy()
        loc.index = loc.index.tz_convert(config.DISPLAY_TZ)
        g = loc.groupby(loc.index.date)
        for name, f in (("mean", g.mean()), ("min", g.min()), ("max", g.max())):
            cols[f"{p}_{name}"] = f
    if not cols:
        return pd.DataFrame()
    d = pd.DataFrame(cols)
    d.index.name = "date"
    return d.round(3)


# ------------------------------------------------------------------ limits

def basis_series(s, basis, cad):
    if basis == "reading":
        return s.dropna()
    win, mins = ("1h", 60) if basis == "mean_1h" else ("24h", 1440)
    need = max(1, int(math.ceil(0.5 * mins / cad)))
    return s.rolling(win, min_periods=need).mean().dropna()


def value_state(v, lo, hi):
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        return "outside"
    if lo is not None and hi is not None:
        margin = CLOSE_SHARE * (hi - lo)
    else:
        margin = CLOSE_SHARE * abs(lo if lo is not None else hi)
    if hi is not None and v >= hi - margin:
        return "close"
    if lo is not None and v <= lo + margin:
        return "close"
    return "within"


def limit_text(lim, p):
    u = UNIT.get(p, "")
    sp = (" " + u) if u else ""
    if lim["lo"] is not None and lim["hi"] is not None:
        return f"{lim['lo']:g} to {lim['hi']:g}{sp}"
    if lim["hi"] is not None:
        return f"max {lim['hi']:g}{sp}"
    return f"min {lim['lo']:g}{sp}"


BASIS_TEXT = {"reading": "each reading", "mean_1h": "1 h average", "mean_24h": "24 h average"}


def find_runs(v, bad, cad, lo, hi):
    if not bad.any():
        return []
    t = v.index.values.astype("datetime64[s]").astype("int64")
    gap = max(3 * cad, 30) * 60
    brk = np.r_[True, np.diff(t) > gap]
    isbad = bad.values
    prev = np.r_[False, isbad[:-1]]
    new = isbad & (~prev | brk)
    gid = np.cumsum(new)
    runs = []
    for g in np.unique(gid[isbad]):
        m = isbad & (gid == g)
        vv = v[m]
        dev = np.zeros(len(vv))
        if hi is not None:
            dev = np.maximum(dev, vv.values - hi)
        if lo is not None:
            dev = np.maximum(dev, lo - vv.values)
        k = int(np.argmax(dev))
        direction = "above" if (hi is not None and vv.values[k] > hi) else "below"
        runs.append({"start": vv.index[0], "end": vv.index[-1], "n": int(m.sum()),
                     "minutes": (vv.index[-1] - vv.index[0]).total_seconds() / 60.0 + cad,
                     "peak": float(vv.values[k]), "direction": direction})
    return runs


def evaluate_limit(p, lim, s_full, start, end, eff_start, cad, now, events):
    expected = max(1.0, (end - eff_start).total_seconds() / 60.0 / cad)
    b = basis_series(s_full, lim["basis"], cad)
    b = b[(b.index >= start) & (b.index <= end)]
    n_eval = int(len(b))
    res = {"param": p, "limit": lim, "n_eval": n_eval, "completeness": min(1.0, n_eval / expected),
           "runs": [], "pct_out": 0.0, "n_sustained": 0, "n_brief": 0, "longest_min": 0.0, "peak": None,
           "last": None, "last_at": None, "last_state": "nodata", "status": "nodata"}
    if n_eval == 0:
        return res
    lo, hi = lim["lo"], lim["hi"]
    bad = pd.Series(False, index=b.index)
    if lo is not None:
        bad |= b < lo
    if hi is not None:
        bad |= b > hi
    res["pct_out"] = float(bad.mean() * 100)
    runs = find_runs(b, bad, cad, lo, hi)
    for r in runs:
        r["linked_event"] = any(p in e.params and e.start <= r["end"] and e.end >= r["start"] for e in events)
    res["runs"] = runs
    res["n_sustained"] = sum(1 for r in runs if r["n"] >= SUSTAINED_N)
    res["n_brief"] = len(runs) - res["n_sustained"]
    res["longest_min"] = max([r["minutes"] for r in runs], default=0.0)
    if runs:
        worst = max(runs, key=lambda r: abs(r["peak"] - (hi if r["direction"] == "above" else lo)))
        res["peak"] = worst["peak"]
    res["last"], res["last_at"] = float(b.iloc[-1]), b.index[-1]
    current = end >= now - pd.Timedelta(minutes=60)
    stale = current and (now - res["last_at"]) > pd.Timedelta(minutes=max(config.STALE_AFTER_MINUTES, 6 * cad))
    res["stale"] = bool(stale)
    res["last_state"] = "nodata" if stale else value_state(res["last"], lo, hi)
    if n_eval < MIN_EVAL or res["completeness"] < MIN_COMPLETE:
        res["status"] = "nodata"
    elif res["n_sustained"] > 0:
        res["status"] = "exceeds"
    elif res["n_brief"] > 0:
        res["status"] = "brief"
    else:
        res["status"] = "meets"
    return res


STATUS_TEXT = {"meets": "Meets the limit (screening)", "brief": "Brief excursions only",
               "exceeds": "Does not meet the limit (screening)", "nodata": "Not enough data"}
STATE_TEXT = {"within": "Within", "close": "Close to limit", "outside": "Outside", "nodata": "No recent data"}


# ------------------------------------------------------------------ models and insights

def _mid(A, cnt, window, full):
    # middle value of each row (NaN counted as missing, NaN sit at the end after sorting)
    r = np.arange(len(A))
    out = np.full(len(A), np.nan)
    if full.any():
        P = np.partition(A[full], [window // 2 - 1, window // 2], axis=1) if window % 2 == 0 else np.partition(A[full], window // 2, axis=1)
        out[full] = (P[:, window // 2 - 1] + P[:, window // 2]) / 2.0 if window % 2 == 0 else P[:, window // 2]
    part = ~full
    if part.any():
        Ap, cp = A[part], cnt[part]
        srt = np.sort(Ap, axis=1)
        rr = np.arange(len(Ap))
        lo = np.clip((cp - 1) // 2, 0, window - 1)
        hi = np.clip(cp // 2, 0, window - 1)
        out[part] = (srt[rr, lo] + srt[rr, hi]) / 2.0
    return out


def _rolling_med_mad(x, window, min_p, chunk=20000):
    # median and median absolute deviation of each window (same numbers as the slow rolling.apply version)
    from numpy.lib.stride_tricks import sliding_window_view
    n = len(x)
    view = sliding_window_view(np.concatenate([np.full(window - 1, np.nan), x]), window)
    med = np.full(n, np.nan)
    mad = np.full(n, np.nan)
    for s in range(0, n, chunk):
        W = view[s:s + chunk]
        cnt = (~np.isnan(W)).sum(axis=1)
        full = cnt == window
        m = _mid(W, cnt, window, full)
        d = _mid(np.abs(W - m[:, None]), cnt, window, full)
        ok = cnt >= min_p
        med[s:s + chunk] = np.where(ok, m, np.nan)
        mad[s:s + chunk] = np.where(ok, d, np.nan)
    return med, mad


def fast_signals(grid, cad):
    base_steps = int(round(config.BASELINE_HOURS * 60 / cad))
    excl = max(1, int(round(config.EXCLUSION_HOURS * 60 / cad)))
    min_p = max(10, int(config.MIN_BASELINE_FRACTION * base_steps))
    med, sig, zs, pers = {}, {}, {}, {}
    for p in config.PARAMS:
        x = grid[p].to_numpy(dtype=float)
        xs = np.concatenate([np.full(excl, np.nan), x[:-excl]]) if len(x) > excl else np.full(len(x), np.nan)
        m, mad = _rolling_med_mad(xs, base_steps, min_p)
        m = pd.Series(m, index=grid.index)
        s = (pd.Series(mad, index=grid.index) * 1.4826).clip(lower=config.MIN_SCALE[p])
        z = (grid[p] - m) / s
        up = (z > config.Z_THRESHOLD).astype(float).rolling(config.PERSIST_N).sum().eq(config.PERSIST_N)
        dn = (z < -config.Z_THRESHOLD).astype(float).rolling(config.PERSIST_N).sum().eq(config.PERSIST_N)
        med[p], sig[p], zs[p] = m, s, z
        pers[p] = up.astype(int) - dn.astype(int)
    return alerts.Signals(grid, pd.DataFrame(med), pd.DataFrame(sig), pd.DataFrame(zs), pd.DataFrame(pers), cad)


def run_events(df, start, end, cad, site_id):
    lead = start - pd.Timedelta(hours=config.BASELINE_HOURS + 1)
    sub = df[(df["timestamp"] >= lead) & (df["timestamp"] <= end)]
    if len(sub) < 30:
        return [], "not enough readings for the unusual-change check"
    vals = pd.DataFrame({p: usable_series(sub, p) for p in config.PARAMS})
    grid = vals.resample(f"{cad}min").mean()
    try:
        sig = fast_signals(grid, cad)
        ev = alerts.detect_events(sig, site_id)
    except Exception as e:
        return [], f"the unusual-change check could not run ({e})"
    return [e for e in ev if e.end >= start and e.start <= end], ""


def pattern_note(ev):
    word = {"up": "rose", "down": "fell"}
    parts = [f"{LABEL[p]} {word[ev.direction[p]]}" for p in ev.params]
    if not parts:
        return "-"
    if len(parts) == 1:
        return parts[0] + " on its own. Pattern only; the cause is not confirmed."
    return ", ".join(parts[:-1]) + " and " + parts[-1] + " in the same period. Pattern only; the cause is not confirmed."


def whi_table(grid):
    w = {p: v for p, v in config.WHI_WEIGHTS.items() if v > 0 and p in grid.columns}
    if not w:
        return None
    sub = {}
    for p in w:
        xs, ys = zip(*config.WHI_CURVES[p])
        sub[p] = np.interp(grid[p].values, xs, ys)
    S = pd.DataFrame(sub, index=grid.index)
    S = S.where(grid[list(w)].notna())
    whi = (S * pd.Series(w)).sum(axis=1, skipna=False)
    return whi.dropna(), S.dropna(), w


NEXT_KIND = {"freshwater": "brackish", "brackish": "seawater"}


def zone_note(wt):
    # what the position of the TDS inside its range means (middle / upper end / border / tidal)
    if wt is None or not wt.data_kind:
        return ""
    z, k = wt.data_zone, wt.data_kind
    if z == "middle":
        return f"TDS is in the typical range for {k} water, so the standard {k} settings apply."
    if z == "upper":
        nxt = NEXT_KIND.get(k)
        if nxt:
            return (f"TDS is at the upper end of the {k} range and could move into {nxt} water at times (for example with tides or dry weather). "
                    "Review the water type setting if that happens.")
        return "TDS is very high even for sea water. Check the TDS sensor range and calibration, because many TDS probes cannot read this high."
    if z == "border":
        out = f"TDS is close to the border between {k} and {wt.other} water."
        if not wt.mismatch:
            out += " For that reason TDS is not scored in the Water Health Index and a wider TDS alert floor is used."
        return out
    if z == "tidal":
        return "TDS swings widely, which looks tidal. The water is treated as brackish and TDS is not scored in the Water Health Index."
    return ""


def do_saturation(grid, kind):
    if "do" not in grid or "temperature" not in grid:
        return None
    sal = 0.0
    if kind in ("brackish", "seawater") and "tds" in grid:
        sal = np.clip(grid["tds"].values / 1000.0, 0, 42)
    sat = 100.0 * grid["do"].values / oxygen.do_saturation_mgl(grid["temperature"].values, sal, 0.0)
    out = pd.Series(sat, index=grid.index).dropna()
    return out if len(out) else None


def daily_cycle(series, start, end):
    out = {}
    for p in ("do", "ph", "temperature"):
        s = series[p]
        s = s[(s.index >= start) & (s.index <= end)].dropna()
        if len(s) < 50:
            continue
        loc = s.copy()
        loc.index = loc.index.tz_convert(config.DISPLAY_TZ)
        if len(set(loc.index.date)) < 3:
            continue
        h = loc.groupby(loc.index.hour).mean()
        if len(h) < 12:
            continue
        out[p] = {"amp": float(h.max() - h.min()), "peak_h": int(h.idxmax()), "low_h": int(h.idxmin())}
    return out


def has_flag_columns(df):
    return any((p + "_flag") in df.columns for p in config.PARAMS)


def quality_summary(df, start, end, cad):
    sub = df[(df["timestamp"] >= start) & (df["timestamp"] <= end)]
    rows = []
    for p in config.PARAMS:
        f = p + "_flag"
        if f not in sub.columns or sub.empty:
            continue
        bad = sub[f].astype(str)
        bad = bad[bad != "ok"]
        if len(bad):
            c = bad.value_counts()
            rows.append((p, int(len(bad)), ", ".join(f"{k} {v}" for k, v in c.items())))
    ts = pd.DatetimeIndex(sub["timestamp"]).sort_values().unique()
    gaps = []
    if len(ts) > 1:
        d = np.diff(ts.values.astype("datetime64[s]").astype("int64")) / 60.0
        lim = max(3 * cad, 30)
        for i in np.where(d > lim)[0]:
            gaps.append((ts[i], ts[i + 1], d[i]))
    return rows, gaps, int(len(sub))


# ------------------------------------------------------------------ advice

ADVICE = {
    ("ph", "above"): (["alkaline process water or cleaning chemicals (for example caustic or lime)",
                       "neutralisation or dosing not working as set",
                       "strong algae growth in warm, still water can raise pH in the afternoon"],
                      ["check neutralisation and dosing set-points, alarms and chemical stock",
                       "review discharge and cleaning logs for the times listed",
                       "take a sample at your outlet and measure pH with a calibrated meter or an accredited lab",
                       "re-calibrate the pH probe (two buffers) if the reading looks unrealistic"]),
    ("ph", "below"): (["acidic process water or cleaning chemicals", "neutralisation or dosing not working as set",
                       "organic matter breaking down can lower pH"],
                      ["check acid dosing and neutralisation set-points and alarms",
                       "review discharge and cleaning logs for the times listed",
                       "take an outlet sample and measure pH with a calibrated meter or an accredited lab",
                       "re-calibrate the pH probe (two buffers) if the reading looks unrealistic"]),
    ("turbidity", "above"): (["suspended solids in effluent or wash water",
                              "storm run-off or earth work near the site",
                              "stirred-up bottom sediment (tides, boats, dredging)",
                              "dirt or biofilm on the sensor window"],
                             ["inspect settling tanks, filters and sludge handling and backwash schedules",
                              "check erosion and run-off control around the site",
                              "clean the sensor window and compare with a grab sample",
                              "compare the dates with rainfall and tide records"]),
    ("tds", "above"): (["saline or high-ionic process water, brine, cooling-tower blow-down",
                        "reverse-osmosis reject or resin regeneration wastes",
                        "tidal mixing or salt-water intrusion if the water is estuarine"],
                       ["compare the TDS or conductivity at your outlet with the buoy",
                        "review blow-down, regeneration and reject schedules for the times listed",
                        "check that the water type set for your account (fresh, brackish, sea) fits the site"]),
    ("do", "below"): (["organic load (high BOD or COD) using up oxygen",
                       "warm water holds less oxygen",
                       "still water and night-time respiration by algae or plants"],
                      ["check aeration and organic-load removal in your treatment",
                       "review organic and nutrient discharges for the times listed",
                       "check the DO probe cap and calibration, and take a sample near dawn when DO is usually lowest",
                       "ask whether your policy also sets BOD or COD limits; the buoy does not measure them"]),
    ("temperature", "above"): (["warm cooling-water or process discharge", "hot weather or low water movement"],
                               ["check the cooling system and the temperature of your discharge",
                                "compare with air temperature and with a reading away from your outlet"]),
    ("temperature", "below"): (["cold-water inflow or weather", "sensor fault"],
                               ["check the sensor and compare with a hand thermometer"]),
}
GENERIC = (["a real change in the water", "a sensor fault or calibration drift"],
           ["check the sensor and its calibration record", "take a sample and measure it with a calibrated meter or accredited lab",
            "review plant and discharge logs for the times listed"])

KW = {"ph": r"\bph\b|acid|alkalin", "turbidity": r"turbid|suspended|\bntu\b|\btss\b",
      "tds": r"\btds\b|dissolved solids|salin|conductiv|chlorid", "do": r"dissolved oxygen|\bdo\b|oxygen|\bbod\b|\bcod\b",
      "temperature": r"temperature|thermal|cooling"}


def advice_for(p, direction):
    return ADVICE.get((p, direction), GENERIC)


# ------------------------------------------------------------------ report

@dataclass
class Report:
    doc: list = field(default_factory=list)
    tables: dict = field(default_factory=dict)
    summary: dict = field(default_factory=dict)
    images: list = field(default_factory=list)


def _png(fig):
    import matplotlib.pyplot as plt
    b = io.BytesIO()
    fig.savefig(b, format="png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    return b.getvalue()


def chart_param(p, s, lim, events, start, end, cad):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    s = s[(s.index >= start) & (s.index <= end)].dropna()
    if s.empty:
        return None
    tz = config.DISPLAY_TZ
    fig, ax = plt.subplots(figsize=(7.2, 2.3))
    if len(s) > 2000:
        mins = max(cad, int(math.ceil((end - start).total_seconds() / 60 / 1000)))
        g = s.resample(f"{mins}min")
        m, lo_, hi_ = g.mean().dropna(), g.min().dropna(), g.max().dropna()
        ax.fill_between(lo_.index.tz_convert(tz), lo_.values, hi_.reindex(lo_.index).values, color="#9ecae1", alpha=0.5, lw=0)
        ax.plot(m.index.tz_convert(tz), m.values, color="#08519c", lw=0.9)
    else:
        ax.plot(s.index.tz_convert(tz), s.values, color="#08519c", lw=0.9)
    if lim:
        if lim["hi"] is not None:
            ax.axhline(lim["hi"], color="#cb181d", ls="--", lw=1)
        if lim["lo"] is not None:
            ax.axhline(lim["lo"], color="#cb181d", ls="--", lw=1)
    for e in events:
        if p in e.params:
            ax.axvspan(e.start.tz_convert(tz), e.end.tz_convert(tz), color="#fdae6b", alpha=0.45, lw=0)
    ax.set_ylabel(UNIT.get(p, "") or "pH", fontsize=8)
    ax.set_title(LABEL[p], fontsize=9, loc="left")
    span_days = (end - start).total_seconds() / 86400
    loc = mdates.AutoDateLocator(tz=tz)
    ax.xaxis.set_major_locator(loc)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M" if span_days <= 2 else "%d %b", tz=tz))
    ax.tick_params(labelsize=7)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    return _png(fig)


def chart_whi(whi, start, end):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    tz = config.DISPLAY_TZ
    w = whi
    if (end - start) > pd.Timedelta(days=3):
        w = whi.resample("1D").mean().dropna()
    fig, ax = plt.subplots(figsize=(7.2, 2.3))
    ax.plot(w.index.tz_convert(tz), w.values, color="#006d2c", lw=1)
    ax.set_ylim(0, 102)
    ax.set_ylabel("score", fontsize=8)
    ax.set_title("Water Health Index (provisional)", fontsize=9, loc="left")
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(tz=tz))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M" if (end - start) <= pd.Timedelta(days=2) else "%d %b", tz=tz))
    ax.tick_params(labelsize=7)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    return _png(fig)


def build_report(df, site, period, profile, wt, user, is_demo=False, extra_policies=None, charts=True):
    # df: processed readings of the site, profile: normalised profile or None, wt: WaterTypeResult
    R = Report()
    d = df.copy()
    d["timestamp"] = pd.to_datetime(d["timestamp"], utc=True)
    start, end, now = period["start_utc"], period["end_utc"], period["now_utc"]
    site_id, site_name = site["id"], site["name"]
    org = (user or {}).get("org") or (profile or {}).get("name") or "your organisation"
    doc = R.doc
    doc.append({"t": "title", "text": "JalDrishti water-quality report"})
    meta = [("Prepared for", org), ("Site", site_name), ("Period", period["label"] + f"  ({ist(start)} to {ist(end)}, IST)"),
            ("Generated", ist(now))]
    water = "not set"
    if wt is not None and wt.kind:
        water = {"freshwater": "Freshwater", "brackish": "Brackish water", "seawater": "Seawater"}[wt.kind]
        water += " (auto-detected from TDS)" if wt.source == "auto" else " (selected by you)"
        if wt.tds_median:
            water += f"; recent TDS about {wt.tds_median:,.0f} mg/L"
    meta.append(("Water type used", water))
    doc.append({"t": "meta", "items": meta})
    if is_demo:
        doc.append({"t": "callout", "level": "warn", "text": "DEMO DATA. The readings in this report are synthetic and are not from a real water body."})

    series = {p: usable_series(d, p) for p in config.PARAMS}
    sub = d[(d["timestamp"] >= start) & (d["timestamp"] <= end)]
    cad = alerts.infer_cadence(d)
    if sub.empty:
        doc.append({"t": "callout", "level": "warn", "text": "There are no readings for this period, so no report can be made. Choose another period or check that the buoy is sending data."})
        R.summary = {"status": "nodata", "readings": 0}
        return R
    first_ever = d["timestamp"].min()
    eff_start = max(start, first_ever)

    stats = param_stats(series, start, end, eff_start, cad)
    n_total = len(sub)
    expected = max(1.0, (end - eff_start).total_seconds() / 60.0 / cad)
    coverage = min(1.0, n_total / expected)

    events, ev_note = run_events(d, start, end, cad, site_id)

    limits = (profile or {}).get("limits", {})
    lim_res = {}
    for p, lim in limits.items():
        lead = start - pd.Timedelta(hours=25)
        s_full = series[p][(series[p].index >= lead) & (series[p].index <= end)]
        lim_res[p] = evaluate_limit(p, lim, s_full, start, end, eff_start, cad, now, events)

    vals = pd.DataFrame({p: series[p][(series[p].index >= start) & (series[p].index <= end)] for p in config.PARAMS})
    grid = vals.resample(f"{cad}min").mean() if len(vals) else vals
    whi_res = whi_table(grid) if len(grid) else None
    sat = do_saturation(grid, wt.kind if wt else None) if len(grid) else None
    cyc = daily_cycle(series, start, end)
    q_rows, gaps, n_rows = quality_summary(d, start, end, cad)

    statuses = [r["status"] for r in lim_res.values()]
    if not lim_res:
        overall = "nolimits"
    elif "exceeds" in statuses:
        overall = "exceeds"
    elif "brief" in statuses:
        overall = "brief"
    elif all(s == "nodata" for s in statuses):
        overall = "nodata"
    elif "nodata" in statuses:
        overall = "partial"
    else:
        overall = "meets"

    # ---------------- findings
    findings = []
    for p, r in lim_res.items():
        if r["status"] in ("exceeds", "brief"):
            dirs = {x["direction"] for x in r["runs"]}
            direction = "above" if "above" in dirs else "below"
            factors, steps = advice_for(p, direction)
            long_h = r["longest_min"] / 60
            sev = "high" if (r["status"] == "exceeds" and (r["pct_out"] >= 5 or long_h >= 6)) else ("medium" if r["status"] == "exceeds" else "low")
            linked = sum(1 for x in r["runs"] if x["linked_event"])
            what = (f"{LABEL[p]} was outside your limit ({limit_text(r['limit'], p)}, {BASIS_TEXT[r['limit']['basis']]}) in "
                    f"{r['pct_out']:.1f}% of {r['n_eval']} compared readings, in {len(r['runs'])} period(s) "
                    f"({r['n_sustained']} lasting {SUSTAINED_N} or more readings). Longest: {hhmm(r['longest_min'])}. "
                    f"Most extreme value: {val(r['peak'], p)}.")
            if linked:
                what += f" {linked} of these periods overlapped an unusual-change flag."
            pol = [limits[p]["ref"]] if limits[p]["ref"] else []
            findings.append({"sev": sev, "title": f"{LABEL[p]} outside the limit you entered" if r["status"] == "exceeds"
                             else f"{LABEL[p]}: brief excursions outside the limit", "what": what,
                             "factors": factors, "steps": steps + (["if these are isolated spikes, check the sensor first before treating them as a real change"] if r["status"] == "brief" else []),
                             "policy": pol})
        elif r["status"] in ("meets",) and r["last_state"] == "close":
            findings.append({"sev": "low", "title": f"{LABEL[p]} is close to its limit",
                             "what": f"The last {LABEL[p]} value ({val(r['last'], p)}) is within {int(CLOSE_SHARE * 100)}% of the limit ({limit_text(r['limit'], p)}), although no sustained period outside was found.",
                             "factors": ["normal variation approaching the limit"],
                             "steps": ["watch the trend, and consider checking the process or controls that affect this parameter before the limit is reached"], "policy": []})
    if events:
        ongoing = any(e.ongoing for e in events)
        strong = any(e.strength == "high" for e in events)
        sev = "high" if ongoing else ("medium" if strong else "low")
        plist = sorted({p for e in events for p in e.params})
        findings.append({"sev": sev, "title": f"{len(events)} unusual-change flag(s) in this period",
                         "what": f"The statistical check flagged readings that moved well away from their usual values for: {', '.join(LABEL[p] for p in plist)}. A flag means unusual behaviour, not confirmed pollution, and it does not name a cause.",
                         "factors": ["a real change in the water (for example discharge, rain run-off, tide)", "a sensor problem or calibration drift",
                                     "a normal daily cycle at a very steady site (the check has no daily-cycle allowance)"],
                         "steps": ["compare the flagged times with plant, discharge and maintenance logs", "check the sensor and take a sample while a change is happening",
                                   "keep a short note of what was found for each flagged time"], "policy": []})
    if coverage < 0.8:
        findings.append({"sev": "high" if coverage < 0.5 else "medium", "title": "Data gaps reduce what can be concluded",
                         "what": f"Only {coverage * 100:.0f}% of the expected readings were received ({n_total} of about {expected:.0f}). Longest gap: "
                                 f"{(max((g[2] for g in gaps), default=0)) / 60:.1f} h.",
                         "factors": ["power or battery problem", "network or MQTT connection loss", "sensor or device fault"],
                         "steps": ["check the buoy power, network and sensor cables", "use the offline logging card (when fitted) to recover missed readings",
                                   "if limits must be shown for the whole period, add manual or laboratory samples for the gaps"], "policy": []})
    flat = [p for p, n, txt in q_rows if "flatline" in txt or "implausible" in txt]
    if flat:
        findings.append({"sev": "medium", "title": "Some sensors show stuck or impossible values",
                         "what": "Quality flags (stuck or implausible readings) were found for: " + ", ".join(LABEL[p] for p in flat) + ". Those readings were left out of all statistics and checks.",
                         "factors": ["fouled, damaged or unplugged sensor", "calibration drift"],
                         "steps": ["clean and inspect the sensor and re-calibrate it", "record the calibration date and the reference solution used"], "policy": []})
    if sat is not None:
        low_share = float((sat < LOW_SAT).mean() * 100)
        if low_share >= 5:
            findings.append({"sev": "medium", "title": "Dissolved oxygen was often low for the temperature and salinity",
                             "what": f"Oxygen was below {LOW_SAT:.0f}% of what the water can hold in {low_share:.1f}% of the compared readings (average {sat.mean():.0f}%, lowest {sat.min():.0f}%). CPCB uses 60% saturation for its SW-I coastal class; this is a marker, not your limit.",
                             "factors": ADVICE[("do", "below")][0], "steps": ADVICE[("do", "below")][1], "policy": []})
    if wt is not None and wt.mismatch:
        findings.append({"sev": "medium", "title": "The water type set for your account may not fit the data",
                         "what": f"TDS is about {wt.tds_median:,.0f} mg/L, which looks like {wt.data_kind}, but the account is set to {wt.kind}. Scores and limits that depend on the water type may be misleading.",
                         "factors": ["wrong setting", "sensor range or calibration problem"],
                         "steps": ["change the water type to auto-detect in Settings, or confirm the TDS sensor range and calibration"], "policy": []})
    order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: order[f["sev"]])

    # ---------------- document
    doc.append({"t": "h1", "text": "1. Summary"})
    lines = []
    lines.append(f"{n_total} readings were received in the period ({coverage * 100:.0f}% of the expected readings, one every {cad} min).")
    if overall == "nolimits":
        doc.append({"t": "callout", "level": "info", "text": "No limits were found in your company profile, so no limit screening was done. Add your limits in the Compliance limits tab."})
    else:
        msg = {"exceeds": ("bad", "Indicative result: readings were outside at least one limit you entered for a sustained period. This is a screening result from the buoy, not a legal decision."),
               "brief": ("warn", "Indicative result: only brief excursions outside your limits were found. Check the sensors before treating them as real."),
               "partial": ("warn", "Indicative result: no sustained excursions were found, but some limits could not be judged because there was not enough data."),
               "meets": ("ok", "Indicative result: readings stayed within all the limits you entered (screening only)."),
               "nodata": ("info", "There was not enough data to judge the limits you entered.")}[overall]
        doc.append({"t": "callout", "level": msg[0], "text": msg[1]})
    lines.append(f"Unusual-change flags: {len(events)}." if not ev_note else f"Unusual-change check: {ev_note}.")
    if whi_res is not None and len(whi_res[0]):
        lines.append(f"Water Health Index (provisional): average {whi_res[0].mean():.0f}, lowest {whi_res[0].min():.0f}.")
    if findings:
        lines.append("Main points: " + "; ".join(f["title"] for f in findings[:4]) + ".")
    else:
        lines.append("No problems were found by the checks in this report.")
    doc.append({"t": "bullets", "items": lines})

    doc.append({"t": "h1", "text": "2. Data summary and statistics"})
    doc.append({"t": "p", "text": "Only readings that passed the quality checks are used. Times are in IST."})
    rows = []
    for r in stats:
        p = r["param"]
        if r["n"] == 0:
            rows.append([lab(p), "0", "0%", "-", "-", "-", "-", "-", "-", "-", "-"])
            continue
        rows.append([lab(p), str(r["n"]), f"{r['completeness'] * 100:.0f}%", f"{fmt(r['min'], p)} ({ist(r['min_at'], False)})",
                     f"{fmt(r['max'], p)} ({ist(r['max_at'], False)})", fmt(r["mean"], p), fmt(r["median"], p), fmt(r["std"], p),
                     fmt(r["p05"], p), fmt(r["p95"], p), fmt(r["last"], p)])
    doc.append({"t": "table", "columns": ["Parameter", "Count", "Compl.", "Minimum", "Maximum", "Mean", "Median", "Std dev", "5th pct", "95th pct", "Last"],
                "rows": rows, "widths": [1.5, 0.8, 0.8, 1.5, 1.5, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8]})
    R.tables["summary_statistics"] = pd.DataFrame([{ "parameter": LABEL[r["param"]], "unit": UNIT[r["param"]], "readings": r["n"],
                                                     "completeness_pct": round(r["completeness"] * 100, 1),
                                                     **{k: (round(r[k], 4) if k in r else None) for k in ("min", "max", "mean", "median", "std", "p05", "p95", "last")},
                                                     "min_at": ist(r["min_at"]) if "min_at" in r else "", "max_at": ist(r["max_at"]) if "max_at" in r else ""} for r in stats])
    dt = daily_table(series, start, end)
    if not dt.empty:
        R.tables["daily_summary"] = dt.reset_index()
    rd = sub[["timestamp"] + [c for c in sub.columns if c in config.PARAMS or c.endswith("_flag")]].copy()
    rd["timestamp"] = rd["timestamp"].dt.tz_convert(config.DISPLAY_TZ).dt.strftime("%Y-%m-%d %H:%M:%S")
    R.tables["readings_in_period"] = rd

    if charts:
        for p in config.PARAMS:
            png = chart_param(p, series[p], limits.get(p), events, start, end, cad)
            if png:
                cap = f"{LABEL[p]} over the period."
                if p in limits:
                    cap += " Red dashed line = your limit" + (" (the check uses " + BASIS_TEXT[limits[p]['basis']] + ")." if limits[p]["basis"] != "reading" else ".")
                if any(p in e.params for e in events):
                    cap += " Orange bands = unusual-change flags."
                doc.append({"t": "img", "bytes": png, "caption": cap})

    doc.append({"t": "h1", "text": "3. Limits you entered: screening result"})
    if not lim_res:
        doc.append({"t": "p", "text": "No limits are available. Enter them in the Compliance limits tab."})
    else:
        doc.append({"t": "p", "text": "The buoy measures the water where it floats, not at your outlet. This screening shows whether the buoy readings were inside or outside the limits you entered; confirm any result with your own calibrated measurement or an accredited laboratory. Your policy may allow a share of readings above a limit; check it."})
        rows = []
        for p, r in lim_res.items():
            rows.append([lab(p), limit_text(r["limit"], p), BASIS_TEXT[r["limit"]["basis"]], str(r["n_eval"]), f"{r['pct_out']:.1f}%",
                         str(len(r["runs"])), hhmm(r["longest_min"]) if r["runs"] else "-", fmt(r["peak"], p) if r["peak"] is not None else "-",
                         (fmt(r["last"], p) + " - " + STATE_TEXT[r["last_state"]]) if r["last"] is not None else "-", STATUS_TEXT[r["status"]]])
        doc.append({"t": "table", "columns": ["Parameter", "Limit", "Compared as", "Count", "Out %", "Periods", "Longest", "Most extreme", "Last value", "Screening result"],
                    "rows": rows, "widths": [1.4, 1.2, 1.1, 0.8, 0.8, 0.9, 0.9, 1.0, 1.5, 1.8]})
        R.tables["limit_screening"] = pd.DataFrame([{"parameter": LABEL[p], "limit": limit_text(r["limit"], p), "compared_as": BASIS_TEXT[r["limit"]["basis"]],
                                                     "compared_readings": r["n_eval"], "pct_outside": round(r["pct_out"], 2), "periods_outside": len(r["runs"]),
                                                     "sustained_periods": r["n_sustained"], "longest_minutes": round(r["longest_min"], 1),
                                                     "most_extreme": r["peak"], "screening_result": STATUS_TEXT[r["status"]]} for p, r in lim_res.items()])
        prow = []
        for p, r in lim_res.items():
            for x in sorted(r["runs"], key=lambda x: x["start"])[:40]:
                prow.append({"parameter": LABEL[p], "start_ist": ist(x["start"]), "end_ist": ist(x["end"]), "duration": hhmm(x["minutes"]),
                             "readings": x["n"], "direction": x["direction"], "most_extreme": fmt(x["peak"], p),
                             "kind": "sustained" if x["n"] >= SUSTAINED_N else "brief", "unusual_change_flag_at_same_time": "yes" if x["linked_event"] else "no"})
        if prow:
            R.tables["limit_periods"] = pd.DataFrame(prow)
            doc.append({"t": "h2", "text": "Periods outside a limit (up to 15 shown; all are in the CSV)"})
            doc.append({"t": "table", "columns": ["Parameter", "Start", "End", "Duration", "Most extreme", "Kind", "Flag at same time"],
                        "rows": [[r["parameter"], r["start_ist"], r["end_ist"], r["duration"], r["most_extreme"], r["kind"], r["unusual_change_flag_at_same_time"]] for r in prow[:15]],
                        "widths": [1.4, 1.5, 1.5, 1.0, 1.0, 0.9, 1.1]})
        for w in (profile or {}).get("warnings", []):
            doc.append({"t": "p", "text": w})

    doc.append({"t": "h1", "text": "4. Insights from the models"})
    doc.append({"t": "h2", "text": "Unusual-change check (statistical baseline)"})
    if ev_note:
        doc.append({"t": "p", "text": ev_note[0].upper() + ev_note[1:] + "."})
    elif not events:
        doc.append({"t": "p", "text": "No unusual change was flagged. A flag needs 3 readings in a row far from the previous 24 h median."})
    else:
        erows = [[ist(e.start), ist(e.end), hhmm(e.duration_min) + (" (ongoing)" if e.ongoing else ""), ", ".join(f"{LABEL[p]} {e.direction[p]}" for p in e.params),
                  e.strength, pattern_note(e)] for e in events[:25]]
        doc.append({"t": "table", "columns": ["Start", "End", "Duration", "Parameters", "Level", "Pattern note"], "rows": erows,
                    "widths": [1.4, 1.4, 1.1, 1.8, 0.9, 3.0]})
        R.tables["unusual_change_events"] = pd.DataFrame([{"start_ist": ist(e.start), "end_ist": ist(e.end), "minutes": e.duration_min,
                                                           "parameters": ", ".join(LABEL[p] for p in e.params), "strength": e.strength,
                                                           "pattern_note": pattern_note(e)} for e in events])
        if len(events) > 25:
            doc.append({"t": "p", "text": f"The first 25 of {len(events)} flags are shown; all are in the CSV."})
    doc.append({"t": "h2", "text": "Water Health Index (provisional)"})
    if whi_res is None or not len(whi_res[0]):
        doc.append({"t": "p", "text": "The index could not be calculated because the sensors it needs did not have valid readings at the same time."})
    else:
        whi, S, w = whi_res
        weakest = S.idxmin(axis=1).value_counts(normalize=True)
        sub_means = ", ".join(f"{LABEL[p]} {S[p].mean():.0f}" for p in S.columns)
        doc.append({"t": "bullets", "items": [
            f"Average {whi.mean():.0f}, lowest {whi.min():.0f}, based on {len(whi)} readings where all needed sensors were valid.",
            "Average sub-scores (0 to 100): " + sub_means + ".",
            "Most often the lowest sub-score: " + ", ".join(f"{LABEL[p]} {v * 100:.0f}%" for p, v in weakest.head(3).items()) + ".",
            "No quality words such as good or poor are used: the cut-offs for them have no evidence behind them yet.",
            "The weights and curves are provisional. For brackish and sea water, TDS is not scored because salt is natural there; DO and pH use coastal-style curves." if (wt and wt.kind in ("brackish", "seawater")) else
            "The weights and curves are provisional and not taken from a regulation."]})
        if charts:
            doc.append({"t": "img", "bytes": chart_whi(whi, start, end), "caption": "Daily average of the provisional index."})
    doc.append({"t": "h2", "text": "Dissolved oxygen compared with what the water can hold"})
    if sat is None:
        doc.append({"t": "p", "text": "Not available: this needs valid temperature and dissolved oxygen readings at the same time."})
    else:
        extra = ""
        if wt and wt.kind in ("brackish", "seawater"):
            extra = " Salinity is estimated as TDS divided by 1000."
        doc.append({"t": "bullets", "items": [
            f"Average {sat.mean():.0f}% of saturation, lowest {sat.min():.0f}%, highest {sat.max():.0f}%.",
            f"Below {LOW_SAT:.0f}% in {float((sat < LOW_SAT).mean() * 100):.1f}% of readings; above {HIGH_SAT:.0f}% in {float((sat > HIGH_SAT).mean() * 100):.1f}% (very high values often go with strong algae growth; this marker is for screening only).",
            "Saturation is worked out from temperature and salinity with the Benson and Krause (1984) equations, assuming sea level." + extra]})
    doc.append({"t": "h2", "text": "Daily pattern"})
    if not cyc:
        doc.append({"t": "p", "text": "At least 3 days with readings across the day are needed to describe the daily pattern."})
    else:
        items = []
        for p, c in cyc.items():
            items.append(f"{LABEL[p]}: average daily swing {fmt(c['amp'], p)} {UNIT[p]}, highest around {c['peak_h']:02d}:00 and lowest around {c['low_h']:02d}:00 IST.")
        items.append("Daily swings in oxygen and pH are usual where there is plant or algae growth. The unusual-change check has no daily-cycle allowance, so some flags may be this cycle.")
        doc.append({"t": "bullets", "items": items})
    doc.append({"t": "h2", "text": "Water type check"})
    if wt is None or wt.tds_median is None:
        doc.append({"t": "p", "text": "There were not enough TDS readings to check the water type."})
    else:
        doc.append({"t": "p", "text": f"Recent TDS: median {wt.tds_median:,.0f} mg/L (5th to 95th percentile {wt.tds_p05:,.0f} to {wt.tds_p95:,.0f}). Data suggest {wt.data_kind} water" + (" with wide swings, likely tidal." if wt.data_zone == "tidal" else ".")})
        zn = zone_note(wt)
        if zn:
            doc.append({"t": "p", "text": zn})
    doc.append({"t": "h2", "text": "Machine-learning forecasts"})
    doc.append({"t": "p", "text": "No SINDy or XGBoost forecast is included. Those models were only tested on one development stream (HOPB) and have not been validated for this site, so their output would not be reliable here."})

    doc.append({"t": "h1", "text": "5. Problems found and suggested next steps"})
    if not findings:
        doc.append({"t": "p", "text": "No problems were found by the checks in this report. Continue routine monitoring, keep calibration records, and keep this report as part of your monitoring file."})
    for i, f in enumerate(findings, 1):
        lvl = {"high": "bad", "medium": "warn", "low": "info"}[f["sev"]]
        doc.append({"t": "callout", "level": lvl, "text": f"{i}. {f['title']}  [{f['sev']} priority]"})
        doc.append({"t": "p", "text": "What we see: " + f["what"]})
        doc.append({"t": "p", "text": "Possible contributing factors (not confirmed by the sensors):"})
        doc.append({"t": "bullets", "items": f["factors"]})
        doc.append({"t": "p", "text": "Suggested next steps:"})
        doc.append({"t": "bullets", "items": f["steps"]})
        if f["policy"]:
            doc.append({"t": "p", "text": "Related policy reference you entered: " + "; ".join(f["policy"])})

    doc.append({"t": "h1", "text": "6. Your policies and how the data compares"})
    pols = list((profile or {}).get("policies", [])) + [x for x in (extra_policies or []) if x.strip()]
    for p, lim in limits.items():
        if lim["ref"]:
            pols.append(f"{LABEL[p]} limit: {lim['ref']}")
    seen, plist2 = set(), []
    for x in pols:
        if x.lower() not in seen:
            seen.add(x.lower())
            plist2.append(x)
    if not plist2:
        doc.append({"t": "p", "text": "No policy text was found in your profile. Add the policies and permit conditions you must follow (one per line) in the Report tab, and they will be checked here."})
    else:
        prow = []
        for x in plist2:
            matched = [p for p, rx in KW.items() if re.search(rx, x, re.I)]
            shown, action = [], []
            for p in matched:
                if p in lim_res:
                    r = lim_res[p]
                    shown.append(f"{LABEL[p]} against the limit you entered ({limit_text(r['limit'], p)}): {STATUS_TEXT[r['status']]} ({r['pct_out']:.1f}% outside). The policy may use a different test.")
                    if r["status"] in ("exceeds", "brief"):
                        action.append(advice_for(p, "above" if any(y["direction"] == "above" for y in r["runs"]) else "below")[1][0])
                else:
                    st_ = next((s for s in stats if s["param"] == p and s["n"]), None)
                    shown.append(f"{LABEL[p]}: no numeric limit entered" + (f"; average {fmt(st_['mean'], p)}, range {fmt(st_['min'], p)} to {fmt(st_['max'], p)} {UNIT[p]}" if st_ else ""))
            if not matched:
                shown = ["Cannot be checked with these five sensors (for example a reporting duty, sampling plan, or a parameter such as BOD, COD, metals or coliform)."]
                action = ["Keep your own records or laboratory results as evidence, and confirm deadlines with your compliance officer."]
            elif not action:
                action = ["Keep the current controls, keep calibration and monitoring records as evidence."]
            prow.append([x, "; ".join(shown), " ".join(dict.fromkeys(action))])
        doc.append({"t": "table", "columns": ["Policy or requirement you entered", "What the buoy data shows", "Suggested action"], "rows": prow, "widths": [3.0, 3.2, 3.0]})
    doc.append({"t": "p", "text": "How to stay within your limits: keep the sensors clean and calibrated (record the date and reference solution), act on a trend before it reaches a limit, keep logs of discharges and maintenance next to the buoy data, and confirm important results with an accredited laboratory."})

    doc.append({"t": "h1", "text": "7. Data quality"})
    items = [f"{n_rows} rows in the period; the buoy normally sends one every {cad} min."]
    if q_rows:
        for p, n, txt in q_rows:
            items.append(f"{LABEL[p]}: {n} readings had a quality flag ({txt}) and were left out.")
    else:
        items.append("No quality flags were raised in this period." if has_flag_columns(d) else
                     "The per-sensor quality flags were not found in the processed table, so flag counts are not shown here. Readings that failed the checks are still left out of every statistic.")
    if gaps:
        longest = max(gaps, key=lambda g: g[2])
        items.append(f"{len(gaps)} gap(s) longer than {max(3 * cad, 30)} min; the longest was {longest[2] / 60:.1f} h starting {ist(longest[0])}.")
    else:
        items.append("No long gaps in the data.")
    if eff_start > start:
        items.append(f"The first reading from this site is on {ist(first_ever)}, so completeness is counted from then.")
    doc.append({"t": "bullets", "items": items})

    doc.append({"t": "h1", "text": "8. Method and limits of this report"})
    doc.append({"t": "bullets", "items": [
        "The buoy measures ambient water at its own position. It does not measure your outlet. Limits that apply at the outlet must be confirmed with your own measurement or an accredited laboratory.",
        "This is a rule-based screening. It is not a legal compliance decision. 'Meets' and 'Does not meet' only describe the readings against the limits you entered.",
        f"A period outside a limit is a run of consecutive readings outside it (a gap longer than max(3 readings, 30 min) ends the run). Fewer than {SUSTAINED_N} readings is called brief. 'Close to limit' means within {int(CLOSE_SHARE * 100)}% of the limit.",
        "Averages (1 h or 24 h) need at least half of the expected readings in the window.",
        "Unusual-change flags use the median of the previous 24 h (leaving out the last hour), a robust z-score above 3.5, and 3 readings in a row. They are untuned on field data, have no allowance for daily cycles, tides or rain, and cannot name a pollutant.",
        "The Water Health Index is provisional. The sensors cannot show that water is safe, and cannot identify a pollutant or its source.",
        "Water type is set from your choice or from the TDS readings (freshwater below about 500 mg/L, brackish about 500 to 30,000 mg/L, seawater above about 30,000 mg/L; points close to a boundary are marked as border).",
        "Hindi and Marathi are not included in this report."]})
    R.summary = {"status": overall, "readings": n_total, "coverage": coverage, "events": len(events),
                 "findings": len(findings), "whi_mean": float(whi_res[0].mean()) if whi_res is not None and len(whi_res[0]) else None,
                 "high": sum(1 for f in findings if f["sev"] == "high")}
    return R
