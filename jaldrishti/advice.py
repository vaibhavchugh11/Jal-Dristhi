"""Findings and next steps written for one company: its own limits, its own policy sentences, this water body's
colours (CPCB / BIS), the trained models and the time pattern of what actually happened."""
import numpy as np
import pandas as pd

from . import company as C
from . import standards as std

TZ = C.TZ
MIN_SCALE = {"ph": 0.05, "turbidity": 0.5, "tds": 5.0, "do": 0.1, "temperature": 0.1}
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}

# what usually lies behind a reading on one side of the limit, and what a company can do about it.
# These are general engineering and water-management points, not conclusions from the sensors.
BANK = {
    ("ph", "above"): {
        "factors": ["alkaline wash, caustic or lime dosing, or soda ash use", "over-dosing in the neutralisation tank", "a pH probe that is drifting or dirty"],
        "steps": ["check the dosing pumps and the set-point of the neutralisation tank for the periods listed", "recalibrate the in-line pH probe with fresh buffers and keep the record",
                  "hold the discharge until pH is back in range (equalisation tank or batch release)", "take a grab sample during a high-pH period and read it on a calibrated bench meter"]},
    ("ph", "below"): {
        "factors": ["acid cleaning, pickling or acidic process steps reaching the drain", "an under-dosed or empty alkali tank", "a pH probe that is drifting or dirty"],
        "steps": ["check the alkali dosing and the level in the dosing tank", "see whether acid cleaning or tank draining happened at the times listed",
                  "recalibrate the pH probe and keep the record", "add or enlarge an equalisation tank so slugs of acid are blended before discharge"]},
    ("do", "below"): {
        "factors": ["high organic load (BOD or COD) using up the oxygen", "aerators or blowers off or under-performing", "warm water, which holds less oxygen",
                    "algae and bacteria breathing at night when there is no photosynthesis"],
        "steps": ["check the aerators, blowers and diffusers, and the dissolved oxygen in the aeration tank", "move or spread out high-load discharges so they do not coincide with the lowest-oxygen hours",
                  "send a sample for BOD and COD on a day when oxygen dipped", "look for sludge carry-over from the clarifier",
                  "consider re-aeration (cascade or diffused air) at the outfall"]},
    ("do", "above"): {
        "factors": ["algae making oxygen in sunlight (supersaturation)", "a sensor that needs recalibration"],
        "steps": ["compare with the time of day: afternoon highs point to algae", "check the sensor membrane and calibration"]},
    ("turbidity", "above"): {
        "factors": ["solids carried over from a settling tank or clarifier", "filter back-wash or desludging", "run-off or earthwork near the outfall", "dirt or growth on the sensor window"],
        "steps": ["check settling tanks and clarifiers and the sludge removal schedule", "move filter back-wash and desludging away from the periods listed or release them slowly",
                  "clean the sensor window and compare with a grab sample on a bench turbidity meter", "compare the dates with rainfall and, for a tidal site, with the tide table"]},
    ("tds", "above"): {
        "factors": ["salt-heavy streams such as demineralisation regeneration, RO reject, dye or process salt baths", "cooling-tower blow-down", "evaporation in a shallow or low-flow stretch"],
        "steps": ["list which streams carry the most salt and when they are released", "segregate and reduce high-TDS streams, or recover and reuse them (ZLD or evaporation where your consent needs it)",
                  "check the conductivity probe and its temperature compensation", "compare with a grab sample measured in the lab"]},
    ("tds", "below"): {
        "factors": ["dilution by rain or a cleaner inflow", "a conductivity probe that is drifting"], "steps": ["check the probe and its calibration"]},
    ("temperature", "above"): {
        "factors": ["hot effluent or cooling water", "sunlight on a shallow stretch"],
        "steps": ["check cooling towers and heat exchangers before the discharge", "see whether the high readings follow the process schedule or only the afternoon sun"]},
}
KEYWORDS = {
    "ph": ["acid", "alkal", "neutral", "caustic", "lime"],
    "do": ["aerat", "oxygen", "bod", "cod", "organic"],
    "turbidity": ["solid", "settl", "clarif", "filter", "sludge", "tss", "turbid"],
    "tds": ["salt", "brine", "zld", "reject", "blowdown", "blow-down", "conductiv", "chloride", "recycl", "reuse", "evapor"],
    "temperature": ["cooling", "thermal", "hot", "temperature"],
}
PROXY_PARAM = {"BOD": "do", "COD": "do", "suspended solids": "turbidity", "chloride": "tds", "sulphate": "tds", "colour": "turbidity", "ammonia": "do"}


