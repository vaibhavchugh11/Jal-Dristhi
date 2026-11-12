"""Technical / authority mode: full readings, history, data quality, WHI breakdown, events, reports."""
import pandas as pd
import streamlit as st
from .. import config, observations, reviews, reports
from ..charts import param_figure, whi_figure
from ..explain import params_text, pattern_text
from ..i18n import t, param_label, fmt_datetime, fmt_relative, fmt_value, fmt_with_unit, to_local
from . import components as c
from .data_view import date_filter, render as data_tab


def render(ctx):
    lang = ctx["lang"]
    names = ["tab_overview", "tab_history", "tab_data", "tab_quality", "tab_alerts", "tab_report", "tab_methods"]
    tabs = st.tabs([t(n, lang) for n in names])
    for tab, fn in zip(tabs, [overview, history, data_tab, quality_tab, alerts_tab, report_tab, methods_tab]):
        with tab:
            fn(ctx)


def _table(df):
    st.dataframe(df, hide_index=True, width="stretch")


def overview(ctx):
    lang, b, status = ctx["lang"], ctx["bundle"], ctx["status"]
    c.status_banner(status, lang, technical=True)
    st.markdown(f"#### {t('latest_readings', lang)}")
    latest = b.df.iloc[-1] if len(b.df) else None
    c.sensor_cards(latest, lang, sig=b.analysis.signals)
    left, right = st.columns(2)
    with left:
        st.markdown(f"#### {t('whi_heading', lang)}")
        r = b.whi_latest
        if r.score is not None:
            st.markdown(f'<div class="jd-card"><span class="jd-whi-score">{r.score:.1f}</span> / 100'
                        f'<span class="jd-badge">{c.esc(t("band_" + r.band, lang))}</span></div>', unsafe_allow_html=True)
        else:
            st.warning(t("whi_unavailable", lang, params=params_text(r.missing, lang)))
        if r.components:
            _table(pd.DataFrame([{t("col_parameter", lang): param_label(x["param"], lang),
                                  t("col_value", lang): fmt_with_unit(x["value"], x["param"]),
                                  t("col_subindex", lang): f"{x['subindex']:.0f}",
                                  t("col_weight", lang): f"{x['weight']:.3f}",
                                  t("col_contribution", lang): f"{x['contribution']:.1f}"} for x in r.components]))
        st.markdown(f'<div class="jd-prov">{c.esc(t("whi_provisional", lang))}</div>', unsafe_allow_html=True)
        st.caption(t("whi_temp_note", lang))
        st.caption(t("whi_separate_note", lang))
    with right:
        st.markdown(f"#### {t('anomaly_heading', lang)}")
        st.caption(t("baseline_info", lang, hours=config.BASELINE_HOURS, excl=config.EXCLUSION_HOURS,
                     z=config.Z_THRESHOLD, n=config.PERSIST_N))
        if status.findings:
            st.markdown(f"**{t('contributing', lang)}**")
            _table(pd.DataFrame([{t("col_parameter", lang): param_label(f.param, lang),
                                  t("col_value", lang): fmt_with_unit(f.value, f.param),
                                  t("legend_baseline", lang): fmt_with_unit(f.baseline, f.param),
                                  t("col_direction", lang): ("▲ " if f.direction == "up" else "▼ ") + t("dir_" + f.direction, lang),
                                  t("col_zscore", lang): f"{f.z:+.1f}",
                                  t("col_strength", lang): t("strength_" + f.strength, lang)} for f in status.findings]))
        else:
            st.info(t("no_contributing", lang))
        st.caption(t("strength_note", lang))
        st.caption(t("no_ml_model", lang))
    st.markdown(f"#### {t('recent_events', lang)}")
    events = b.analysis.events
    if not events:
        st.caption(t("events_none", lang))
    else:
        st.caption(t("event_summary", lang, n=len(events), time=fmt_datetime(events[-1].start, lang)))
        for e in reversed(events[-3:]):
            st.markdown(f"**{fmt_datetime(e.start, lang)}** · {t('duration_min', lang, n=e.duration_min)} · "
                        f"{', '.join(('▲ ' if e.direction[p] == 'up' else '▼ ') + param_label(p, lang) for p in e.params)}  \n"
                        f"{pattern_text(e, lang)}")
        st.caption(t("pattern_caution", lang))


