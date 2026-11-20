"""Builds the company report as a list of blocks (title, tables, coloured cards, charts, findings).
report_out.py turns the blocks into a PDF, an HTML page and a ZIP of tables."""
import io
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from . import advice as A
from . import company as C
from . import insights as I
from . import insights_report as ir
from . import standards as std

TZ = C.TZ
LABEL = C.LABEL
PRI_FILL = {"high": "#d64545", "medium": "#f28c28", "low": "#6c8ebf"}
PRI_NAME = {"high": "High priority", "medium": "Medium priority", "low": "Low priority"}


@dataclass
class Report:
    doc: list
    summary: dict
    csvs: dict = field(default_factory=dict)
    title: str = ""
    base: str = "JalDrishti_report"
    findings: list = field(default_factory=list)
    policies: list = field(default_factory=list)
    limits_eval: dict = field(default_factory=dict)


# ------------------------------------------------------------------ periods (India time)

def period_bounds(kind, now=None, rng=None):
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    loc = now.tz_convert(TZ)
    if kind == "today":
        s = loc.normalize()
        return s.tz_convert("UTC"), now, f"Today, {loc.strftime('%d %b %Y')}"
    if kind == "month":
        s = loc.normalize().replace(day=1)
        return s.tz_convert("UTC"), now, f"{loc.strftime('%B %Y')} (month to date)"
    if kind == "year":
        s = loc.normalize().replace(month=1, day=1)
        return s.tz_convert("UTC"), now, f"{loc.year} (year to date)"
    if kind == "custom":
        a, b = rng
        if a is None or b is None:
            raise ValueError("Pick a start and an end date.")
        if a > b:
            raise ValueError("The start date is after the end date.")
        s = pd.Timestamp(a).tz_localize(TZ)
        e = (pd.Timestamp(b).tz_localize(TZ) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))
        return s.tz_convert("UTC"), min(e.tz_convert("UTC"), now), f"{s.strftime('%d %b %Y')} to {pd.Timestamp(b).strftime('%d %b %Y')}"
    raise ValueError("unknown period")


def loc(ts, fmt="%d %b %Y %H:%M"):
    return pd.Timestamp(ts).tz_convert(TZ).strftime(fmt) + " IST"


# ------------------------------------------------------------------ small helpers

def _png(fig):
    import matplotlib.pyplot as plt
    b = io.BytesIO()
    fig.savefig(b, format="png", dpi=130)
    plt.close(fig)
    return b.getvalue()


def _mpl():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    return plt