def ist(ts):
    return pd.Timestamp(ts).tz_convert(TZ)


def when(ts):
    return ist(ts).strftime("%d %b %H:%M")


def lim_text(p, lim):
    u = C.UNIT[p]
    u = (" " + u) if u else ""
    parts = []
    if lim["lo"] is not None:
        parts.append(f"minimum {lim['lo']:g}{u}")
    if lim["hi"] is not None:
        parts.append(f"maximum {lim['hi']:g}{u}")
    return " and ".join(parts) + (f", compared as {C.BASIS_NAME[lim['basis']]}" if lim["basis"] != "reading" else "")


def fmt(p, v):
    return f"{v:.{C.DEC[p]}f}" + ((" " + C.UNIT[p]) if C.UNIT[p] else "")


# ------------------------------------------------------------------ patterns in the time of the exceedances

def tod_window(flag_hours):
    idx = (flag_hours[flag_hours].index + pd.Timedelta(minutes=30)).tz_convert(TZ)     # bin centre = the hour in IST
    n = len(idx)
    if n < 6:
        return None
    counts = np.bincount(idx.hour, minlength=24)
    best = max(range(24), key=lambda h: sum(counts[(h + k) % 24] for k in range(3)))
    share = sum(counts[(best + k) % 24] for k in range(3)) / n
    return (best, share) if share >= 0.5 else None


def weekend_share(flag_hours):
    idx = (flag_hours[flag_hours].index + pd.Timedelta(minutes=30)).tz_convert(TZ)
    return (float((idx.dayofweek >= 5).mean()), len(idx)) if len(idx) else (None, 0)


def trend_halves(flag_hours, start, end):
    n = int(flag_hours.sum())
    if n < 8 or (end - start) < pd.Timedelta(days=6):
        return None
    mid = start + (end - start) / 2
    a = int(flag_hours[flag_hours.index < mid].sum())
    b = n - a
    if a == 0 and b >= 8:
        return "later"
    if b == 0 and a >= 8:
        return "earlier"
    if a and b / a >= 2:
        return "later"
    if b and a / b >= 2:
        return "earlier"
    return None


def robust_z(h, p):
    x = h[p]
    prior = x.shift(1).rolling(168, min_periods=24)
    med = prior.median()
    mad = prior.apply(lambda w: np.nanmedian(np.abs(w - np.nanmedian(w))), raw=True) * 1.4826
    return (x - med) / mad.clip(lower=MIN_SCALE[p])


def co_movers(h, flag_hours, p):
    hrs = flag_hours[flag_hours].index
    out = []
    if len(hrs) < 4:
        return out
    for q in ("ph", "turbidity", "tds", "do", "temperature"):
        if q == p or q not in h:
            continue
        z = robust_z(h, q).reindex(hrs).dropna()
        if len(z) < 4:
            continue
        up, dn = float((z > 3).mean()), float((z < -3).mean())
        if max(up, dn) >= 0.4:
            out.append((q, "up" if up >= dn else "down", max(up, dn)))
    return sorted(out, key=lambda t: -t[2])


def deviation_overlap(runs, devs):
    if not runs or not devs:
        return 0
    n = 0
    for r in runs:
        a, b = r["start"], r["end"] + pd.Timedelta(hours=1)
        if any(d["start"] <= b and d["end"] + pd.Timedelta(hours=1) >= a for d in devs):
            n += 1
    return n


def matched_policies(profile, p):
    out = []
    for text in (profile or {}).get("policies", []):
        t = text.lower()
        if C.policy_param(text) == p or any(k in t for k in KEYWORDS[p]):
            out.append(text)
    return out


# ------------------------------------------------------------------ findings

