"""Colour coding of readings against Indian standards (CPCB and BIS).

A colour answers one question: which class of limit does this reading meet?
  1 green  = meets the strictest limit listed for that parameter
  2 yellow = meets an in-between limit
  3 orange = meets only the most relaxed limit
  4 red    = outside every limit listed

IMPORTANT: the numbers below were typed in from memory when the web was not reachable, so every
tier carries a "verify" flag. Check the ones marked True against the official documents before
anybody relies on them:
  CPCB  Water Quality Criteria (Designated Best Use classes A to E)
  CPCB  Water Quality Standards for Coastal Waters (SW-I to SW-V)
  BIS   IS 10500:2012 drinking water, IS 2296:1992 inland surface water
Change a number here and the whole app (panel, report, index) follows.
"""
import numpy as np

COLOURS = {1: "#2e9d4f", 2: "#f2c21b", 3: "#f28c28", 4: "#d64545"}
NAMES = {1: "Green", 2: "Yellow", 3: "Orange", 4: "Red"}
TEXT_ON = {1: "#ffffff", 2: "#222222", 3: "#222222", 4: "#ffffff"}
SCORE_AT = {1: 100.0, 2: 80.0, 3: 60.0}      # sub-score of a reading that sits exactly on a tier limit
GREY = "#9aa0a6"

# Overall Water Health Index bands. HIGHER IS BETTER: 100 is best, 0 is worst. These are the same cut-offs as the project's
# original METHODS file (95 / 80 / 65 / 45). They are provisional design choices with no regulation or study behind them.
# If config.WHI_BANDS exists in your project it is used instead, so there is one place to change them.
DEFAULT_BANDS = [(95, "Excellent"), (80, "Good"), (65, "Fair"), (45, "Marginal"), (0, "Poor")]
BAND_COLOURS = ["#1a9850", "#66bd63", "#f2c21b", "#f28c28", "#d73027"]      # best ... worst
BAND_TEXT_ON = ["#ffffff", "#1b1b1b", "#1b1b1b", "#1b1b1b", "#ffffff"]


def bands():
    try:
        from . import config
        b = [(float(a), str(n).capitalize()) for a, n in config.WHI_BANDS]
        if len(b) == len(BAND_COLOURS) and b == sorted(b, reverse=True):
            return b
    except Exception:
        pass
    return DEFAULT_BANDS


def band_index(score):
    """0 = best band ... 4 = worst band, or None when there is no score. A higher score is always a better band."""
    if score is None or score != score:
        return None
    for i, (lower, _) in enumerate(bands()):
        if score >= lower:
            return i
    return len(bands()) - 1


def band_name(score):
    i = band_index(score)
    return "no data" if i is None else bands()[i][1]


def band_colour(score):
    i = band_index(score)
    return GREY if i is None else BAND_COLOURS[i]


def band_text_on(score):
    i = band_index(score)
    return "#222222" if i is None else BAND_TEXT_ON[i]


def band_range_text(i):
    b = bands()
    hi = 100 if i == 0 else b[i - 1][0] - 1
    return f"{b[i][0]:g} to {hi:g}" if i else f"{b[0][0]:g} to 100"


BAND_PLAIN = {
    "Excellent": "The overall index is very high.",
    "Good": "The overall index is high.",
    "Fair": "The overall index is middling.",
    "Marginal": "The overall index is low.",
    "Poor": "The overall index is very low.",
}