def history(ctx):
    lang, b = ctx["lang"], ctx["bundle"]
    st.subheader(t("history_heading", lang))
    st.caption(t("tz_note", lang))
    if b.df.empty:
        st.info(t("no_rows", lang))
        return
    view = date_filter(b.df, lang, "hist_range")
    col1, col2 = st.columns(2)
    show_base = col1.checkbox(t("show_baseline", lang), value=True)
    show_ev = col2.checkbox(t("show_events", lang), value=True)
    params = st.multiselect(t("pick_parameter", lang), config.PARAMS, default=config.PARAMS,
                            format_func=lambda k: param_label(k, lang))
    if view.empty:
        st.info(t("no_rows", lang))
        return
    for p in params:
        st.plotly_chart(param_figure(lang, view, p, sig=b.analysis.signals, events=b.analysis.events,
                                     show_baseline=show_base, show_events=show_ev, height=270),
                        width="stretch", config={"displayModeBar": False}, key=f"hist_{p}")
    st.plotly_chart(whi_figure(lang, view, b.whi_series.loc[view.index]), width="stretch", config={"displayModeBar": False}, key="hist_whi")
    st.caption(t("whi_provisional", lang))


def quality_tab(ctx):
    lang, b, q, site = ctx["lang"], ctx["bundle"], ctx["bundle"].quality, ctx["site"]
    st.subheader(t("quality_heading", lang))
    conn = {"online": "conn_online", "stale": "conn_stale", "nodata": "conn_nodata"}[q["connection"]]
    m = st.columns(4)
    m[0].metric(t("connection", lang), t(conn, lang))
    m[1].metric(t("last_received", lang), fmt_relative(q["age_minutes"], lang))
    m[2].metric(t("cadence", lang), t("duration_min", lang, n=q["cadence"]))
    m[3].metric(t("readings_total", lang), q["n_readings"])
    if b.rows_rejected:
        st.warning(t("rows_rejected", lang, n=b.rows_rejected))
    if b.duplicates_removed:
        st.info(t("duplicates_removed", lang, n=b.duplicates_removed))
    if q["completeness"]:
        st.markdown(f"#### {t('completeness', lang)} (24 h)")
        _table(pd.DataFrame([{t("col_parameter", lang): param_label(p, lang), t("completeness", lang): f"{v:.0f}%"}
                             for p, v in q["completeness"].items()]))
        st.markdown(f"#### {t('flags_summary', lang)}")
        rows = []
        for p, counts in q["flags"].items():
            row = {t("col_parameter", lang): param_label(p, lang)}
            row.update({t("flag_" + k, lang): v for k, v in counts.items()})
            rows.append(row)
        _table(pd.DataFrame(rows))
    st.markdown(f"#### {t('calibration_heading', lang)}")
    cal = ctx["calibration"]
    cal = cal[cal["device_id"].isin(b.df["device_id"].unique())] if len(b.df) and len(cal) else cal
    if cal.empty:
        st.info(t("calibration_none", lang))
    else:
        _table(cal)
    st.markdown(f"#### {t('location_heading', lang)}")
    st.write(f"**{t('site_id', lang)}:** {site['id']}  \n**{t('coordinates', lang)}:** "
             f"{(str(site['coords'][0]) + ', ' + str(site['coords'][1])) if site['coords'] else t('coords_none', lang)}")
    if site["coords"]:
        st.map(pd.DataFrame({"latitude": [site["coords"][0]], "longitude": [site["coords"][1]]}), size=40)
    else:
        st.caption(t("map_none", lang))


