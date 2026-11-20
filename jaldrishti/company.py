"""Everything about one company: its saved limits and policies, how the readings compare with them,
and what its policy sentences ask for."""
import json
import os
import re
from pathlib import Path

import numpy as np
import pandas as pd

from . import insights as I

TZ = "Asia/Kolkata"
PARAMS = ["ph", "turbidity", "tds", "do", "temperature"]
LABEL = {"ph": "pH", "turbidity": "Turbidity", "tds": "TDS", "do": "Dissolved oxygen", "temperature": "Temperature"}
UNIT = {"ph": "", "turbidity": "NTU", "tds": "mg/L", "do": "mg/L", "temperature": "°C"}
DEC = {"ph": 2, "turbidity": 1, "tds": 0, "do": 2, "temperature": 1}
BASIS_NAME = {"reading": "each reading", "mean_1h": "1 h average", "mean_24h": "24 h average"}

LO_KEYS = ["lo", "min", "minimum", "lower", "low", "min_value", "lower_limit", "from"]
HI_KEYS = ["hi", "max", "maximum", "upper", "high", "max_value", "upper_limit", "to"]
BASIS_KEYS = ["basis", "compare", "compared", "compare_as", "compared_as", "averaging", "average", "mode"]
REF_KEYS = ["ref", "reference", "policy_ref", "policy_reference", "policy", "source", "clause"]
NAME_KEYS = ["name", "company", "company_name", "org", "organisation", "organization", "firm", "profile", "profile_name"]
POLICY_KEYS = ["policies", "policy_measures", "measures", "requirements", "obligations", "commitments", "conditions",
               "other_policies", "policy_notes", "notes", "rules", "other"]


# ------------------------------------------------------------------ reading the saved profile

def alias_param(key):
    k = re.sub(r"[^a-z0-9]", "", str(key).lower())
    if k in ("ph", "phvalue") or (k.startswith("ph") and "phos" not in k and len(k) <= 8):
        return "ph"
    if "turb" in k or k == "ntu":
        return "turbidity"
    if "tds" in k or "dissolvedsolid" in k:
        return "tds"
    if "dissolvedoxygen" in k or k in ("do", "domgl", "dissolvedo2"):
        return "do"
    if k.startswith("temp"):
        return "temperature"
    return None


def num(v):
    if v is None or isinstance(v, bool):
        return None
    try:
        x = float(str(v).replace(",", "").strip())
    except ValueError:
        return None
    return None if np.isnan(x) else x


def first(d, keys):
    low = {str(k).lower(): v for k, v in d.items()}
    for k in keys:
        if k in low and low[k] not in (None, ""):
            return low[k]
    return None


def norm_basis(v):
    t = str(v or "").lower()
    if "24" in t:
        return "mean_24h"
    if "1 h" in t or "1h" in t or "hour" in t or "mean_1h" in t or "1_h" in t:
        return "mean_1h"
    return "reading"


def looks_like_profile(d):
    if not isinstance(d, dict):
        return False
    if isinstance(d.get("limits"), (dict, list)):
        return True
    return any(alias_param(k) for k in d.keys())


def find_profiles(raw):
    out = []
    if isinstance(raw, list):
        for i, item in enumerate(raw):
            if looks_like_profile(item):
                out.append((str(first(item, NAME_KEYS) or f"Profile {i + 1}"), item))
    elif isinstance(raw, dict):
        if looks_like_profile(raw):
            out.append((str(first(raw, NAME_KEYS) or "Profile"), raw))
        else:
            for k, v in raw.items():
                if isinstance(v, dict) and looks_like_profile(v):
                    out.append((str(first(v, NAME_KEYS) or k), v))
                elif isinstance(v, (dict, list)) and k not in ("meta", "version"):
                    out.extend(find_profiles(v))
    return out


def normalise_profile(name, prof):
    limits, warns = {}, []
    box = prof.get("limits", prof)
    items = []
    if isinstance(box, dict):
        items = list(box.items())
    elif isinstance(box, list):
        for it in box:
            if isinstance(it, dict):
                items.append((first(it, ["parameter", "param", "name", "key"]), it))
    for key, v in items:
        p = alias_param(key)
        if p is None:
            continue
        if isinstance(v, (list, tuple)) and len(v) == 2:
            lo, hi, basis, ref = num(v[0]), num(v[1]), "reading", ""
        elif isinstance(v, dict):
            lo, hi = num(first(v, LO_KEYS)), num(first(v, HI_KEYS))
            basis, ref = norm_basis(first(v, BASIS_KEYS)), str(first(v, REF_KEYS) or "").strip()
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
        v = first(prof, [k])
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


