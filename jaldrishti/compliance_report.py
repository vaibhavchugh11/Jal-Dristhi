"""Wording, insights and the downloadable report for the company limit screening."""
import pandas as pd
from . import config
from .i18n import t, param_label, fmt_datetime, fmt_with_unit

PERIODS = {24: "period_24h", 168: "period_7d", 336: "period_14d"}
OVERALL_KEY = {"none": "firm_status_none", "unavailable": "firm_status_unavailable", "outside": "firm_status_outside",
               "near": "firm_status_near", "within": "firm_status_within"}
STATUS_ICON = {"outside": "▲", "near": "◐", "within": "✓", "nodata": "○"}


def period_label(hours, lang):
    return t(PERIODS.get(hours, "period_7d"), lang)


def fmt_duration(minutes, lang):
    if minutes < 120:
        return t("duration_min", lang, n=int(round(minutes)))
    return t("duration_hr", lang, n=f"{minutes / 60:.1f}")


def limit_text(limit, param, lang):
    lo, hi = limit.get("min"), limit.get("max")
    unit = f" {config.UNITS[param]}" if config.UNITS[param] else ""
    f = lambda v: f"{v:g}"
    if lo is not None and hi is not None:
        return t("limit_range", lang, lo=f(lo), hi=f(hi)) + unit
    if hi is not None:
        return t("limit_max_only", lang, hi=f(hi)) + unit
    return t("limit_min_only", lang, lo=f(lo)) + unit


def insights(result, lang):
    out = []
    period = period_label(result.period_hours, lang)
    for p in config.PARAMS:
        pr = result.params.get(p)
        if pr is None or pr.status == "nodata":
            continue
        name, lim = param_label(p, lang), limit_text(pr.limit, p, lang)
        val = fmt_with_unit(pr.latest, p)
        if pr.status == "outside":
            out.append(t("ins_outside_now", lang, param=name, value=val, limit=lim))
        elif pr.status == "near":
            if pr.trend:
                out.append(t("ins_near", lang, param=name, value=val, limit=lim, trend=t("trend_" + pr.trend, lang)))
            else:
                out.append(t("ins_near_plain", lang, param=name, value=val, limit=lim))
        if pr.episodes:
            out.append(t("ins_episodes", lang, param=name, n=len(pr.episodes), period=period,
                         longest=fmt_duration(pr.longest_min, lang), peak=fmt_with_unit(pr.peak, p),
                         time=fmt_datetime(pr.peak_time, lang)))
            linked = [e for e in pr.episodes if e.unusual_event]
            if linked:
                out.append(t("ins_unusual", lang, param=name, time=fmt_datetime(linked[0].start, lang)))
        else:
            out.append(t("ins_none", lang, param=name, period=period))
        if pr.usable_pct < 70:
            out.append(t("ins_low_data", lang, param=name, pct=f"{pr.usable_pct:.0f}"))
    return out


def action_list(result, lang):
    if result.overall in ("outside", "near"):
        return [t(f"firm_act_{i}", lang) for i in (1, 2, 3, 4)]
    if result.overall == "unavailable":
        return [t("firm_act_2", lang)]
    return []


def episodes_frame(result, lang):
    rows = []
    for p, pr in result.params.items():
        for e in pr.episodes:
            rows.append({"parameter": param_label(p, lang), "start_utc": e.start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                         "end_utc": e.end.strftime("%Y-%m-%dT%H:%M:%SZ"), "duration_min": round(e.duration_min),
                         "readings": e.n_readings, "peak": round(e.peak, 3),
                         "peak_time_utc": e.peak_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
                         "limit": limit_text(pr.limit, p, lang), "unusual_change_detected": e.unusual_event})
    return pd.DataFrame(rows)


def build_report(lang, profile, site, result, is_demo, now=None):
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    lines = [f"# {t('rpt_title', lang)}", ""]
    if is_demo:
        lines += [f"> **{t('demo_banner', lang)}**", ""]
    lines += [f"> {t('firm_disclaimer', lang)}", ""]
    lines += [f"- {t('rpt_company', lang)}: {profile['name']}",
              f"- {t('report_site', lang)}: {site['name']} ({site['id']})",
              f"- {t('report_generated', lang)}: {fmt_datetime(now, lang)} (IST)",
              f"- {t('firm_period', lang)}: {period_label(result.period_hours, lang)}",
              f"- {t('report_observed', lang)}: {fmt_datetime(result.latest_time, lang)}"]
    if profile.get("relation"):
        lines.append(f"- {t('firm_relation', lang)}: {profile['relation']}")
    if profile.get("notes"):
        lines.append(f"- {t('firm_notes', lang)}: {profile['notes']}")
    lines += ["", f"**{t(OVERALL_KEY[result.overall], lang)}**"]
    if result.counts:
        lines.append(t("firm_summary", lang, out=result.counts["outside"], near=result.counts["near"],
                       within=result.counts["within"], nodata=result.counts["nodata"]))
    lines += ["", f"## {t('rpt_limits', lang)}", "",
              f"| {t('col_parameter', lang)} | {t('col_limit', lang)} | {t('rpt_basis', lang)} | {t('rpt_reference', lang)} |", "|---|---|---|---|"]
    for p in config.PARAMS:
        lim = profile["limits"].get(p)
        if lim:
            lines.append(f"| {param_label(p, lang)} | {limit_text(lim, p, lang)} | {t('basis_' + lim['basis'], lang)} | {lim.get('reference') or '—'} |")
    lines += ["", f"## {t('rpt_results', lang)}", "",
              f"| {t('col_parameter', lang)} | {t('col_latest', lang)} | {t('col_status', lang)} | {t('col_pct_outside', lang)} | {t('col_episodes', lang)} | {t('col_peak', lang)} |",
              "|---|---|---|---|---|---|"]
    for p in config.PARAMS:
        pr = result.params.get(p)
        if pr:
            lines.append(f"| {param_label(p, lang)} | {fmt_with_unit(pr.latest, p)} | {t('st_' + pr.status, lang)} | "
                         f"{pr.pct_outside:.1f}% | {len(pr.episodes)} | {fmt_with_unit(pr.peak, p)} |")
    ins = insights(result, lang)
    if ins:
        lines += ["", f"## {t('firm_insights', lang)}", ""] + [f"- {x}" for x in ins]
    acts = action_list(result, lang)
    if acts:
        lines += ["", f"## {t('next_steps', lang)}", ""] + [f"- {x}" for x in acts]
    lines += ["", f"## {t('report_limitations', lang)}", "", f"- {t('rpt_buoy_note', lang)}", f"- {t('rpt_not_legal', lang)}",
              f"- {t('lim_1', lang)}", f"- {t('lim_4', lang)}", f"- {t('lim_5', lang)}", f"- {t('lim_6', lang)}", ""]
    lines += [f"_{t('methods_version', lang, v=config.METHOD_VERSION)}_", ""]
    if not config.TRANSLATIONS_REVIEWED.get(lang, True):
        lines += [f"_{t('translation_review', lang)}_", ""]
    return "\n".join(lines)