def alerts_tab(ctx):
    lang, b, site = ctx["lang"], ctx["bundle"], ctx["site"]
    events, keys = b.analysis.events, ctx["verified_keys"]
    st.subheader(t("events_heading", lang))
    if not events:
        st.info(t("events_none", lang))
    else:
        rows = []
        for e in reversed(events):
            rows.append({t("col_start", lang): fmt_datetime(e.start, lang), t("col_end", lang): fmt_datetime(e.end, lang),
                         t("col_duration", lang): t("duration_min", lang, n=e.duration_min),
                         t("col_params", lang): ", ".join(("▲ " if e.direction[p] == "up" else "▼ ") + param_label(p, lang) for p in e.params),
                         t("col_strength", lang): t("strength_" + e.strength, lang),
                         t("col_pattern", lang): pattern_text(e, lang),
                         t("col_review", lang): t("review_verified" if e.key in keys else "review_unverified", lang)})
        _table(pd.DataFrame(rows))
        st.caption(t("strength_note", lang))
        st.caption(t("pattern_caution", lang))

    st.markdown(f"#### {t('verify_heading', lang)}")
    st.caption(t("verify_help", lang))
    if ctx["is_demo"]:
        st.info(t("verify_demo_blocked", lang))
    elif not reviews.pin_configured():
        st.info(t("verify_disabled", lang))
    elif not events:
        st.caption(t("no_events_to_verify", lang))
    else:
        ev_labels = {e.key: f"{fmt_datetime(e.start, lang)} · {', '.join(param_label(p, lang) for p in e.params)}" for e in reversed(events)}
        ev_types = {"lab": "ev_lab", "field": "ev_field", "record": "ev_record", "other": "ev_other"}
        with st.form("verify_form", clear_on_submit=True):
            key = st.selectbox(t("verify_event", lang), list(ev_labels), format_func=lambda k: ev_labels[k])
            name = st.text_input(t("verify_name", lang))
            org = st.text_input(t("verify_org", lang))
            etype = st.selectbox(t("verify_evidence_type", lang), list(ev_types), format_func=lambda k: t(ev_types[k], lang))
            note = st.text_area(t("verify_note", lang), max_chars=1000)
            decision = st.selectbox(t("verify_decision", lang), ["verified", "not_confirmed"],
                                    format_func=lambda k: t("dec_" + k, lang))
            pin = st.text_input(t("verify_pin", lang), type="password")
            sent = st.form_submit_button(t("verify_submit", lang))
        if sent:
            code = reviews.record_review(key, site["id"], name, org, etype, note, decision, pin)
            msg = {"saved": ("success", "verify_saved"), "bad_pin": ("error", "verify_bad_pin"),
                   "short_note": ("warning", "verify_short_note"), "disabled": ("info", "verify_disabled"),
                   "invalid": ("warning", "verify_short_note")}[code]
            getattr(st, msg[0])(t(msg[1], lang))
            if code == "saved":
                st.rerun()

    st.markdown(f"#### {t('obs_recent', lang)}")
    obs = observations.load_observations(site["id"], days=30).head(20)
    if obs.empty:
        st.caption(t("obs_none", lang))
    else:
        show = obs.assign(recorded_at=[fmt_datetime(x, lang) for x in obs["recorded_at"]])[["recorded_at", "colour", "smell", "dead_fish", "notes"]]
        show.columns = [t("col_time", lang), t("obs_colour", lang), t("obs_smell", lang), t("obs_fish", lang), t("obs_notes", lang)]
        _table(show)
        st.caption(t("obs_unverified", lang))


def report_tab(ctx):
    lang, b, site, status = ctx["lang"], ctx["bundle"], ctx["site"], ctx["status"]
    st.subheader(t("report_heading", lang))
    st.caption(t("report_help", lang))
    n_obs = len(observations.load_observations(site["id"], days=7))
    latest = b.df.iloc[-1] if len(b.df) else None
    md = reports.build_report(lang, site, ctx["is_demo"], status, latest, b.whi_latest, b.quality, n_obs)
    st.download_button(t("report_download", lang), md.encode("utf-8"), file_name=f"jaldrishti_report_{site['id']}.md",
                       mime="text/markdown")
    with st.expander("Preview", expanded=True):
        st.markdown(md)


def methods_tab(ctx):
    lang = ctx["lang"]
    st.subheader(t("methods_heading", lang))
    st.write(t("methods_version", lang, v=config.METHOD_VERSION))
    st.caption(t("baseline_info", lang, hours=config.BASELINE_HOURS, excl=config.EXCLUSION_HOURS,
                 z=config.Z_THRESHOLD, n=config.PERSIST_N))
    st.markdown(f"#### {t('methods_whi_heading', lang)}")
    st.write(t("methods_whi_body", lang))
    curves = ctx["bundle"].curves
    _table(pd.DataFrame([{t("col_parameter", lang): param_label(p, lang), t("col_weight", lang): f"{w:.3f}",
                          t("methods_curve", lang): " → ".join(f"{x:g}:{y:g}" for x, y in curves[p])}
                         for p, w in config.WHI_WEIGHTS.items()]))
    st.markdown(f'<div class="jd-prov">{c.esc(t("whi_provisional", lang))}</div>', unsafe_allow_html=True)
    st.markdown(f"#### {t('methods_limits_heading', lang)}")
    _table(pd.DataFrame([{t("col_parameter", lang): param_label(p, lang),
                          "min": config.PLAUSIBLE[p][0], "max": config.PLAUSIBLE[p][1], "unit": config.UNITS[p]} for p in config.PARAMS]))
    st.markdown(f"#### {t('report_limitations', lang)}")
    for i in range(1, 8):
        st.markdown(f"- {t(f'lim_{i}', lang)}")
    c.translation_note(lang)