def data_dir():
    try:
        from . import config
        return Path(config.DATA_DIR)
    except Exception:
        return Path(os.getenv("JALDRISHTI_DATA_DIR", "data"))


def load_profiles(path=None):
    path = Path(path) if path else data_dir() / "compliance_profiles.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [], "no saved company profile found"
    except Exception as e:
        return [], f"the saved profile file could not be read ({e})"
    profs = [normalise_profile(n, p) for n, p in find_profiles(raw)]
    profs = [p for p in profs if p["limits"] or p["policies"]]
    return profs, ("" if profs else "the saved file has no limits that could be read")


def pick_profile(profiles, org, strict=True):
    # strict: only a profile that carries this account's company name, never somebody else's
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


def local_path():
    return data_dir() / "firm_report_settings.json"


def load_local(email):
    try:
        return json.loads(local_path().read_text(encoding="utf-8")).get(email, {})
    except Exception:
        return {}


def save_local(email, d):
    p = local_path()
    try:
        allv = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        allv = {}
    allv[email] = d
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(allv, indent=2), encoding="utf-8")


def profile_from_local(email, org):
    d = load_local(email)
    if not d:
        return None
    lim = {}
    for p, v in (d.get("limits") or {}).items():
        if p in PARAMS and (v.get("lo") is not None or v.get("hi") is not None):
            lim[p] = {"lo": v.get("lo"), "hi": v.get("hi"), "basis": v.get("basis", "reading"), "ref": v.get("ref", "")}
    pol = [x for x in (d.get("policies") or []) if x]
    return {"name": org or "Your company", "limits": lim, "policies": pol, "warnings": []} if (lim or pol) else None


# ------------------------------------------------------------------ readings

def native_series(df, p):
    if p not in df.columns:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([], tz="UTC"))
    s = I._usable(df, p)
    s.index = pd.DatetimeIndex(pd.to_datetime(df["timestamp"], utc=True))
    s = s[~s.index.isna()].sort_index()
    return s[~s.index.duplicated(keep="last")]


def cadence_minutes(df):
    if len(df) < 3:
        return 5
    d = pd.to_datetime(df["timestamp"], utc=True).sort_values().diff().dropna().dt.total_seconds() / 60
    d = d[d > 0]
    return int(min(60, max(1, round(d.median())))) if len(d) else 5


def compared(s, basis, cad):
    if basis == "mean_1h":
        n = max(1, int(round(60 / cad)))
        return s.rolling("1h", min_periods=max(1, int(0.5 * n))).mean()
    if basis == "mean_24h":
        n = max(1, int(round(1440 / cad)))
        return s.rolling("24h", min_periods=max(1, int(0.5 * n))).mean()
    return s


def runs_of(mask, cad):
    # consecutive true readings; a gap longer than 2.5 readings ends a run
    t = mask.index[mask.values]
    if len(t) == 0:
        return []
    gap = pd.Timedelta(minutes=2.5 * cad)
    out, a, prev = [], t[0], t[0]
    n = 1
    for x in t[1:]:
        if x - prev > gap:
            out.append((a, prev, n))
            a, n = x, 0
        n += 1
        prev = x
    out.append((a, prev, n))
    return [{"start": a, "end": b, "n": n, "hours": (b - a).total_seconds() / 3600 + cad / 60} for a, b, n in out]


def evaluate_limit(df, p, lim, start, end, cad, near=0.1):
    s = native_series(df, p)
    c = compared(s, lim["basis"], cad)
    inwin = c[(c.index >= start) & (c.index <= end)].dropna()
    res = {"param": p, "lim": lim, "n": int(len(inwin)), "n_out": 0, "pct_out": 0.0, "runs": [], "longest_h": 0.0,
           "worst": None, "last": None, "last_state": "nodata", "out_mask": None}
    if len(inwin) == 0:
        return res
    lo, hi = lim["lo"], lim["hi"]
    below = inwin < lo if lo is not None else pd.Series(False, index=inwin.index)
    above = inwin > hi if hi is not None else pd.Series(False, index=inwin.index)
    out = below | above
    res.update(n_out=int(out.sum()), pct_out=float(out.mean() * 100), out_mask=out, below=below, above=above)
    res["runs"] = runs_of(out, cad)
    for r in res["runs"]:
        seg = inwin[(inwin.index >= r["start"]) & (inwin.index <= r["end"])]
        side = "above" if above[seg.index].any() else "below"
        r["side"] = side
        r["extreme"] = float(seg.max() if side == "above" else seg.min())
    res["longest_h"] = max([r["hours"] for r in res["runs"]], default=0.0)
    if out.any():
        worst_t = (inwin - (hi if hi is not None else lo)).where(above).idxmax() if above.any() else (lo - inwin).where(below).idxmax()
        res["worst"] = (worst_t, float(inwin[worst_t]))
    res["last"] = (inwin.index[-1], float(inwin.iloc[-1]))
    span0 = abs(hi - lo) if (lo is not None and hi is not None) else max(abs(hi if hi is not None else lo), 1e-9)
    marg = near * span0
    nearm = ~out & (((inwin > hi - marg) if hi is not None else False) | ((inwin < lo + marg) if lo is not None else False))
    res["near_pct"] = float(nearm.mean() * 100)
    v = float(inwin.iloc[-1])
    if (lo is not None and v < lo) or (hi is not None and v > hi):
        res["last_state"] = "outside"
    else:
        span = abs(hi - lo) if (lo is not None and hi is not None) else max(abs(hi if hi is not None else lo), 1e-9)
        m = near * span if (lo is not None and hi is not None) else near * span
        close = (hi is not None and v > hi - m) or (lo is not None and v < lo + m)
        res["last_state"] = "close" if close else "within"
    # hours in which the limit was crossed (for time-of-day and co-movement checks)
    res["out_hours"] = out.groupby(out.index.floor("1h")).any()
    return res