STANDARDS = {
    "freshwater": {
        "do": {"label": "Dissolved oxygen", "unit": "mg/L", "shape": "min", "zero": 2.0, "tiers": {
            1: {"limit": 6.0, "std": "CPCB Class A", "use": "drinking water source without conventional treatment", "verify": False},
            2: {"limit": 5.0, "std": "CPCB Class B", "use": "outdoor bathing", "verify": False},
            3: {"limit": 4.0, "std": "CPCB Class C and D", "use": "drinking water with conventional treatment, fish and wildlife", "verify": False}}},
        "ph": {"label": "pH", "unit": "", "shape": "range", "zero_delta": 1.0, "tiers": {
            1: {"lo": 6.5, "hi": 8.5, "std": "CPCB Class A, B, D and BIS 10500", "use": "most uses", "verify": False},
            2: {"lo": 6.0, "hi": 9.0, "std": "CPCB Class C", "use": "drinking water with conventional treatment", "verify": False}}},
        "turbidity": {"label": "Turbidity", "unit": "NTU", "shape": "max", "zero": 25.0, "tiers": {
            1: {"limit": 1.0, "std": "BIS IS 10500 acceptable limit", "use": "drinking water", "verify": False},
            2: {"limit": 5.0, "std": "BIS IS 10500 permissible limit", "use": "drinking water when no other source exists", "verify": False}}},
        "tds": {"label": "Total dissolved solids", "unit": "mg/L", "shape": "max", "zero": 3000.0, "tiers": {
            1: {"limit": 500.0, "std": "CPCB Class A and BIS acceptable limit", "use": "drinking water", "verify": False},
            2: {"limit": 1500.0, "std": "CPCB Class C", "use": "drinking water with conventional treatment", "verify": False},
            3: {"limit": 2100.0, "std": "CPCB Class E", "use": "irrigation and industrial cooling (BIS permissible limit is 2000)", "verify": True}}},
    },
    "coastal": {
        "do": {"label": "Dissolved oxygen", "unit": "mg/L", "shape": "min_sat", "zero_ratio": 0.5, "tiers": {
            1: {"mgl": 5.0, "sat": 60.0, "std": "CPCB SW-I", "use": "salt pans, shell fishing, mariculture, sensitive zones", "verify": False},
            2: {"mgl": 4.0, "sat": 50.0, "std": "CPCB SW-II", "use": "bathing, contact sports, commercial fishing", "verify": True},
            3: {"mgl": 3.0, "sat": 40.0, "std": "CPCB SW-III, IV and V", "use": "industrial cooling, harbour, navigation", "verify": True}}},
        "ph": {"label": "pH", "unit": "", "shape": "range", "zero_delta": 1.0, "tiers": {
            1: {"lo": 6.5, "hi": 8.5, "std": "CPCB SW-I, II and III", "use": "", "verify": False},
            2: {"lo": 6.5, "hi": 9.0, "std": "CPCB SW-IV", "use": "harbour", "verify": True},
            3: {"lo": 6.0, "hi": 9.0, "std": "CPCB SW-V", "use": "navigation and controlled waste disposal", "verify": True}}},
        "turbidity": {"label": "Turbidity", "unit": "NTU", "shape": "max", "zero": 120.0, "tiers": {
            1: {"limit": 30.0, "std": "CPCB SW-II and SW-III", "use": "", "verify": True}}},
    },
}
NOT_GRADED = {
    "freshwater": ["temperature"],
    "coastal": ["tds", "temperature"],
}
NOT_GRADED_WHY = {
    "tds": "no ambient limit in brackish or sea water, where dissolved salt is natural",
    "temperature": "context only, no ambient limit",
}
LABEL = {"do": "Dissolved oxygen", "ph": "pH", "turbidity": "Turbidity", "tds": "TDS", "temperature": "Temperature"}
UNIT = {"do": "mg/L", "ph": "", "turbidity": "NTU", "tds": "mg/L", "temperature": "°C"}

PLAIN = {
    "do": {1: "plenty of oxygen", 2: "oxygen is a little below the best range", 3: "oxygen is low", 4: "oxygen is very low"},
    "ph": {1: "balanced, not too acidic or alkaline", 2: "slightly outside the best range", 3: "clearly outside the best range", 4: "far outside the best range"},
    "turbidity": {1: "clear", 2: "a little cloudier than the strictest limit", 3: "cloudy", 4: "very cloudy"},
    "tds": {1: "low dissolved minerals", 2: "moderate dissolved minerals", 3: "high dissolved minerals", 4: "very high dissolved minerals"},
}


def group(kind):
    return "coastal" if kind in ("brackish", "seawater") else "freshwater"


def graded(kind):
    return list(STANDARDS[group(kind)])


def spec(param, kind):
    return STANDARDS[group(kind)].get(param)


def _tier_limits(sp, do_sat_mgl=None):
    out = {}
    for t, d in sp["tiers"].items():
        if sp["shape"] == "min_sat":
            sat = np.nan if do_sat_mgl is None else d["sat"] / 100.0 * np.asarray(do_sat_mgl, dtype=float)
            out[t] = np.fmax(d["mgl"], sat) if do_sat_mgl is not None else np.full(1, d["mgl"])
        else:
            out[t] = d.get("limit")
    return out


def _pl(x, points, zero):
    # score for a "higher is better" quantity. points = [(limit, score), ...] from the strictest to the most relaxed limit.
    # Past the most relaxed limit the score steps down to 59 or less and falls to 0 at `zero`, so a red reading
    # always has a score under 60 (and green = 100, yellow = 80 to 100, orange = 60 to 80)
    x = np.asarray(x, dtype=float)
    pts = [(np.broadcast_to(np.asarray(l, dtype=float), x.shape), float(sc)) for l, sc in points]
    z = np.broadcast_to(np.asarray(zero, dtype=float), x.shape)
    out = np.where(x >= pts[0][0], pts[0][1], np.nan)
    for (xa, ya), (xb, yb) in zip(pts[:-1], pts[1:]):
        span = np.where(xa - xb == 0, 1.0, xa - xb)
        seg = (x < xa) & (x >= xb)
        out = np.where(seg, yb + (ya - yb) * (x - xb) / span, out)
    last = pts[-1][0]
    span = np.where(last - z == 0, 1.0, last - z)
    ramp = np.clip(59.0 * (x - z) / span, 0.0, 59.0)
    out = np.where(x < last, ramp, out)
    return np.where(np.isnan(x), np.nan, out)