def exceedance_finding(p, ev, ctx):
    lim, kind, h = ev["lim"], ctx["kind"], ctx["h"]
    sides = []
    if ev["below"].any():
        sides.append("below")
    if ev["above"].any():
        sides.append("above")
    side = "below" if (len(sides) == 1 and sides[0] == "below") else ("above" if len(sides) == 1 else
                                                                      ("below" if ev["below"].sum() >= ev["above"].sum() else "above"))
    pri = "high" if (ev["pct_out"] >= 5 or ev["longest_h"] >= 3 or ev["last_state"] == "outside") else "medium"
    wt, wv = ev["worst"] if ev["worst"] else (None, None)
    nruns = len(ev["runs"])
    see = (f"{C.LABEL[p]} was {side} your limit ({lim_text(p, lim)}) in {ev['pct_out']:.1f}% of readings, in {nruns} separate period(s). "
           f"The longest lasted {ev['longest_h']:.1f} h.")
    if wt is not None:
        see += f" The worst value was {fmt(p, wv)} on {when(wt)} IST."
    evidence, factors, steps = [], list(BANK.get((p, side), {}).get("factors", [])), list(BANK.get((p, side), {}).get("steps", []))
    fh = ev["out_hours"]
    tw = tod_window(fh)
    if tw:
        win = f"around {tw[0]:02d}:00 to {(tw[0] + 2) % 24:02d}:00 IST"
        evidence.append(f"{tw[1] * 100:.0f}% of the hours outside the limit fall {win}.")
        steps.insert(0, f"audit what runs {win} (batch releases, cleaning, shift changes, dosing)")
    wk, nwk = weekend_share(fh)
    if wk is not None and nwk >= 12:
        if wk >= 0.5:
            evidence.append(f"{wk * 100:.0f}% of the hours outside the limit are on a weekend (2 of 7 days would give 29%).")
        elif wk <= 0.07:
            evidence.append("Almost none fall on a Saturday or Sunday, which fits a weekday operation more than a natural cause (to be checked).")
    tr = trend_halves(fh, ctx["start"], ctx["end"])
    if tr == "later":
        evidence.append("It is happening more in the second half of the period than in the first: the problem is growing.")
        pri = "high"
    elif tr == "earlier":
        evidence.append("It happened mostly in the first half of the period and less since, so something may already have been fixed.")
    cm = co_movers(h, fh, p)
    for q, d, share in cm[:3]:
        evidence.append(f"{share * 100:.0f}% of those hours also had {C.LABEL[q]} unusually {'high' if d == 'up' else 'low'} (more than 3 robust standard deviations from the past week).")
    if cm and cm[0][0] in ("turbidity", "tds") and cm[0][1] == "up" and p in ("turbidity", "tds"):
        factors.insert(0, "turbidity and TDS rising together is consistent with something entering the water (discharge or run-off) rather than a lone sensor fault")
    if p == "ph" and side == "above" and any(q == "do" and d == "up" for q, d, _ in cm):
        factors.insert(0, "pH and dissolved oxygen rising together in the afternoon is also what algae do in sunlight, so a natural cause is possible")
    if p in ("do",) and side == "below" and tw and 0 <= tw[0] <= 6:
        factors.insert(0, "lowest oxygen in the early hours is typical when algae and bacteria use oxygen overnight")
    if kind in ("brackish", "seawater") and p in ("tds", "turbidity"):
        factors.insert(0, "in a tidal creek the tide mixes and stirs the water on its own schedule, so compare the times with the tide table first")
    n_ov = deviation_overlap(ev["runs"], ctx.get("deviations", []))
    if n_ov:
        evidence.append(f"{n_ov} of {nruns} periods coincided with a stretch where the water moved away from this site's usual daily pattern (SINDy, experimental).")
    fr = ctx.get("frame")
    if fr is not None and len(fh):
        hh = fr.reindex(fh[fh].index)["worst_tier"].dropna()
        if len(hh):
            bad = float((hh >= 3).mean())
            if bad >= 0.05:
                evidence.append(f"In those hours the Water Health Index colour was Orange or Red {bad * 100:.0f}% of the time.")
            else:
                evidence.append("In those hours the Water Health Index colour stayed Green or Yellow, so your own limit is stricter than the CPCB and BIS class limits for this parameter.")
    ind = ctx.get("industry")
    if ind and p in ind["focus"]:
        factors.insert(0, f"for a {ind['name']}: {ind['text']}")
    steps.append("write down the cause and the fix for each period in your log; your regulator may ask for it")
    runs = sorted(ev["runs"], key=lambda r: -r["hours"])[:3]
    if runs:
        evidence.append("Longest periods: " + "; ".join(f"{when(r['start'])} to {when(r['end'])} IST ({r['hours']:.1f} h, {'peak' if r['side'] == 'above' else 'low'} {fmt(p, r['extreme'])})" for r in runs) + ".")
    return {"id": f"limit_{p}", "priority": pri, "title": f"{C.LABEL[p]} outside your limit in {ev['pct_out']:.1f}% of readings",
            "see": see, "evidence": evidence, "factors": factors, "steps": steps,
            "policy": matched_policies(ctx["profile"], p), "magnitude": ev["pct_out"] + ev["longest_h"]}