def fmt(p, v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "-"
    return f"{v:.{C.DEC[p]}f}"


def pct(x):
    return f"{x * 100:.0f}%"


def chip(label, value, tier, sub=""):
    fill = std.COLOURS.get(tier, std.GREY) if tier else std.GREY
    fg = std.TEXT_ON.get(tier, "#222222") if tier else "#222222"
    return {"label": label, "value": value, "sub": sub, "fill": fill, "fg": fg}


# ------------------------------------------------------------------ statistics

def param_stats(df, p, start, end, cad):
    s = C.native_series(df, p)
    w = s[(s.index >= start) & (s.index <= end)]
    allr = pd.to_datetime(df["timestamp"], utc=True)
    allr = allr[(allr >= start) & (allr <= end)]
    row = {"param": p, "count": int(w.notna().sum())}
    if len(allr):
        span = max((allr.max() - allr.min()).total_seconds() / 60, cad)
        expected = span / cad + 1
    else:
        expected = 0
    row["complete"] = float(min(1.0, row["count"] / expected)) if expected else 0.0
    v = w.dropna()
    if len(v):
        row.update(min=float(v.min()), min_t=v.idxmin(), max=float(v.max()), max_t=v.idxmax(), mean=float(v.mean()), median=float(v.median()),
                   std=float(v.std()) if len(v) > 1 else 0.0, p5=float(v.quantile(.05)), p95=float(v.quantile(.95)), last=float(v.iloc[-1]))
    return row


# ------------------------------------------------------------------ charts

def _zone_runs(p, kind, yy, sat):
    sat_arr = None if sat is None else np.full(len(yy), sat)
    tier, _ = std.grade(p, yy, kind, sat_arr)
    runs, a = [], 0
    for i in range(1, len(yy) + 1):
        if i == len(yy) or tier[i] != tier[a]:
            runs.append((yy[a], yy[i - 1], tier[a]))
            a = i
    return runs


def chart_params(hp, kind, profile, ev):
    plt = _mpl()
    ps = [p for p in std.graded(kind) if p in hp and hp[p].notna().any()]
    if "temperature" in hp and hp["temperature"].notna().any():
        ps.append("temperature")
    if not ps:
        return None
    n = len(ps)
    rows = int(np.ceil(n / 2))
    fig, axes = plt.subplots(rows, 2, figsize=(7.6, 2.05 * rows), squeeze=False)
    for ax in axes.ravel()[n:]:
        ax.axis("off")
    for ax, p in zip(axes.ravel(), ps):
        s = hp[p].dropna()
        x = s.index.tz_convert(TZ)
        lo, hi = float(s.min()), float(s.max())
        pad = max((hi - lo) * 0.15, 1e-6)
        if std.spec(p, kind) is not None:
            sp = std.spec(p, kind)
            ys = [lo - pad, hi + pad]
            lim = (profile or {}).get("limits", {}).get(p)
            if lim:
                ys += [v for v in (lim["lo"], lim["hi"]) if v is not None]
            for t in sp["tiers"].values():
                ys += [t.get(k) for k in ("lo", "hi", "limit", "mgl") if t.get(k) is not None]
            y0, y1 = min(ys), max(ys)
            if p == "ph":
                y0, y1 = max(min(y0, 5.5), 0), min(max(y1, 9.5), 14)
            yy = np.linspace(y0, y1, 300)
            sat = float(hp["do_sat_mgl"].mean()) if (p == "do" and "do_sat_mgl" in hp) else None
            for a, b, t in _zone_runs(p, kind, yy, sat):
                if not np.isnan(t):
                    ax.axhspan(a, b, color=std.COLOURS[int(t)], alpha=0.16, lw=0)
            ax.set_ylim(y0, y1)
        ax.plot(x, s.values, color="#1f2d3d", lw=0.8)
        lim = (profile or {}).get("limits", {}).get(p)
        if lim:
            for v in (lim["lo"], lim["hi"]):
                if v is not None:
                    ax.axhline(v, color="#7a0019", ls="--", lw=1.1)
        ax.set_title(LABEL[p] + (f" ({C.UNIT[p]})" if C.UNIT[p] else ""), fontsize=8, loc="left")
        ax.tick_params(labelsize=6.5)
        ax.grid(alpha=0.2)
        for lab in ax.get_xticklabels():
            lab.set_rotation(20)
            lab.set_ha("right")
    fig.suptitle("Hourly averages. Background = CPCB / BIS colour zones, dashed dark red = your own limit", fontsize=7.5, y=0.995)
    fig.tight_layout()
    return _png(fig)


def chart_tier_share(wb, kind):
    plt = _mpl()
    ps = wb["params"]
    fig, ax = plt.subplots(figsize=(7.2, 0.5 + 0.45 * len(ps)))
    left = np.zeros(len(ps))
    for t in (1, 2, 3, 4):
        v = np.array([wb["param_share"][p][t] * 100 for p in ps])
        ax.barh([LABEL[p] for p in ps], v, left=left, color=std.COLOURS[t], label=std.NAMES[t])
        for i, (a, b) in enumerate(zip(left, v)):
            if b >= 8:
                ax.text(a + b / 2, i, f"{b:.0f}%", ha="center", va="center", fontsize=7, color=std.TEXT_ON[t])
        left += v
    ax.set_xlim(0, 100)
    ax.invert_yaxis()
    ax.set_xlabel("share of hours (%)", fontsize=8)
    ax.tick_params(labelsize=8)
    ax.legend(ncol=4, fontsize=7, loc="upper center", bbox_to_anchor=(0.5, 1.28), frameon=False)
    fig.tight_layout()
    return _png(fig)


def chart_whi_days(wb, start, end):
    plt = _mpl()
    from matplotlib.patches import Patch
    f = wb["frame"].dropna(subset=["whi"])
    if f.empty:
        return None
    hourly = (end - start) <= pd.Timedelta(days=2)
    g = f.groupby(f.index.tz_convert(TZ).floor("1h" if hourly else "1D"))
    mean = g["whi"].mean()
    fig, ax = plt.subplots(figsize=(7.4, 2.5))
    width = 0.035 if hourly else 0.8
    ax.bar(mean.index.tz_localize(None), mean.values, width=width, color=[std.band_colour(v) for v in mean.values], edgecolor="none")
    ax.set_ylim(0, 105)
    ax.set_ylabel("index (0 to 100, higher is better)", fontsize=8)
    ax.set_title("Water Health Index: " + ("each hour" if hourly else "each day") + ", coloured by the index band", fontsize=8.5, loc="left")
    ax.tick_params(labelsize=7)
    ax.grid(axis="y", alpha=0.25)
    ax.legend(handles=[Patch(color=std.BAND_COLOURS[i], label=f"{n} ({std.band_range_text(i)})") for i, (_, n) in enumerate(std.bands())], fontsize=6.5, ncol=5,
              loc="upper right", bbox_to_anchor=(1.0, 1.17), frameon=False)
    fig.autofmt_xdate()
    fig.tight_layout()
    return _png(fig)


def chart_expected(h, sd):
    if sd.get("status") != "ready":
        return None
    plt = _mpl()
    exp = I.sindy_expected(h, sd)
    sts = [s for s in ("do_sat", "ph") if s in sd["states"]]
    if not sts:
        return None
    end = h.index.max()
    sl = slice(end - pd.Timedelta(hours=72), end)
    fig, axes = plt.subplots(len(sts), 1, figsize=(7.4, 1.9 * len(sts)), sharex=True, squeeze=False)
    name = {"do_sat": "dissolved oxygen (% saturation)", "ph": "pH"}
    for ax, s in zip(axes[:, 0], sts):
        ax.plot(h[s].loc[sl].index.tz_convert(TZ), h[s].loc[sl].values, color="#1f2d3d", lw=1.0, label="measured")
        ax.plot(exp[s].loc[sl].index.tz_convert(TZ), exp[s].loc[sl].values, color="#c64600", lw=1.0, ls="--", label="expected from the learned daily cycle")
        ax.set_ylabel(name[s], fontsize=7)
        ax.tick_params(labelsize=7)
        ax.grid(alpha=0.25)
    axes[0, 0].legend(fontsize=7, loc="best")
    axes[0, 0].set_title("Last 3 days: measured against the daily cycle SINDy learned", fontsize=8.5, loc="left")
    fig.autofmt_xdate()
    fig.tight_layout()
    return _png(fig)


# ------------------------------------------------------------------ the report


def model_rows(m, kind):
    rows = []
    d = m.get("do", {})
    if d.get("status") == "ready":
        sc = d["scores"]
        bb, bm = d["best_baseline"], d["best_model"]
        rows.append(["Dissolved oxygen forecast (6 h)", f"{d['rows']['test']} later hours",
                     f"{bm.replace('_', ' ')} {sc[bm]['test']} vs {bb.replace('_', ' ')} {sc[bb]['test']} (saturation points, lower is better)"])
    else:
        rows.append(["Dissolved oxygen forecast (6 h)", "-", d.get("message", "Collecting data.")])

    t = m.get("turb", {})
    if t.get("status") == "ready":
        sc = t["scores"]
        rows.append(["Turbidity rise warning (6 h)", f"{t['events']['test']} rises in later data",
                     f"{t['used']} PR-AUC {sc[t['used']]['test']} vs simple rule {sc['rule']['test']} (guessing {t['base_rate_test']})"])
    else:
        rows.append(["Turbidity rise warning (6 h)", "-", t.get("message", "Collecting data.")])

    s = m.get("sindy", {})
    if s.get("status") == "ready":
        te = s["test_error"]
        best = min(("persistence", "daily_shape", "hourly_mean"), key=lambda k: te[k])
        rows.append(["SINDy daily pattern", f"{s['test_starts']} look-aheads",
                     f"SINDy {te['sindy']} vs {best.replace('_', ' ')} {te[best]} (lower is better)"])
    else:
        rows.append(["SINDy daily pattern", "-", s.get("message", "Collecting data.")])

    return rows

def build_report(df, site, period, profile, kind, user, models, is_demo=False, now=None, extra_policies=None):
    start, end, label = period
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    org = (user or {}).get("org") or (profile or {}).get("name") or ""
    ts = pd.to_datetime(df["timestamp"], utc=True)
    cad = C.cadence_minutes(df)
    doc, csvs = [], {}
    summary = {"period": label}
    if "error" in models:
        doc += [{"t": "title", "text": "JalDrishti water-quality report", "sub": label}, {"t": "p", "text": models["error"]}]
        return Report(doc, {"status": "nodata", "period": label}, csvs, "JalDrishti water-quality report")

    h = models["hours"]
    hp = h[(h.index >= start) & (h.index <= end)]
    ins = I.attach_whi(models, start, end)
    wb = ins["whi"]
    sub = df[(ts >= start) & (ts <= end)]
    quality = A.quality_summary(df, start, end, cad)
    prof = profile
    if prof and extra_policies:
        prof = dict(prof, policies=list(prof["policies"]) + [x for x in extra_policies if x not in prof["policies"]])
    limits_eval = {}
    if prof:
        for p, lim in prof["limits"].items():
            limits_eval[p] = C.evaluate_limit(df, p, lim, start, end, cad)
    ctx = {"kind": kind, "h": h, "hp": hp, "df": df, "profile": prof, "limits_eval": limits_eval, "whi": wb, "models": models, "start": start,
           "end": end, "cad": cad, "quality": quality, "deviations": models.get("sindy", {}).get("deviations", []),
           "frame": (wb.get("frame") if wb.get("status") == "ready" else None), "industry": C.industry_hint(org, (prof or {}).get("policies", [])), "org": org}
    findings = A.make_findings(ctx) if len(sub) else []
    pol_rows = A.policy_rows(ctx) if len(sub) else []
    kind_name = {"freshwater": "Fresh water", "brackish": "Brackish water", "seawater": "Sea water"}[kind]
    framework = ("CPCB designated-best-use classes A to E and BIS IS 10500 / IS 2296" if std.group(kind) == "freshwater" else "CPCB coastal-water classes SW-I to SW-V")

    # ---- title
    doc.append({"t": "title", "text": "JalDrishti water-quality report", "sub": label})
    if is_demo:
        doc.append({"t": "callout", "level": "low", "title": "DEMO DATA", "lines": ["The readings in this report are synthetic and are not from a real water body."]})
    doc.append({"t": "table", "head": ["", ""], "rows": [["Prepared for", org or "-"], ["Site", (site or {}).get("name", "-")], ["Period", f"{loc(start)} to {loc(end)}"],
                                                         ["Generated", loc(now)], ["Water type", f"{kind_name}. Colours follow {framework}."],
                                                         ["Readings", f"{len(sub):,} in the period, one every {cad} min"]], "widths": [1.2, 5], "plain": True})
    if len(sub) == 0:
        doc.append({"t": "p", "text": "There are no readings in this period, so there is nothing to report. Pick a different period."})
        return Report(doc, {"status": "nodata", "period": label}, csvs, "JalDrishti water-quality report")

    # ---- 1. at a glance
    doc.append({"t": "h1", "text": "1. At a glance"})
    lg = I.latest_grading(h[h.index <= end], kind)
    if wb.get("status") == "ready":
        bn = wb["band_mean"]
        bs = wb["band_share"]
        lines = ["Higher is better: 100 is the best and 0 is the worst. The colour comes from the index number.",
                 f"Average {wb['mean']:.0f}, lowest {wb['lowest']:.0f}, from {wb['hours']} hours with enough valid sensors.",
                 "Share of hours by band: " + ", ".join(f"{n} {pct(v)}" for n, v in bs.items() if v >= 0.005) + "."]
        doc.append({"t": "card", "fill": std.band_colour(wb["mean"]), "fg": std.band_text_on(wb["mean"]), "title": f"Water Health Index {wb['mean']:.0f} / 100 - {bn}", "lines": lines})
        alerts_ = []
        for p in wb["params"]:
            ps = wb["param_share"][p]
            if ps[3] + ps[4] >= 0.05:
                alerts_.append(f"{LABEL[p]} was Red in {pct(ps[4])} and Orange in {pct(ps[3])} of hours.")
        if alerts_:
            doc.append({"t": "h2", "text": "Parameter alerts (separate from the index number)"})
            doc.append({"t": "bullets", "items": alerts_})
        summary.update(whi_mean=wb["mean"], whi_colour=bn, red_share=wb["red_share"])
    else:
        doc.append({"t": "p", "text": "The Water Health Index could not be worked out: " + wb.get("message", "not enough valid sensors.")})
    if lg:
        chips = [chip(LABEL[p], (fmt(p, lg["values"][p]) + (" " + C.UNIT[p] if C.UNIT[p] else "")) if lg["values"][p] is not None else "-", lg["tiers"][p], std.NAMES.get(lg["tiers"][p], "") if lg["tiers"][p] else "")
                 for p in lg["tiers"]]
        doc.append({"t": "h2", "text": f"Latest hour with enough sensors ({loc(lg['as_of'])})"})
        doc.append({"t": "chips", "items": chips})
    if findings:
        doc.append({"t": "h2", "text": "What needs attention first"})
        doc.append({"t": "bullets", "items": [f"{PRI_NAME[f['priority']]}: {f['title']}" for f in findings[:4]]})
    elif prof and prof["limits"]:
        doc.append({"t": "p", "text": "Nothing needs attention: no limit you entered was crossed and no forecast or warning needs action."})
    nout = [p for p, e in limits_eval.items() if e["n_out"]]
    if prof and prof["limits"]:
        doc.append({"t": "p", "text": f"Your limits: {len(prof['limits'])} entered, {len(nout)} crossed in this period" + (": " + ", ".join(LABEL[p] for p in nout) + "." if nout else ".")})
        summary["limits_crossed"] = len(nout)
    else:
        doc.append({"t": "p", "text": "No company limits were found, so only the standards colours are shown. Save your limits in the Compliance limits tab (or in the form on this page) to get a comparison and advice written for your company."})
    summary.update(status="exceeds" if nout else ("meets" if (prof and prof["limits"]) else "nolimits"), findings=len(findings), readings=len(sub), coverage=quality["coverage"],
                   high=sum(1 for f in findings if f["priority"] == "high"))

    # ---- 2. WHI
    doc.append({"t": "h1", "text": "2. Water Health Index in detail"})
    doc.append({"t": "p", "text": "The index is a number from 0 to 100. Higher is better: 100 is the best and 0 is the worst. Its band (" + ", ".join(f"{n} {std.band_range_text(i)}" for i, (_, n) in enumerate(std.bands())) +
                                  ") comes from that number alone. Separately, each sensor takes the colour of the strictest CPCB / BIS limit it meets (Green = strictest class, Yellow = next, Orange = only the most relaxed, Red = outside every limit). "
                                  "A sensor in Orange or Red is shown as a parameter alert and does not change the band, so a good overall number never hides a weak sensor and one weak sensor never turns the whole index Red."})
    if wb.get("status") == "ready":
        head = ["Parameter", "Standard (Green limit)", "Latest", "Green", "Yellow", "Orange", "Red", "Mean score"]
        rows, fills = [], {}
        for r, p in enumerate(wb["params"]):
            sp = std.spec(p, kind)
            ps = wb["param_share"][p]
            lat = lg["tiers"].get(p) if lg else None
            rows.append([LABEL[p], f"{sp['tiers'][1]['std']}: {std.rule_text(p, kind, 1)}", std.NAMES.get(lat, "-") if lat else "-"] + [pct(ps[t]) for t in (1, 2, 3, 4)] + [f"{wb['sub_means'][p]:.0f}"])
            if lat:
                fills[(r, 2)] = std.COLOURS[lat]
            for c, t in zip((3, 4, 5, 6), (1, 2, 3, 4)):
                if ps[t] >= 0.05:
                    fills[(r, c)] = std.COLOURS[t]
        for p in std.NOT_GRADED[std.group(kind)]:
            if p in hp and hp[p].notna().any():
                rows.append([LABEL[p], std.NOT_GRADED_WHY[p], "not graded", "-", "-", "-", "-", "-"])
        doc.append({"t": "table", "head": head, "rows": rows, "fills": fills, "widths": [1.2, 3.0, 0.9, 0.7, 0.7, 0.7, 0.7, 0.8], "small": True, "csv": "whi_by_parameter"})
        doc.append({"t": "img", "bytes": chart_whi_days(wb, start, end), "caption": "Daily Water Health Index (higher is better). The colour of each bar is the index band of that day."})
        doc.append({"t": "img", "bytes": chart_tier_share(wb, kind), "caption": "Share of hours each parameter spent in each colour."})
        wts = ", ".join(f"{LABEL[k]} {v:.2f}" for k, v in wb["weights"].items())
        doc.append({"t": "p", "text": f"Weights used for the number: {wts}. They are " + wb.get("weight_source", "provisional") + ". Treat the number as provisional; the sensor colours do not depend on the weights."})
        csvs["whi_hourly"] = wb["frame"].dropna(subset=["whi"]).tz_convert(TZ).tz_localize(None).round(3)
        nb = [std.next_better(p, kind, lg["tiers"][p]) for p in wb["params"] if lg and lg["tiers"].get(p) and lg["tiers"][p] > 1]
        if nb:
            doc.append({"t": "h2", "text": "What the latest reading needs to move up a colour"})
            doc.append({"t": "bullets", "items": [x + "." for x in nb if x]})

    # ---- 3. statistics
    doc.append({"t": "h1", "text": "3. Data and statistics"})
    st_rows = []
    for p in C.PARAMS:
        if p not in df.columns:
            continue
        r = param_stats(df, p, start, end, cad)
        if r["count"] == 0:
            st_rows.append([LABEL[p] + (f" ({C.UNIT[p]})" if C.UNIT[p] else "")] + ["0", "0%"] + ["-"] * 8)
            continue
        st_rows.append([LABEL[p] + (f" ({C.UNIT[p]})" if C.UNIT[p] else ""), f"{r['count']:,}", pct(r["complete"]),
                        f"{fmt(p, r['min'])} ({pd.Timestamp(r['min_t']).tz_convert(TZ).strftime('%d %b')})", f"{fmt(p, r['max'])} ({pd.Timestamp(r['max_t']).tz_convert(TZ).strftime('%d %b')})",
                        fmt(p, r["mean"]), fmt(p, r["median"]), fmt(p, r["std"]), fmt(p, r["p5"]), fmt(p, r["p95"]), fmt(p, r["last"])])
    doc.append({"t": "table", "head": ["Parameter", "Count", "Coverage", "Minimum", "Maximum", "Mean", "Median", "Std dev", "5th pct", "95th pct", "Last"], "rows": st_rows,
                "small": True, "widths": [1.5, 0.75, 1.0, 1.25, 1.25, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8], "csv": "statistics"})
    doc.append({"t": "p", "text": "Only readings that passed the quality checks are used. Times are in India time (IST). Coverage = readings received compared with the readings expected."})
    img = chart_params(hp, kind, prof, limits_eval)
    if img:
        doc.append({"t": "img", "bytes": img, "caption": "Each parameter over the period."})

    # ---- 4. limits
    doc.append({"t": "h1", "text": "4. Your limits"})
    if prof and prof["limits"]:
        head = ["Parameter", "Your limit", "Readings", "Outside", "Periods", "Longest", "Worst value", "Latest"]
        rows, fills = [], {}
        for r, (p, e) in enumerate(limits_eval.items()):
            if e["n"] == 0:
                rows.append([LABEL[p], A.lim_text(p, e["lim"]), "0", "-", "-", "-", "-", "no data"])
                continue
            state = {"within": "within", "close": "close to limit", "outside": "outside"}[e["last_state"]]
            rows.append([LABEL[p], A.lim_text(p, e["lim"]) + (f" ({e['lim']['ref']})" if e["lim"]["ref"] else ""), f"{e['n']:,}", f"{e['pct_out']:.1f}%", str(len(e["runs"])),
                         f"{e['longest_h']:.1f} h" if e["runs"] else "-", (f"{fmt(p, e['worst'][1])} on {pd.Timestamp(e['worst'][0]).tz_convert(TZ).strftime('%d %b %H:%M')}" if e["worst"] else "-"), state])
            fills[(r, 7)] = {"within": "#d9f0df", "close": "#fdf0c4", "outside": "#f9d6d6"}[e["last_state"]]
            if e["n_out"]:
                fills[(r, 3)] = "#f9d6d6"
        doc.append({"t": "table", "head": head, "rows": rows, "fills": fills, "small": True, "widths": [1.1, 2.4, 0.8, 0.8, 0.7, 0.8, 1.7, 1.0], "csv": "limits"})
        pr = []
        for p, e in limits_eval.items():
            for r in e["runs"]:
                pr.append([LABEL[p], loc(r["start"], "%d %b %H:%M"), loc(r["end"], "%d %b %H:%M"), f"{r['hours']:.1f} h", r["side"], fmt(p, r["extreme"])])
        pr.sort(key=lambda r: r[1])
        if pr:
            doc.append({"t": "h2", "text": "Periods outside a limit" + (" (first 15 shown, all are in the CSV)" if len(pr) > 15 else "")})
            doc.append({"t": "table", "head": ["Parameter", "Start", "End", "Duration", "Side", "Most extreme"], "rows": pr[:15], "small": True, "csv": "periods_outside_limits"})
            csvs["periods_outside_limits_all"] = pd.DataFrame(pr, columns=["parameter", "start", "end", "duration", "side", "most_extreme"])
    else:
        doc.append({"t": "p", "text": "You have not entered any limits yet. Add the minimum and maximum for each parameter in the Compliance limits tab, or in the form at the top of this page, to see how the readings compare and to get advice written for your company."})
    if prof and prof.get("warnings"):
        doc.append({"t": "bullets", "items": prof["warnings"]})

    # ---- 5. models
    doc.append({"t": "h1", "text": "5. Insights from the trained models"})
    doc.append({"t": "p", "text": "These models are trained only on this site's own readings, in time order. Each is then checked on a later part of the same data against simple baselines (no change, typical day, usual value for the hour). "
                                  "A trained model is used only if it clearly beats them; otherwise the simple baseline is used and the report says so."})
    doc.append({"t": "table", "head": ["Model", "Checked on", "Result on later data"], "rows": model_rows(models, kind), "small": True, "widths": [1.5, 1.2, 4.6], "csv": "model_checks"})

    for sec in ir.sections(ins, with_images=True, include_whi=False):
        doc.append({"t": "h2", "text": sec["title"]})

        for t in sec["paras"]:
            doc.append({"t": "p", "text": t})

        if sec["bullets"]:
            doc.append({"t": "bullets", "items": sec["bullets"]})

        if sec.get("image"):
            doc.append({"t": "img", "bytes": sec["image"], "caption": ""})

        if sec.get("equations"):
            doc.append({
                "t": "p",
                "small": True,
                "text": "SINDy equations (change in one hour, standardised units; sin24 and cos24 are the time of day): "
                + " | ".join(
                    f"{ir.LABEL.get(k, k)}: {v}"
                    for k, v in sec["equations"].items()
                )
            })

    sd = models.get("sindy", {})
    ex = chart_expected(h[h.index <= end], sd)
    if ex:
        doc.append({"t": "img", "bytes": ex, "caption": "Dashed line = expected value from the learned daily cycle."})
    devs = [d for d in sd.get("deviations", []) if start <= d["start"] <= end]
    if devs:
        nm = {"do_sat": "Dissolved oxygen (% sat)", "ph": "pH", "logturb": "Turbidity (log)"}
        doc.append({"t": "h2", "text": "Stretches away from the learned daily pattern (experimental)"})
        doc.append({"t": "table", "head": ["Parameter", "Start", "Hours", "Direction", "Measured", "Expected"],
                    "rows": [[nm[d["state"]], loc(d["start"], "%d %b %H:%M"), str(d["hours"]), d["direction"], f"{d['observed']:.2f}", f"{d['expected']:.2f}"] for d in devs[:10]], "small": True, "csv": "pattern_deviations"})

    # ---- 6. findings
    doc.append({"t": "h1", "text": "6. Problems found and what to do"})
    if not findings:
        doc.append({"t": "p", "text": "No problems were found in this period from the limits you entered, the Water Health Index colours, the forecasts or the data quality."})
    for i, f in enumerate(findings[:10], 1):
        doc.append({"t": "callout", "level": f["priority"], "title": f"{i}. {f['title']} [{PRI_NAME[f['priority']]}]", "lines": [f["see"]]})
        if f["evidence"]:
            doc.append({"t": "h3", "text": "What the data shows"})
            doc.append({"t": "bullets", "items": f["evidence"]})
        if f["factors"]:
            doc.append({"t": "h3", "text": "Possible contributing factors (not confirmed by the sensors)"})
            doc.append({"t": "bullets", "items": f["factors"][:5]})
        if f["steps"]:
            doc.append({"t": "h3", "text": "Suggested next steps"})
            doc.append({"t": "bullets", "items": f["steps"][:7]})
        if f["policy"]:
            doc.append({"t": "h3", "text": "Your policies that apply"})
            doc.append({"t": "bullets", "items": ['"' + x + '"' for x in f["policy"][:4]]})
    if len(findings) > 10:
        doc.append({"t": "p", "text": f"{len(findings) - 10} further lower-priority items are not shown."})

    # ---- 7. policies
    doc.append({"t": "h1", "text": "7. Your policies and what the data shows"})
    if pol_rows:
        fills = {(r, 2): row["fill"] for r, row in enumerate(pol_rows)}
        doc.append({"t": "table", "head": ["Your policy or requirement", "What the buoy shows", "Status", "How to comply"], "rows": [[r["policy"], r["shows"], r["status"], r["how"]] for r in pol_rows],
                    "fills": fills, "small": True, "widths": [1.8, 2.4, 1.0, 2.6], "csv": "policies"})
    elif prof:
        doc.append({"t": "p", "text": "No policy sentences were found in your saved profile. Add them in the Compliance limits tab (or the form on this page) and they will be checked here."})
    else:
        doc.append({"t": "p", "text": "No company profile was found."})

    # ---- 8. data quality
    doc.append({"t": "h1", "text": "8. Data quality"})
    items = [f"{quality['rows']:,} rows in the period; {quality['coverage'] * 100:.0f}% of the expected readings arrived; longest gap {quality['longest_gap_h']:.1f} h."]
    fl = [f"{LABEL[p]} {n}" for p, n in quality["flags"].items() if n]
    items.append("Readings marked faulty: " + (", ".join(fl) if fl else "none") + ". Faulty readings are left out of every statistic and colour.")
    if quality["last"] is not None:
        items.append(f"Last reading in the period: {loc(quality['last'])}.")
    doc.append({"t": "bullets", "items": items})

    # ---- 9. method
    doc.append({"t": "h1", "text": "9. Method and standards used"})
    doc.append({"t": "bullets", "items": [
        "Sensor colours: each hourly average is compared with the limits below; the colour is the strictest class limit it meets. They are shown as parameter alerts and do not set the index band.",
        "Water Health Index number: each parameter is scored 0 to 100 (100 at the strictest limit, 80 and 60 at the next limits, under 60 beyond the last limit) and the scores are combined with a weighted average. Higher is better. The overall band (Excellent, Good, Fair, Marginal, Poor) comes from this number using the cut-offs 95, 80, 65 and 45, which are provisional design choices. A weighted average can look good while one sensor is poor, which is why Orange and Red sensors are listed separately as parameter alerts.",
        "Models: DO forecast (ridge regression and XGBoost against three baselines), turbidity-rise warning (logistic regression and XGBoost against a 3-hour-rise rule) and SINDy (sparse equations of the daily cycle). Training uses the first 60% of the site's usable hours, tuning the next 20% and testing the last 20%, with a 6-hour gap between the parts.",
        "Tides are not an input to the models yet; in a tidal creek the daily pattern and the tidal pattern are mixed.",
        "Salinity for the oxygen-saturation calculation is estimated as TDS divided by 1000, and sea-level pressure is assumed.",
        "All times are India time (IST)."]})
    rows, fills = [], {}
    for r, x in enumerate(std.table_rows(kind)):
        rows.append([x["label"], x["colour"], x["rule"], x["std"] + (f" ({x['use']})" if x["use"] else ""), "check" if x["verify"] else ""])
        if x["tier"]:
            fills[(r, 1)] = std.COLOURS[x["tier"]]
    doc.append({"t": "table", "head": ["Parameter", "Colour", "Rule", "Standard", "Verify"], "rows": rows, "fills": fills, "small": True, "widths": [1.3, 0.8, 2.4, 3.0, 0.6], "csv": "standards_used"})
    doc.append({"t": "p", "small": True, "text": "The limits in this table were entered from memory without access to the official documents. Rows marked 'check' are the least certain. Please check them against the current CPCB and BIS publications before relying on them."})
    return Report(doc, summary, csvs, "JalDrishti water-quality report", base="JalDrishti_report", findings=findings, policies=pol_rows, limits_eval=limits_eval)