# ------------------------------------------------------------------ policy sentences

UNMEASURED = {
    "bod": ("BOD", "dissolved oxygen dips and unusual-change flags"),
    "cod": ("COD", "unusual-change flags and dissolved oxygen"),
    "tss": ("suspended solids", "turbidity"),
    "suspended": ("suspended solids", "turbidity"),
    "oil": ("oil and grease", "nothing measured by the buoy"),
    "grease": ("oil and grease", "nothing measured by the buoy"),
    "ammonia": ("ammonia", "pH and dissolved oxygen (weak)"),
    "nitrate": ("nitrate", "nothing measured by the buoy"),
    "nitrogen": ("nitrogen", "nothing measured by the buoy"),
    "phosph": ("phosphate", "nothing measured by the buoy"),
    "coliform": ("coliform", "nothing measured by the buoy"),
    "e. coli": ("E. coli", "nothing measured by the buoy"),
    "ecoli": ("E. coli", "nothing measured by the buoy"),
    "chromium": ("chromium", "nothing measured by the buoy"),
    "lead": ("lead", "nothing measured by the buoy"),
    "mercury": ("mercury", "nothing measured by the buoy"),
    "cadmium": ("cadmium", "nothing measured by the buoy"),
    "zinc": ("zinc", "nothing measured by the buoy"),
    "copper": ("copper", "nothing measured by the buoy"),
    "metal": ("heavy metals", "nothing measured by the buoy"),
    "chloride": ("chloride", "TDS"),
    "sulphate": ("sulphate", "TDS"),
    "sulfate": ("sulphate", "TDS"),
    "fluoride": ("fluoride", "nothing measured by the buoy"),
    "colour": ("colour", "turbidity (weak)"),
    "color": ("colour", "turbidity (weak)"),
    "sulphide": ("sulphide", "nothing measured by the buoy"),
    "phenol": ("phenols", "nothing measured by the buoy"),
    "cyanide": ("cyanide", "nothing measured by the buoy"),
}
PARAM_WORDS = {
    "ph": [r"\bph\b"], "do": [r"dissolved oxygen", r"\bdo\b"], "turbidity": [r"turbid", r"\bntu\b"],
    "tds": [r"\btds\b", r"dissolved solids"], "temperature": [r"temperature", r"\btemp\b", r"thermal"],
}
NUM = r"(-?\d+(?:\.\d+)?)"


def policy_param(text):
    t = text.lower()
    for p, pats in PARAM_WORDS.items():
        if any(re.search(x, t) for x in pats):
            return p
    return None


def policy_numbers(text):
    # returns (lo, hi) found in a sentence such as "pH must stay between 6.5 and 8.5" or "TDS not to exceed 2100 mg/L"
    t = text.lower().replace("≤", " max ").replace("≥", " min ").replace("–", "-")
    m = re.search(r"between\s+" + NUM + r"\s*(?:and|to|-)\s*" + NUM, t) or re.search(NUM + r"\s*(?:to|-)\s*" + NUM + r"(?!\s*(?:h|hr|hrs|hours?|days?|min|mins|minutes?)\b)", t)
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        return min(a, b), max(a, b)
    m = re.search(r"not\s+(?:to\s+|go\s+|fall\s+|drop\s+|be\s+)*(?:below|under|less than|lower than)\s*(?:of\s*)?" + NUM, t)
    if m:
        return float(m.group(1)), None
    m = re.search(r"not\s+(?:to\s+|go\s+|rise\s+|be\s+)*(?:exceed|above|over|more than|greater than|higher than)\s*(?:of\s*)?" + NUM, t)
    if m:
        return None, float(m.group(1))
    m = re.search(r"(?:at least|minimum|min|more than|greater than|above|over)\s*(?:of\s*)?" + NUM, t)
    if m:
        return float(m.group(1)), None
    m = re.search(r"(?:at most|maximum|max|upto|up to|below|under|less than|limit of|exceeds?)\s*(?:of\s*)?" + NUM, t)
    if m:
        return None, float(m.group(1))
    return None, None