def near_limit_finding(p, ev, ctx):
    return {"id": f"near_{p}", "priority": "low", "title": f"{C.LABEL[p]} runs close to your limit",
            "see": f"{C.LABEL[p]} stayed inside your limit ({lim_text(p, ev['lim'])}) but within 10% of it for {ev['near_pct']:.0f}% of readings.",
            "evidence": [], "factors": ["a small change in the process or the weather would push it over"],
            "steps": ["set an internal alert a little before the limit so there is time to act", "look at what the best days did differently and write it into the routine"],
            "policy": matched_policies(ctx["profile"], p), "magnitude": ev["near_pct"] / 10}


def forecast_findings(ctx):
    out = []
    m = ctx.get("models") or {}
    d = m.get("do", {})
    kind, prof = ctx["kind"], ctx["profile"]
    if d.get("status") == "ready":
        lim = (prof or {}).get("limits", {}).get("do")
        lo_lim = lim["lo"] if lim and lim.get("lo") is not None else None
        h = ctx["h"]
        sat = float(h.loc[d["as_of"], "do_sat_mgl"]) if d["as_of"] in h.index else None
        t_pred, _ = std.grade("do", [d["pred_mgl"]], kind, [sat] if sat else None)
        t_low, _ = std.grade("do", [d["lo_mgl"]], kind, [sat] if sat else None)
        nb = std.next_better("do", kind, t_pred[0])
        method = f"Method: {d['used'].replace('_', ' ')}" + (" (trained model, beat the simple baselines on this site's own later data)" if d["adopted_model"] else " (simple baseline; the trained models did not clearly beat it on this site)")
        if lo_lim is not None and d["lo_mgl"] < lo_lim:
            whole = d["hi_mgl"] < lo_lim
            out.append({"id": "fc_do", "priority": "high" if whole else "medium",
                        "title": f"Dissolved oxygen is forecast to {'fall below' if whole else 'come close to or below'} your minimum of {lo_lim:g} mg/L",
                        "see": f"As of {when(d['as_of'])} IST oxygen is {d['now_mgl']:.1f} mg/L. In {d['horizon_h']} hours it is forecast at {d['pred_mgl']:.1f} mg/L (likely range {d['lo_mgl']:.1f} to {d['hi_mgl']:.1f}).",
                        "evidence": [method, "Forecast colour (CPCB): " + std.tier_phrase("do", kind, t_pred[0]) + (f". {nb}." if nb else ".")],
                        "factors": BANK[("do", "below")]["factors"][:3],
                        "steps": ["check aerators and blowers now, before the dip", "hold back or slow high-load discharges for the next few hours", "plan a grab sample at the expected low point"],
                        "policy": matched_policies(prof, "do"), "magnitude": 5})
        elif t_low[0] >= 3:
            out.append({"id": "fc_do", "priority": "medium", "title": "Dissolved oxygen may drop to the Orange or Red colour in the next hours",
                        "see": f"As of {when(d['as_of'])} IST oxygen is {d['now_mgl']:.1f} mg/L; forecast {d['pred_mgl']:.1f} mg/L in {d['horizon_h']} hours (range {d['lo_mgl']:.1f} to {d['hi_mgl']:.1f}).",
                        "evidence": [method, "Lower end of the range (CPCB): " + std.tier_phrase("do", kind, t_low[0])],
                        "factors": BANK[("do", "below")]["factors"][:3], "steps": BANK[("do", "below")]["steps"][:3],
                        "policy": matched_policies(prof, "do"), "magnitude": 3})
    t = m.get("turb", {})
    if t.get("status") == "ready" and t.get("elevated"):
        out.append({"id": "fc_turb", "priority": "medium", "title": "Early warning: a turbidity rise is likely in the next 6 hours",
                    "see": f"As of {when(t['as_of'])} IST the warning level is ELEVATED" + (" and turbidity is already above its usual level." if t.get("already_high") else "."),
                    "evidence": [f"On this site's later test data, about {t['test_precision'] * 100:.0f} in 100 alerts were followed by a rise within {t['horizon_h']} hours and about {t['test_recall'] * 100:.0f} in 100 rises were warned about.",
                                 "Method: " + t["used"].replace("_", " ") + (" (trained model)" if t["adopted_model"] else " (simple rule)")],
                    "factors": BANK[("turbidity", "above")]["factors"][:3],
                    "steps": ["inspect settling tanks and clarifiers now", "postpone filter back-wash and desludging if you can", "keep the sensor window clean so the next reading can be trusted"],
                    "policy": matched_policies(prof, "turbidity"), "magnitude": 3})
    return out


