"""Downloadable observation report (Markdown) in the selected language."""
import pandas as pd
from . import config
from .i18n import t, param_label, fmt_datetime, fmt_with_unit
from .explain import status_label, reason_text, issues_text, next_steps, params_text


def _flag_text(flag, lang):
    return t(f"flag_{flag}", lang)


def build_report(lang, site, is_demo, status, latest_row, whi_result, quality, n_observations, now=None):
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    na = t("report_not_applicable", lang)
    lines = [f"# {t('report_title', lang)}", ""]
    if is_demo:
        lines += [f"> **{t('demo_banner', lang)}**", ""]
    coords = f"{site['latitude']:.5f}, {site['longitude']:.5f}" if site.get("coords") else na
    lines += [f"- {t('report_generated', lang)}: {fmt_datetime(now, lang)} (IST)",
              f"- {t('report_site', lang)}: {site['name']} ({site['id']})",
              f"- {t('report_location', lang)}: {coords}",
              f"- {t('report_data_source', lang)}: {t('source_demo', lang) if is_demo else t('source_local', lang)}", ""]
    lines += [f"## {t('report_status', lang)}", "",
              f"**{status_label(status.state, lang, technical=True)}**", "",
              reason_text(status, lang), ""]
    if issues_text(status, lang):
        lines += [issues_text(status, lang), ""]
    lines += [f"{t('report_observed', lang)}: {fmt_datetime(status.latest_time, lang)}", ""]

    lines += [f"## {t('report_findings', lang)}", ""]
    if status.findings:
        lines += [f"| {t('col_parameter', lang)} | {t('col_value', lang)} | {t('legend_baseline', lang)} | {t('col_direction', lang)} | {t('col_zscore', lang)} | {t('col_strength', lang)} |",
                  "|---|---|---|---|---|---|"]
        for f in status.findings:
            direction = t("dir_up" if f.direction == "up" else "dir_down", lang)
            lines.append(f"| {param_label(f.param, lang)} | {fmt_with_unit(f.value, f.param)} | {fmt_with_unit(f.baseline, f.param)} | "
                         f"{direction} | {f.z:+.1f} | {t('strength_' + f.strength, lang)} |")
        lines += ["", t("strength_note", lang), ""]
    else:
        lines += [t("report_none_flagged", lang), ""]

    lines += [f"## {t('report_readings', lang)}", "",
              f"| {t('col_parameter', lang)} | {t('col_value', lang)} | {t('col_flag', lang)} |", "|---|---|---|"]
    for p in config.PARAMS:
        val = latest_row[p] if latest_row is not None else None
        flag = latest_row[f"{p}_flag"] if latest_row is not None else "missing"
        lines.append(f"| {param_label(p, lang)} | {fmt_with_unit(val, p)} | {_flag_text(flag, lang)} |")
    lines.append("")

    lines += [f"## {t('report_whi', lang)}", ""]
    if whi_result is not None and whi_result.score is not None:
        lines.append(f"{whi_result.score:.1f} / 100 — {t('band_' + whi_result.band, lang)}")
    elif whi_result is not None:
        lines.append(t("whi_unavailable", lang, params=params_text(whi_result.missing, lang)))
    lines += ["", t("whi_provisional", lang), ""]

    lines += [f"## {t('report_quality', lang)}", ""]
    for p in config.PARAMS:
        c = quality.get("completeness", {}).get(p)
        if c is not None:
            lines.append(f"- {param_label(p, lang)}: {t('completeness', lang)} {c:.0f}% (24 h)")
    lines.append(f"- {t('report_observations', lang, n=n_observations)}")
    lines.append("")

    steps = next_steps(status, lang)
    if steps:
        lines += [f"## {t('report_recommendations', lang)}", ""] + [f"- {s}" for s in steps] + [""]
    lines += [f"## {t('report_limitations', lang)}", ""] + [f"- {t(f'lim_{i}', lang)}" for i in range(1, 8)] + [""]
    lines += [f"_{t('methods_version', lang, v=config.METHOD_VERSION)}_", ""]
    if not config.TRANSLATIONS_REVIEWED.get(lang, True):
        lines += [f"_{t('translation_review', lang)}_", ""]
    return "\n".join(lines)
