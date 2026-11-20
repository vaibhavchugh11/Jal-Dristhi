import io

import numpy as np
import pandas as pd

TZ = "Asia/Kolkata"
LABEL = {"temperature": "temperature", "do_sat": "dissolved oxygen (% saturation)", "ph": "pH", "logturb": "turbidity (log scale)", "tds": "TDS"}
UNIT = {"temperature": "C", "do_sat": "points of saturation", "ph": "pH units", "logturb": "log units", "tds": "mg/L"}
METHOD_NAME = {"persistence": "no change from now", "daily_shape": "typical shape of the day", "hourly_mean": "usual value for that hour",
               "ridge": "ridge regression", "xgboost": "XGBoost", "logistic": "logistic regression", "rule": "simple rule (3 hour rise in turbidity)"}


def local(ts):
    return pd.Timestamp(ts).tz_convert(TZ).strftime("%d %b %H:%M IST")


def hour_local(utc_hour):
    # an hourly value starting at HH:00 UTC is centred on HH:30 UTC, which is HH+6:00 in India
    m = (int(utc_hour) * 60 + 30 + 330) % 1440
    return "%02d:%02d" % (m // 60, m % 60)


def _png(fig):
    import matplotlib.pyplot as plt
    b = io.BytesIO()
    fig.savefig(b, format="png", dpi=130)
    plt.close(fig)
    return b.getvalue()


def chart_forecast(ins):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    d, h = ins["do"], ins["hours"]
    if d.get("status") != "ready":
        return None
    end = d["as_of"]
    x = h["do_sat"].loc[end - pd.Timedelta(hours=72):end]
    fig, ax = plt.subplots(figsize=(7.2, 2.6))
    ax.plot(x.index.tz_convert(TZ), x.values, color="#1a5fb4", lw=1.2, label="measured")
    t2 = (end + pd.Timedelta(hours=d["horizon_h"])).tz_convert(TZ)
    ax.errorbar([t2], [d["pred_pct"]], yerr=[[d["pred_pct"] - d["lo_pct"]], [d["hi_pct"] - d["pred_pct"]]], fmt="o", color="#c64600", capsize=4, label="forecast (5 to 95% range)")
    ax.set_ylabel("DO, % saturation", fontsize=8)
    ax.set_title("Dissolved oxygen: last 3 days and the next %d hours" % d["horizon_h"], fontsize=9, loc="left")
    ax.tick_params(labelsize=7)
    ax.grid(alpha=0.25)
    ax.legend(fontsize=7, loc="best")
    fig.tight_layout()
    return _png(fig)


def chart_whi(ins):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    w = ins["whi"]
    if w.get("status") != "ready":
        return None
    s = w["series"].dropna()
    if (s.index.max() - s.index.min()) > pd.Timedelta(days=3):
        s = s.resample("1D").mean().dropna()
    fig, ax = plt.subplots(figsize=(7.2, 2.3))
    ax.plot(s.index.tz_convert(TZ), s.values, color="#006d2c", lw=1)
    ax.set_ylim(0, 102)
    ax.set_ylabel("score", fontsize=8)
    ax.set_title("Water Health Index (provisional)", fontsize=9, loc="left")
    ax.tick_params(labelsize=7)
    ax.grid(alpha=0.25)
    fig.tight_layout()
    return _png(fig)


def sections(ins, do_limit=None, with_images=True, include_whi=True):
    # plain description of each model output, used by the page and by the PDF
    out = []
    if "error" in ins:
        return [{"title": "Forecast and early warning", "status": "none", "paras": [ins["error"]], "bullets": [], "image": None}]
    d = ins["do"]
    sec = {"title": "Dissolved oxygen forecast (next %d hours)" % d["horizon_h"], "status": d["status"], "paras": [], "bullets": [], "image": None}
    if d["status"] != "ready":
        sec["paras"].append(d["message"])
    else:
        sec["paras"].append(f"As of {local(d['as_of'])}: dissolved oxygen is {d['now_mgl']:.1f} mg/L ({d['now_pct']:.0f}% saturation). "
                            f"In {d['horizon_h']} hours it is expected to be about {d['pred_mgl']:.1f} mg/L "
                            f"({d['pred_pct']:.0f}% saturation), most likely between {d['lo_mgl']:.1f} and {d['hi_mgl']:.1f} mg/L.")
        sc = d["scores"]
        bb, bm = d["best_baseline"], d["best_model"]
        if d["adopted_model"]:
            sec["paras"].append(f"Method: {METHOD_NAME[d['used']]}. It beat the best simple baseline ({METHOD_NAME[bb]}) by at least 5% on both the "
                                f"tuning part and the latest part of this site's data, so it is used.")
        else:
            sec["paras"].append(f"Method: {METHOD_NAME[d['used']]} (a simple baseline). The trained models ({METHOD_NAME[bm]} was the best) did not beat it by at least 5% "
                                "on both checks on this site's data, so the simple baseline is used.")
        sec["bullets"] += [
            f"Test error on the latest part of the data (typical miss, in saturation points): " + ", ".join(
                f"{METHOD_NAME[k]} {v['test']}" for k, v in sc.items()) + ".",
            f"Hours used: {d['rows']['train']} to train, {d['rows']['val']} to tune, {d['rows']['test']} to test (in time order, never shuffled).",
            "The range comes from the errors made on the test part. It assumes the water temperature stays the same when converting % saturation to mg/L."]
        if (d["data_end"] - d["as_of"]) > pd.Timedelta(hours=3):
            sec["bullets"].append(f"The newest complete hour is {local(d['as_of'])}, older than the last reading, so the forecast is for that time.")
        if do_limit is not None:
            if d["hi_mgl"] < do_limit:
                sec["bullets"].append(f"The whole forecast range is below your minimum of {do_limit:g} mg/L.")
            elif d["lo_mgl"] < do_limit:
                sec["bullets"].append(f"The lower end of the forecast range is below your minimum of {do_limit:g} mg/L. Check the aerators or discharge before then.")
            else:
                sec["bullets"].append(f"The forecast range stays above your minimum of {do_limit:g} mg/L.")
        if with_images:
            sec["image"] = chart_forecast(ins)
    out.append(sec)

    t = ins["turb"]
    sec = {"title": "Turbidity rise warning (next %d hours)" % t["horizon_h"], "status": t["status"], "paras": [], "bullets": [], "image": None}
    if t["status"] in ("collecting", "too_few_events", "not_useful"):
        sec["paras"].append(t["message"])
    else:
        state = "ELEVATED" if t["elevated"] else "normal"
        sec["paras"].append(f"As of {local(t['as_of'])} the warning level is {state}." +
                            (" Turbidity is already above its usual level." if t["already_high"] else ""))
        sec["paras"].append(f"On the latest part of this site's data, about {t['test_precision'] * 100:.0f} in 100 alerts were followed by a turbidity rise within "
                            f"{t['horizon_h']} hours, and about {t['test_recall'] * 100:.0f} in 100 rises were warned about in advance.")
        sc = t["scores"]
        sec["bullets"] += [
            f"Method: {METHOD_NAME[t['used']]}." + (" It beat the simple rule by at least 10% on both checks." if t["adopted_model"]
                                                     else " The trained models did not beat this simple rule clearly enough on this site."),
            "Ranking quality (PR-AUC, tuning / latest part): " + ", ".join(f"{METHOD_NAME[k]} {v['val']} / {v['test']}" for k, v in sc.items()) +
            f". Guessing would score about {t['base_rate_test']}.",
            f"Turbidity rises seen: {t['events']['train_val']} in the earlier data, {t['events']['test']} in the latest part.",
            "A rise is a jump above the past 30 day median larger than normal wobble. Rain and tides also cause rises, so an alert does not mean pollution."]
    out.append(sec)

    s = ins["sindy"]
    sec = {"title": "Expected daily pattern (SINDy)", "status": s["status"], "paras": [], "bullets": [], "image": None}
    if s["status"] != "ready":
        sec["paras"].append(s["message"])
    else:
        sw = s["daily_swing"]
        for k, v in sw.items():
            if v["swing"] > 0 and k not in ("logturb", "tds"):
                sec["bullets"].append(f"{LABEL[k]}: usual daily swing about {v['swing']:.2g} {UNIT[k]}, highest around {hour_local(v['peak_hour_utc'])} and lowest around {hour_local(v['low_hour_utc'])}.")
        te = s["test_error"]
        best = min(("persistence", "daily_shape", "hourly_mean"), key=lambda k: te[k])
        verdict = ("beat the simple baselines" if s["beats_baselines"] else "did not beat the best simple baseline")
        sec["paras"].append(f"SINDy fitted sparse equations to this site's hourly data. For {6} hour look-aheads on the latest part of the data it {verdict} "
                            f"(error {te['sindy']} against {te[best]} for '{METHOD_NAME[best]}'; lower is better).")
        sec["bullets"].append("The equations show statistical links in this site's data. They are not proven physical laws and they cannot identify a pollutant.")
        sec["equations"] = s["equations"]
    out.append(sec)

    if not include_whi:
        return out
    w = ins["whi"]
    sec = {"title": "Water Health Index (provisional)", "status": w["status"], "paras": [], "bullets": [], "image": None}
    if w["status"] != "ready":
        sec["paras"].append(w["message"])
    else:
        sec["paras"].append(f"Average {w['mean']:.0f}, lowest {w['lowest']:.0f} over {w['hours']} hours with enough valid sensors (water type: {ins['kind']}).")
        sec["bullets"] += [
            "Average sub-scores (0 to 100): " + ", ".join(f"{k} {v:.0f}" for k, v in w["sub_means"].items()) + ".",
            "Most often the limiting parameter: " + ", ".join(f"{k} {v * 100:.0f}%" for k, v in sorted(w["weakest_share"].items(), key=lambda a: -a[1])[:3]) + ".",
            "Weights: " + ", ".join(f"{k} {v:.2f}" for k, v in w["weights"].items()) + ". These are placeholder expert judgements and have not been surveyed.",
            "Limits used: " + w["source"] + "."]
        if with_images:
            sec["image"] = chart_whi(ins)
    out.append(sec)
    return out


def to_pdf(ins, org="", site="", period_label="", do_limit=None):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.platypus import Image, ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer
    from xml.sax.saxutils import escape
    st_t = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=colors.HexColor("#1a5fb4"), spaceAfter=6)
    st_h = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=12.5, leading=15, textColor=colors.HexColor("#1a5fb4"), spaceBefore=12, spaceAfter=4, keepWithNext=1)
    st_p = ParagraphStyle("p", fontName="Helvetica", fontSize=9.5, leading=12.5, spaceAfter=4)
    st_s = ParagraphStyle("s", fontName="Helvetica", fontSize=8, leading=10, textColor=colors.HexColor("#555555"))
    story = [Paragraph("Forecast and early-warning addendum", st_t)]
    meta = [x for x in (f"Prepared for: {org}" if org else "", f"Site: {site}" if site else "", f"Period: {period_label}" if period_label else "") if x]
    for m in meta:
        story.append(Paragraph(escape(m), st_p))
    story.append(Paragraph("Experimental. These outputs are trained on this site's own data and checked against simple baselines on later data. "
                           "They are screening aids, not legal compliance findings.", st_s))
    for sec in sections(ins, do_limit):
        story.append(Paragraph(escape(sec["title"]), st_h))
        for p in sec["paras"]:
            story.append(Paragraph(escape(p), st_p))
        if sec["bullets"]:
            story.append(ListFlowable([ListItem(Paragraph(escape(b), st_p)) for b in sec["bullets"]], bulletType="bullet", leftIndent=14))
        if sec.get("image"):
            story.append(Spacer(1, 4))
            story.append(Image(io.BytesIO(sec["image"]), width=16.5 * cm, height=16.5 * cm * 0.36))
        if sec.get("equations"):
            story.append(Paragraph("Equations (change in one hour, in standardised units; sin24 and cos24 are the time of day):", st_s))
            for k, v in sec["equations"].items():
                story.append(Paragraph(escape(f"{LABEL.get(k, k)}: {v}"), st_s))
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.8 * cm, rightMargin=1.8 * cm, topMargin=1.6 * cm, bottomMargin=1.6 * cm,
                      title="Forecast and early-warning addendum").build(story)
    return buf.getvalue()


def merge_pdfs(first, second):
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter()
    for b in (first, second):
        for p in PdfReader(io.BytesIO(b)).pages:
            w.add_page(p)
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()