def whi_finding(ctx):
    w = ctx.get("whi")
    if not w or w.get("status") != "ready":
        return []
    kind = ctx["kind"]
    bad = w["worst_share"][3] + w["worst_share"][4]
    if not (bad >= 0.2 or w["worst_share"][4] >= 0.05):
        return []
    top = max(w["weakest_share"], key=w["weakest_share"].get) if w["weakest_share"] else None
    ps = w["param_share"].get(top, {}) if top else {}
    tier_typ = 3 if ps.get(3, 0) >= ps.get(4, 0) else 4
    nb = std.next_better(top, kind, tier_typ) if top else ""
    steps = list(BANK.get((top, "below" if top == "do" else "above"), {}).get("steps", []))[:3] if top else []
    return [{"id": "whi", "priority": "high" if w["worst_share"][4] >= 0.1 else "medium",
             "title": f"A parameter was Orange or Red in {bad * 100:.0f}% of hours" + (f", mostly {C.LABEL[top]}" if top else ""),
             "see": f"The Water Health Index averaged {w['mean']:.0f} out of 100 ({w['band_mean']}; higher is better), lowest {w['lowest']:.0f}. Separately from that number, at least one sensor was Red in {w['worst_share'][4] * 100:.0f}% and Orange in {w['worst_share'][3] * 100:.0f}% of hours.",
             "evidence": ([f"{C.LABEL[top]} was the limiting parameter in {w['weakest_share'][top] * 100:.0f}% of the hours that were not Green."] if top else []) + ([nb + "."] if nb else []),
             "factors": [], "steps": steps, "policy": matched_policies(ctx["profile"], top) if top else [], "magnitude": bad * 10}]


def improvement_finding(ctx):
    w = ctx.get("whi")
    if not w or w.get("status") != "ready" or w["common_tier"] != 2:
        return []
    kind = ctx["kind"]
    rows = []
    for p in w["params"]:
        ps = w["param_share"][p]
        if ps.get(2, 0) >= 0.3:
            nb = std.next_better(p, kind, 2)
            if nb:
                rows.append(f"{C.LABEL[p]} was Yellow in {ps[2] * 100:.0f}% of hours. {nb}.")
    if not rows:
        return []
    return [{"id": "improve", "priority": "low", "title": "What it takes to bring the Yellow sensors up to Green",
             "see": f"Yellow was the most common colour ({w['worst_share'][2] * 100:.0f}% of hours).", "evidence": rows, "factors": [],
             "steps": ["decide which of these targets are realistic for your process and plan them into the next maintenance window"], "policy": [], "magnitude": 0.5}]


