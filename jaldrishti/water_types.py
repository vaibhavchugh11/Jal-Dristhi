import copy
import threading
from dataclasses import dataclass

import numpy as np

from . import config
from .series_tools import usable_series

KINDS = ["freshwater", "brackish", "seawater"]
PREFS = ["auto"] + KINDS

# TDS limits in mg/L, roughly the usual fresh / brackish / sea split (0.5 and 30 parts per thousand)
FRESH_MAX = 500.0
SEA_MIN = 30000.0
SEA_UPPER = 40000.0
BORDER_SHARE = 0.10
UPPER_SHARE = 0.25
WIDE_TDS = (0, 70000)

AUTO_HOURS = 25
AUTO_FALLBACK_DAYS = 7
AUTO_MIN_READINGS = 12
SWING_RATIO = 1.5

# provisional curves for salty water (design choices, see docs)
SALINE_DO_CURVE = [(0, 0), (2, 0), (3.5, 60), (5, 100)]
SALINE_PH_CURVE = [(5.5, 0), (6.5, 100), (8.5, 100), (9.5, 0)]
BORDER_FLOOR_SHARE = 0.05
FLOOR_SHARE = 0.02

_lock = threading.Lock()
_KEYS = ["PLAUSIBLE", "WHI_CURVES", "WHI_WEIGHTS", "MIN_SCALE"]


@dataclass
class WaterTypeResult:
    pref: str
    kind: str = None
    zone: str = "unknown"      # middle, upper, border, tidal, unknown
    other: str = None          # neighbour kind when the zone is border
    source: str = "none"       # selected, auto, none
    tds_median: float = None
    tds_p05: float = None
    tds_p95: float = None
    n: int = 0
    data_kind: str = None
    data_zone: str = "unknown"
    mismatch: bool = False


def upper_start(kind):
    if kind == "freshwater":
        return FRESH_MAX * (1 - UPPER_SHARE)
    if kind == "brackish":
        lo, hi = np.log10(FRESH_MAX), np.log10(SEA_MIN)
        return float(10 ** (lo + (1 - UPPER_SHARE) * (hi - lo)))
    return SEA_UPPER


def kind_of(x):
    if x < FRESH_MAX:
        return "freshwater"
    if x < SEA_MIN:
        return "brackish"
    return "seawater"


def classify_tds(x):
    # returns (kind, zone, neighbour_kind)
    if x is None or not np.isfinite(x) or x < 0:
        return None, "unknown", None
    for b, low_kind, high_kind in ((FRESH_MAX, "freshwater", "brackish"), (SEA_MIN, "brackish", "seawater")):
        if abs(x - b) <= BORDER_SHARE * b:
            return (low_kind, "border", high_kind) if x < b else (high_kind, "border", low_kind)
    k = kind_of(x)
    return k, ("upper" if x >= upper_start(k) else "middle"), None


def recent_tds(df):
    s = usable_series(df, "tds").dropna()
    if s.empty:
        return s
    end = s.index.max()
    w = s[s.index >= end - np.timedelta64(AUTO_HOURS, "h")]
    if len(w) < AUTO_MIN_READINGS:
        w = s[s.index >= end - np.timedelta64(AUTO_FALLBACK_DAYS, "D")]
    return w


def resolve(pref, df):
    if pref not in PREFS:
        pref = "auto"
    w = recent_tds(df)
    res = WaterTypeResult(pref=pref, n=int(len(w)))
    if len(w) >= AUTO_MIN_READINGS:
        res.tds_median = float(w.median())
        res.tds_p05 = float(w.quantile(0.05))
        res.tds_p95 = float(w.quantile(0.95))
        res.data_kind, res.data_zone, res.other = classify_tds(res.tds_median)
        swing = (kind_of(res.tds_p05) != kind_of(res.tds_p95)
                 and res.tds_p95 / max(res.tds_p05, 1.0) >= SWING_RATIO)
        if swing:
            res.data_kind, res.data_zone, res.other = "brackish", "tidal", None
    if pref == "auto":
        res.source = "auto" if res.data_kind else "none"
        res.kind, res.zone = res.data_kind, res.data_zone
        return res
    res.source = "selected"
    res.kind = pref
    if res.data_kind is None:
        res.zone = "unknown"
    elif res.data_zone == "tidal":
        res.zone = "tidal"
        res.mismatch = pref != "brackish"
    elif res.data_zone == "border":
        if pref in (res.data_kind, res.other):
            res.zone = "border"
        else:
            res.mismatch = True
    elif res.data_kind == pref:
        res.zone = res.data_zone
    else:
        res.mismatch = True
    return res


def _round_floor(x):
    if x <= 5:
        return 5.0
    if x < 100:
        return float(round(x / 5.0) * 5)
    return float(round(x / 50.0) * 50)


def settings_for(res):
    # what changes in the config for this water type. freshwater in the middle/upper zone = repo defaults
    orig = config._JD_ORIG
    s = {k: copy.deepcopy(orig[k]) for k in _KEYS}
    s["PLAUSIBLE"]["tds"] = WIDE_TDS
    kind, zone = res.kind, res.zone
    if kind is None:
        return s
    if kind in ("brackish", "seawater"):
        s["WHI_CURVES"]["do"] = list(SALINE_DO_CURVE)
        s["WHI_CURVES"]["ph"] = list(SALINE_PH_CURVE)
    tds_scored = kind == "freshwater" and zone not in ("border", "tidal")
    if not tds_scored:
        s["WHI_CURVES"]["tds"] = [(0, 100), (WIDE_TDS[1], 100)]
        w = {k: v for k, v in orig["WHI_WEIGHTS"].items() if k != "tds"}
        tot = sum(w.values())
        s["WHI_WEIGHTS"] = {k: v / tot for k, v in w.items()}
        s["WHI_WEIGHTS"]["tds"] = 0.0
    if res.tds_median:
        share = BORDER_FLOOR_SHARE if zone in ("border", "tidal") else FLOOR_SHARE
        s["MIN_SCALE"]["tds"] = max(orig["MIN_SCALE"]["tds"], _round_floor(share * res.tds_median))
    return s


def _snapshot():
    if not hasattr(config, "_JD_ORIG"):
        config._JD_ORIG = {k: copy.deepcopy(getattr(config, k)) for k in _KEYS}


def _current():
    return {k: copy.deepcopy(getattr(config, k)) for k in _KEYS}


def _write(settings):
    for k in _KEYS:
        d = getattr(config, k)
        d.clear()
        d.update(copy.deepcopy(settings[k]))


def prepare_config():
    # call once when the app starts, before any data is analysed
    with _lock:
        _snapshot()
        base = settings_for(WaterTypeResult(pref="auto"))
        if _current() != base:
            _write(base)


def apply_calibration(res):
    # returns True if the config really changed (then cached results must be rebuilt)
    with _lock:
        _snapshot()
        new = settings_for(res)
        if _current() == new:
            return False
        _write(new)
        return True