def grade(param, x, kind, do_sat_mgl=None):
    """Return (tier, score) arrays for readings x. tier is 1 to 4 (nan where there is no reading);
    score is a 0 to 100 summary that equals 100 / 80 / 60 exactly on the limits of tier 1 / 2 / 3."""
    sp = spec(param, kind)
    x = np.asarray(x, dtype=float)
    if sp is None:
        return np.full(x.shape, np.nan), np.full(x.shape, np.nan)
    tiers = sorted(sp["tiers"])
    tier = np.full(x.shape, 4.0)
    shape = sp["shape"]
    if shape in ("min", "min_sat"):
        lim = _tier_limits(sp, do_sat_mgl)
        for t in sorted(tiers, reverse=True):
            tier = np.where(x >= lim[t], t, tier)
        pts = [(lim[t], SCORE_AT[t]) for t in tiers]
        zero = (sp["zero"] if shape == "min" else sp["zero_ratio"] * lim[max(tiers)])
        score = _pl(x, pts, zero)
    elif shape == "max":
        for t in sorted(tiers, reverse=True):
            tier = np.where(x <= sp["tiers"][t]["limit"], t, tier)
        score = _pl(-x, [(-sp["tiers"][t]["limit"], SCORE_AT[t]) for t in tiers], -sp["zero"])
    else:   # range
        for t in sorted(tiers, reverse=True):
            d = sp["tiers"][t]
            tier = np.where((x >= d["lo"]) & (x <= d["hi"]), t, tier)
        last = max(tiers)
        lo_score = _pl(x, [(sp["tiers"][t]["lo"], SCORE_AT[t]) for t in tiers], sp["tiers"][last]["lo"] - sp["zero_delta"])
        hi_score = _pl(-x, [(-sp["tiers"][t]["hi"], SCORE_AT[t]) for t in tiers], -(sp["tiers"][last]["hi"] + sp["zero_delta"]))
        score = np.fmin(lo_score, hi_score)
    tier = np.where(np.isnan(x), np.nan, tier)
    return tier, score


def rule_text(param, kind, tier):
    # "at least 6 mg/L" style sentence for one tier
    sp = spec(param, kind)
    if sp is None or tier not in sp["tiers"]:
        return ""
    d, u = sp["tiers"][tier], sp["unit"]
    if sp["shape"] == "min":
        return f"at least {d['limit']:g} {u}"
    if sp["shape"] == "min_sat":
        return f"at least {d['mgl']:g} {u} or {d['sat']:g}% saturation, whichever is higher"
    if sp["shape"] == "max":
        return f"at most {d['limit']:g} {u}"
    return f"between {d['lo']:g} and {d['hi']:g}"


def table_rows(kind):
    # rows for the "standards used" table in the report and the panel
    rows = []
    for p in graded(kind):
        sp = spec(p, kind)
        for t in sorted(sp["tiers"]):
            d = sp["tiers"][t]
            rows.append({"param": p, "label": sp["label"], "tier": t, "colour": NAMES[t], "rule": rule_text(p, kind, t),
                         "std": d["std"], "use": d["use"], "verify": bool(d["verify"])})
        rows.append({"param": p, "label": sp["label"], "tier": 4, "colour": NAMES[4], "rule": "outside all the limits above",
                     "std": "", "use": "", "verify": False})
    for p in NOT_GRADED[group(kind)]:
        rows.append({"param": p, "label": LABEL[p], "tier": 0, "colour": "Not graded", "rule": NOT_GRADED_WHY[p], "std": "", "use": "", "verify": False})
    return rows


def tier_phrase(param, kind, tier):
    # one line: "Yellow: meets CPCB Class B (at least 5 mg/L)"
    if tier is None or np.isnan(tier):
        return "no reading"
    t = int(tier)
    sp = spec(param, kind)
    if sp is None:
        return "not graded"
    if t == 4:
        return "Red: outside every limit listed"
    return f"{NAMES[t]}: meets {sp['tiers'][t]['std']} ({rule_text(param, kind, t)})"


def next_better(param, kind, tier):
    # what it takes to move up one colour (used in advice)
    sp = spec(param, kind)
    if sp is None or tier is None or np.isnan(tier) or int(tier) <= 1:
        return ""
    t = int(tier)
    better = max(k for k in sp["tiers"] if k < t) if t > max(sp["tiers"]) or any(k < t for k in sp["tiers"]) else None
    if better is None:
        return ""
    return f"For {NAMES[better]}: {sp['label']} {rule_text(param, kind, better)} ({sp['tiers'][better]['std']})"


def tier_from_score(score):
    s = np.asarray(score, dtype=float)
    t = np.where(s >= 99.999, 1.0, np.where(s >= 80, 2.0, np.where(s >= 60, 3.0, 4.0)))
    return np.where(np.isnan(s), np.nan, t)