def trend_findings(ctx):
    from scipy.stats import kendalltau, theilslopes
    out = []
    hp, start, end = ctx["hp"], ctx["start"], ctx["end"]
    if (end - start) < pd.Timedelta(days=8):
        return out
    for p in ("ph", "turbidity", "tds", "do", "temperature"):
        if p not in hp:
            continue
        d = hp[p].resample("1D").mean().dropna()
        if len(d) < 7:
            continue
        x = np.arange(len(d), dtype=float)
        tau, pv = kendalltau(x, d.values)
        if not (pv < 0.01):
            continue
        slope = theilslopes(d.values, x)[0]
        total = slope * (len(d) - 1)
        scale = max(float(d.std()), 1e-9)
        if abs(total) < 1.0 * scale:
            continue
        lim = (ctx["profile"] or {}).get("limits", {}).get(p)
        eta = None
        if lim and slope != 0:
            cur = float(d.iloc[-3:].mean())
            if slope > 0 and lim.get("hi") is not None and cur < lim["hi"]:
                eta = (lim["hi"] - cur) / slope
            if slope < 0 and lim.get("lo") is not None and cur > lim["lo"]:
                eta = (cur - lim["lo"]) / -slope
        ev = [f"Daily averages moved by about {total:+.{C.DEC[p]}f} {C.UNIT[p]} over {len(d)} days (Kendall trend test, p < 0.01)."]
        pri = "low"
        if eta is not None and eta <= 30:
            ev.append(f"At this pace it would reach your limit in about {eta:.0f} days.")
            pri = "medium"
        out.append({"id": f"trend_{p}", "priority": pri,
                    "title": f"{C.LABEL[p]} is {'rising' if slope > 0 else 'falling'} steadily",
                    "see": f"{C.LABEL[p]} has a clear {'upward' if slope > 0 else 'downward'} drift across the period, not just day-to-day wobble.",
                    "evidence": ev, "factors": ["a gradual change in process load, raw materials or season", "sensor drift or fouling (check this first when only one sensor drifts)"],
                    "steps": ["compare with a reference meter or a lab sample to rule out sensor drift", "check calibration dates and clean the sensor"],
                    "policy": matched_policies(ctx["profile"], p), "magnitude": abs(total) / scale / 5})
    return out


def deviation_finding(ctx):
    devs = [d for d in ctx.get("deviations", []) if ctx["start"] <= d["start"] <= ctx["end"]]
    if not devs:
        return []
    name = {"do_sat": "dissolved oxygen", "ph": "pH", "logturb": "turbidity"}
    top = sorted(devs, key=lambda d: -d["max_z"])[:3]
    rows = [f"{name[d['state']]} stayed {d['direction']} its usual daily pattern for {d['hours']} h from {when(d['start'])} IST (about {d['max_z']:.0f} robust standard deviations)." for d in top]
    return [{"id": "sindy", "priority": "low", "title": f"{len(devs)} stretch(es) where the water moved away from this site's usual daily pattern",
             "see": "SINDy learned the daily cycle of this site. These are hours in which a value stayed well away from it for three hours or more.",
             "evidence": rows + ["This check is experimental. It has not been tested against known events."], "factors": ["a change in the process, the weather or the tide", "a sensor problem"],
             "steps": ["compare these times with your process and maintenance logs", "if they match a known event, note it; if not, take a grab sample the next time it happens"],
             "policy": [], "magnitude": len(devs) / 10}]


def quality_finding(ctx):
    q = ctx["quality"]
    bad = []
    if q["coverage"] < 0.9:
        bad.append(f"only {q['coverage'] * 100:.0f}% of the expected readings arrived")
    if q["longest_gap_h"] >= 6:
        bad.append(f"the longest gap was {q['longest_gap_h']:.0f} h")
    for p, n in q["flags"].items():
        if n:
            bad.append(f"{C.LABEL[p]} had {n} readings marked as faulty (stuck, missing or implausible)")
    if not bad:
        return []
    return [{"id": "quality", "priority": "medium" if (q["coverage"] < 0.7 or q["flags"]) else "low", "title": "Data gaps and sensor faults reduce what can be concluded",
             "see": "; ".join(bad) + ".", "evidence": [], "factors": ["power, connection or buoy problems", "fouled or failed sensors"],
             "steps": ["clean and inspect the sensors and the buoy", "check power and connection at the times of the gaps", "record each calibration with the date and the reference solution"],
             "policy": [], "magnitude": 1 - q["coverage"]}]