def within_hours(text):
    t = text.lower()
    m = re.search(r"within\s+(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|days?|minutes?|mins?)\b", t)
    if not m:
        return None
    v, u = float(m.group(1)), m.group(2)
    return v * 24 if u.startswith("day") else (v / 60 if u.startswith("min") else v)


def parse_policy(text):
    t = text.lower()
    p = policy_param(text)
    lo, hi = policy_numbers(text)
    unmeasured = [UNMEASURED[k] for k in UNMEASURED if k in t]
    kind = "other"
    if p and (lo is not None or hi is not None):
        kind = "numeric_limit"
    elif unmeasured:
        kind = "unmeasured"
    elif re.search(r"\b(report|notify|inform|intimate|submit|disclose|alert)\b", t):
        kind = "reporting"
    elif re.search(r"\b(sampl|record|log|calibrat|maintain|audit|inspect|monitor|test|analy[sz]e|lab)\w*", t):
        kind = "monitoring"
    elif re.search(r"\b(etp|stp|cetp|zld|treat|aerat|recycl|reuse|neutrali[sz]|discharge|effluent|consent)\w*", t):
        kind = "treatment"
    return {"text": text, "kind": kind, "param": p, "lo": lo, "hi": hi, "unmeasured": unmeasured,
            "within_h": within_hours(text), "reports": bool(re.search(r"\b(report|notify|inform|intimate)\b", t))}


INDUSTRY = [
    (("textile", "dye", "dyeing", "denim", "garment", "fabric", "yarn", "processing house"), "textile or dyeing unit",
     "Salt-heavy dye baths and soda or acid washes mostly show up as TDS and pH swings; colour and COD are not measured by the buoy.", ["tds", "ph"]),
    (("pharma", "api ", "chemical", "specialty", "agro", "pesticide", "bulk drug"), "chemical or pharma unit",
     "Batch cleaning and solvent or acid-base steps usually show up as pH steps and TDS jumps; organic load needs a lab COD.", ["ph", "tds"]),
    (("food", "dairy", "sugar", "distiller", "brewer", "bever", "edible", "oil mill", "slaughter", "meat", "fish process", "seafood"), "food or beverage unit",
     "High organic load (BOD) uses up oxygen: look for dissolved oxygen dips and pH drops after washing and fermentation cycles.", ["do", "ph"]),
    (("tannery", "leather"), "tannery",
     "Salt-heavy streams (soaking, pickling) raise TDS and low pH comes from pickling and chrome tanning; chromium and sulphide need a lab test.", ["tds", "ph"]),
    (("paper", "pulp", "board mill"), "paper or pulp mill",
     "Fibre and fines carry-over shows up as turbidity, and black liquor or starch adds organic load that lowers dissolved oxygen.", ["turbidity", "do"]),
    (("steel", "metal", "foundry", "forging", "plating", "galvan", "casting", "wire"), "metal-working unit",
     "Pickling acids and plating baths show up as low pH, and scale and sludge as turbidity; metals need a lab test.", ["ph", "turbidity"]),
    (("power", "thermal", "boiler", "cooling"), "power or cooling-water user",
     "Cooling-tower blowdown raises TDS and hot discharge raises temperature and lowers oxygen solubility.", ["tds", "temperature"]),
    (("aquaculture", "shrimp", "prawn", "fish farm", "hatchery"), "aquaculture farm",
     "Feed and waste load drive oxygen dips at night and pH swings with algae; ammonia needs a lab or test kit.", ["do", "ph"]),
    (("mining", "quarry", "cement", "stone", "sand", "crusher", "dredg", "port", "jetty", "construction", "infrastructure"), "mining, construction or port activity",
     "Soil, dust and dredged material show up as turbidity, often after rain or heavy work.", ["turbidity"]),
    (("hospital", "hotel", "resort", "apartment", "township", "stp", "sewage", "municipal"), "sewage-producing facility",
     "Untreated or partly treated sewage lowers dissolved oxygen and can change pH; coliform and BOD need a lab test.", ["do", "ph"]),
]


def industry_hint(org, policies):
    t = (" " + (org or "") + " " + " ".join(policies or []) + " ").lower()
    for words, name, text, focus in INDUSTRY:
        if any(w in t for w in words):
            return {"name": name, "text": text, "focus": focus}
    return None