def make_findings(ctx):
    out = []
    for p, ev in ctx["limits_eval"].items():
        if ev["n"] == 0:
            continue
        if ev["n_out"] > 0:
            out.append(exceedance_finding(p, ev, ctx))
        elif ev.get("near_pct", 0) >= 10:
            out.append(near_limit_finding(p, ev, ctx))
    out += forecast_findings(ctx) + whi_finding(ctx) + trend_findings(ctx) + deviation_finding(ctx) + quality_finding(ctx) + improvement_finding(ctx)
    out.sort(key=lambda f: (PRIORITY_ORDER[f["priority"]], -f["magnitude"]))
    return out


# ------------------------------------------------------------------ the company's own policy sentences

def policy_rows(ctx):
    prof, rows = ctx["profile"], []
    if not prof:
        return rows
    h, start, end, cad = ctx["h"], ctx["start"], ctx["end"], ctx["cad"]
    for text in prof["policies"]:
        pp = C.parse_policy(text)
        status, shows, how, fill = "Needs records", "", "", "#f2f2f2"
        if pp["kind"] == "numeric_limit":
            lim = {"lo": pp["lo"], "hi": pp["hi"], "basis": "reading", "ref": ""}
            ev = C.evaluate_limit(ctx["df"], pp["param"], lim, start, end, cad)
            if ev["n"] == 0:
                status, shows, how, fill = "Not enough data", "No readings of this parameter in the period.", "Check that the sensor was sending data.", "#f2f2f2"
            elif ev["n_out"] == 0:
                v = native_series(ctx["df"], pp["param"])
                v = v[(v.index >= start) & (v.index <= end)]
                near = (f"closest to the maximum: {fmt(pp['param'], v.max())}" if lim["hi"] is not None else "") + (" and " if lim["hi"] is not None and lim["lo"] is not None else "") + (f"closest to the minimum: {fmt(pp['param'], v.min())}" if lim["lo"] is not None else "")
                status, shows, fill = "Meets", f"{C.LABEL[pp['param']]} stayed inside {lim_text(pp['param'], lim)} in all {ev['n']} readings ({near}).", "#d9f0df"
                how = "Keep the current controls and the calibration record. Add an internal alert slightly inside the limit."
            else:
                status, fill = "Does not meet", "#f9d6d6"
                shows = f"{C.LABEL[pp['param']]} was outside {lim_text(pp['param'], lim)} in {ev['pct_out']:.1f}% of readings ({len(ev['runs'])} period(s), longest {ev['longest_h']:.1f} h)."
                side = "above" if ev["above"].any() and ev["above"].sum() >= ev["below"].sum() else "below"
                how = "; ".join(BANK.get((pp["param"], side), {}).get("steps", [])[:3])
                if pp["reports"]:
                    first = sorted(ev["runs"], key=lambda r: r["start"])[:3]
                    how += (f". Your policy also asks for a report{' within %g h' % pp['within_h'] if pp['within_h'] else ''}: "
                            "check that one was made for each period (first: " + "; ".join(when(r["start"]) + " IST" for r in first) + ").")
        elif pp["kind"] == "unmeasured":
            names = ", ".join(sorted({a for a, _ in pp["unmeasured"]}))
            proxies = sorted({b for _, b in pp["unmeasured"] if "nothing" not in b})
            status, fill = "Cannot be checked by the buoy", "#e4e4e4"
            shows = f"{names} is not measured by the buoy." + (f" Related signal: {', '.join(proxies)}." if proxies else "")
            dates = []
            for a, _ in pp["unmeasured"]:
                q = PROXY_PARAM.get(a)
                if q and q in ctx["limits_eval"] and ctx["limits_eval"][q]["runs"]:
                    dates += [when(r["start"]) for r in sorted(ctx["limits_eval"][q]["runs"], key=lambda r: -r["hours"])[:3]]
            how = "Sample and test in an accredited laboratory on the schedule your policy or consent gives."
            if dates:
                how += " The buoy's related signal was outside your limit on: " + ", ".join(sorted(set(dates))) + " IST. Sampling on days like these is the most useful."
            if pp["reports"]:
                how += (f" Your policy also has a reporting duty{' within %g h' % pp['within_h'] if pp['within_h'] else ''}: "
                        "make sure the lab result goes to the authority in that time and keep the proof.")
        elif pp["kind"] == "reporting":
            related = [pp["param"]] if pp["param"] in ctx["limits_eval"] else list(ctx["limits_eval"])
            runs = [(p, r) for p in related for r in ctx["limits_eval"][p]["runs"]]
            window = f" within {pp['within_h']:g} h" if pp["within_h"] else ""
            if runs:
                first = sorted(runs, key=lambda t: t[1]["start"])[:4]
                status, fill = "Duty may have been triggered", "#fde5c8"
                shows = f"The buoy recorded {len(runs)} period(s) outside your limits that may need to be reported{window}. First: " + "; ".join(f"{C.LABEL[p]} at {when(r['start'])} IST" for p, r in first) + "."
                how = "Check your log for a report to the authority for each period, with the time of detection and the time of reporting. Set an alert to the person on duty when the Water Health Index turns Red or a limit is crossed."
            else:
                status, fill = "No trigger seen", "#d9f0df"
                shows = "No period outside your entered limits was seen in this period."
                how = "Keep the alert route ready and test it once a quarter."
        elif pp["kind"] == "monitoring":
            q = ctx["quality"]
            status, fill = ("Meets" if q["coverage"] >= 0.9 and not any(q["flags"].values()) else "Needs attention"), ("#d9f0df" if q["coverage"] >= 0.9 and not any(q["flags"].values()) else "#fde5c8")
            shows = f"The buoy sent {q['coverage'] * 100:.0f}% of the expected readings; longest gap {q['longest_gap_h']:.0f} h; faulty readings: " + (", ".join(f"{C.LABEL[p]} {n}" for p, n in q["flags"].items() if n) or "none") + "."
            how = "Keep a dated calibration and maintenance log with reference solutions, and attach it to the report you send."
        elif pp["kind"] == "treatment":
            status, fill = "Needs records", "#f2f2f2"
            bad = [p for p, ev in ctx["limits_eval"].items() if ev["n_out"]]
            shows = ("Readings outside your limits: " + ", ".join(C.LABEL[p] for p in bad) + ".") if bad else "No period outside your entered limits."
            how = "The buoy cannot see inside the plant. Use the periods in the findings to audit treatment logs (inlet and outlet readings, aeration hours, dosing, sludge removal)."
        else:
            shows, how = "No direct link to the five sensors.", "Keep the evidence your policy asks for on file."
        rows.append({"policy": text, "kind": pp["kind"], "status": status, "shows": shows, "how": how, "fill": fill})
    return rows


def native_series(df, p):
    return C.native_series(df, p)


def quality_summary(df, start, end, cad, flags_cols=True):
    ts = pd.to_datetime(df["timestamp"], utc=True)
    sub = df[(ts >= start) & (ts <= end)]
    q = {"rows": int(len(sub)), "coverage": 0.0, "longest_gap_h": 0.0, "flags": {}, "last": None}
    if len(sub) == 0:
        return q
    t = pd.DatetimeIndex(pd.to_datetime(sub["timestamp"], utc=True)).sort_values().unique()
    span_min = max((t[-1] - t[0]).total_seconds() / 60, cad)
    q["coverage"] = float(min(1.0, len(t) / (span_min / cad + 1)))
    if len(t) > 1:
        q["longest_gap_h"] = float((pd.Series(t).diff().max()).total_seconds() / 3600)
    for p in C.PARAMS:
        f = p + "_flag"
        q["flags"][p] = int((sub[f].astype(str) != "ok").sum()) if f in sub.columns else 0
    q["last"] = t[-1]
    return q
