"""Firms / Compliance view: a company enters its own limits and the buoy readings are screened against them."""
import pandas as pd
import streamlit as st
from .. import compliance, compliance_report as cr, config
from ..charts import limit_figure
from ..i18n import t, param_label, fmt_with_unit
from . import components as c
from .data_view import render as data_tab

NEW = "__new__"
PERIOD_HOURS = [24, 168, 336]


def render(ctx):
    lang = ctx["lang"]
    st.markdown(f'<div class="jd-prov" role="note">{c.esc(t("firm_disclaimer", lang))}</div>', unsafe_allow_html=True)
    if ctx["is_demo"]:
        st.caption(t("firm_demo_note", lang))
    profiles = compliance.load_profiles()
    ids = [NEW] + list(profiles)
    if "firm_profile_next" in st.session_state:
        st.session_state["firm_profile"] = st.session_state.pop("firm_profile_next")
    if st.session_state.get("firm_profile") not in ids:
        st.session_state["firm_profile"] = NEW
    sel = st.selectbox(t("firm_select", lang), ids, key="firm_profile",
                       format_func=lambda i: t("firm_new", lang) if i == NEW else profiles[i]["name"])
    tabs = st.tabs([t("tab_firm_limits", lang), t("tab_firm_screening", lang), t("tab_data", lang), t("tab_firm_report", lang)])
    with tabs[0]:
        limits_tab(ctx, profiles, sel)
    result = None
    if sel != NEW and sel in profiles:
        b = ctx["bundle"]
        result = compliance.evaluate(b.df, profiles[sel]["limits"], st.session_state.get("firm_period", 168),
                                     b.analysis.signals.cadence, b.analysis.events)
    with tabs[1]:
        screening_tab(ctx, result)
    with tabs[2]:
        data_tab(ctx)
    with tabs[3]:
        report_tab(ctx, profiles, sel, result)


def _num(v):
    return "" if v is None else f"{v:g}"


def limits_tab(ctx, profiles, sel):
    lang = ctx["lang"]
    prof = profiles.get(sel, {"name": "", "relation": "", "notes": "", "limits": {}})
    st.subheader(t("firm_profile", lang))
    with st.form(f"firm_form_{sel}"):
        name = st.text_input(t("firm_name", lang), value=prof["name"], max_chars=80)
        relation = st.text_input(t("firm_relation", lang), value=prof.get("relation", ""), max_chars=200)
        notes = st.text_area(t("firm_notes", lang), value=prof.get("notes", ""), max_chars=500)
        st.markdown(f"#### {t('firm_limits_heading', lang)}")
        st.caption(t("firm_limits_help", lang))
        form = {}
        for p in config.PARAMS:
            lim = prof["limits"].get(p, {})
            unit = f" ({config.UNITS[p]})" if config.UNITS[p] else ""
            with st.expander(param_label(p, lang) + unit, expanded=bool(lim)):
                c1, c2, c3 = st.columns(3)
                mn = c1.text_input(t("firm_min", lang), value=_num(lim.get("min")), key=f"{sel}_{p}_min")
                mx = c2.text_input(t("firm_max", lang), value=_num(lim.get("max")), key=f"{sel}_{p}_max")
                basis = c3.selectbox(t("firm_basis", lang), compliance.BASES, key=f"{sel}_{p}_basis",
                                     index=compliance.BASES.index(lim.get("basis", "instant")),
                                     format_func=lambda b: t("basis_" + b, lang))
                ref = st.text_input(t("firm_reference", lang), value=lim.get("reference", ""), max_chars=200, key=f"{sel}_{p}_ref")
            form[p] = {"min": mn, "max": mx, "basis": basis, "reference": ref}
        sent = st.form_submit_button(t("firm_save", lang))
    if sent:
        limits, errors = compliance.parse_limits(form)
        if not name.strip():
            errors.insert(0, ("name", None, None))
        if errors:
            for code, p, extra in errors:
                label = param_label(p, lang) if p else ""
                if code == "name":
                    st.error(t("firm_err_name", lang))
                elif code == "range":
                    st.error(t("firm_err_range", lang, param=label, lo=extra[0], hi=extra[1]))
                else:
                    key = {"number": "firm_err_number", "minmax": "firm_err_minmax", "none": "firm_err_none"}[code]
                    st.error(t(key, lang, param=label))
        else:
            pid = compliance.save_profile(name, ctx["site"]["id"], relation, notes, limits)
            st.session_state["firm_profile_next"] = pid
            st.session_state["firm_flash"] = "firm_saved"
            st.rerun()
    if st.session_state.get("firm_flash"):
        st.success(t(st.session_state.pop("firm_flash"), lang))
    if sel != NEW and sel in profiles and st.button(t("firm_delete", lang)):
        compliance.delete_profile(sel)
        st.session_state["firm_profile_next"] = NEW
        st.session_state["firm_flash"] = "firm_deleted"
        st.rerun()


def _banner(result, lang):
    cls = {"outside": "investigate", "near": "investigate", "within": "normal"}.get(result.overall, "unavailable")
    icon = {"outside": "▲", "near": "◐", "within": "✓"}.get(result.overall, "■")
    extra = ""
    if result.counts:
        summary = t("firm_summary", lang, out=result.counts["outside"], near=result.counts["near"],
                    within=result.counts["within"], nodata=result.counts["nodata"])
        extra = f'<div class="jd-meta">{c.esc(summary)}</div>'
    label = t(cr.OVERALL_KEY[result.overall], lang)
    st.markdown(f'<div class="jd-card jd-status jd-s-{cls}" role="status"><div class="jd-icon" aria-hidden="true">{icon}</div>'
                f'<div><div class="jd-label">{c.esc(label)}</div>{extra}</div></div>', unsafe_allow_html=True)


def screening_tab(ctx, result):
    lang, b = ctx["lang"], ctx["bundle"]
    st.subheader(t("firm_status_heading", lang))
    if result is None:
        st.info(t("firm_no_profile", lang))
        return
    st.selectbox(t("firm_period", lang), PERIOD_HOURS, index=1, key="firm_period",
                 format_func=lambda h: cr.period_label(h, lang))
    st.caption(t("firm_site_note", lang, site=ctx["site"]["name"]))
    _banner(result, lang)
    latest = b.df.iloc[-1] if len(b.df) else None
    c.sensor_cards(latest, lang)

    rows = []
    for p in config.PARAMS:
        pr = result.params.get(p)
        if pr is None:
            continue
        rows.append({t("col_parameter", lang): param_label(p, lang), t("col_limit", lang): cr.limit_text(pr.limit, p, lang),
                     t("col_latest", lang): fmt_with_unit(pr.latest, p),
                     t("col_status", lang): f"{cr.STATUS_ICON[pr.status]} {t('st_' + pr.status, lang)}",
                     t("col_pct_outside", lang): f"{pr.pct_outside:.1f}%", t("col_episodes", lang): len(pr.episodes),
                     t("col_longest", lang): cr.fmt_duration(pr.longest_min, lang) if pr.episodes else "—",
                     t("col_peak", lang): fmt_with_unit(pr.peak, p) if pr.episodes else "—"})
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    ins = cr.insights(result, lang)
    if ins:
        st.markdown(f"#### {t('firm_insights', lang)}")
        for line in ins:
            st.markdown(f"- {line}")
    acts = cr.action_list(result, lang)
    if acts:
        st.markdown(f"#### {t('next_steps', lang)}")
        for a in acts:
            st.markdown(f"- {a}")

    plottable = [p for p in config.PARAMS if p in result.params and len(b.df)]
    if plottable:
        p = st.selectbox(t("firm_chart_pick", lang), plottable, format_func=lambda k: param_label(k, lang), key="firm_plot")
        window = b.df[b.df["timestamp"] > b.df["timestamp"].max() - pd.Timedelta(hours=result.period_hours)]
        st.plotly_chart(limit_figure(lang, window, p, result.params[p].limit, result.params[p].episodes),
                        width="stretch", config={"displayModeBar": False}, key="firm_chart")
    eps = cr.episodes_frame(result, lang)
    if eps.empty:
        st.caption(t("firm_no_episodes", lang))
    else:
        st.dataframe(eps, hide_index=True, width="stretch")


def report_tab(ctx, profiles, sel, result):
    lang = ctx["lang"]
    st.subheader(t("firm_report_heading", lang))
    st.caption(t("firm_report_help", lang))
    if result is None:
        st.info(t("firm_no_profile", lang))
        return
    md = cr.build_report(lang, profiles[sel], ctx["site"], result, ctx["is_demo"])
    c1, c2 = st.columns(2)
    c1.download_button(t("firm_report_download", lang), md.encode("utf-8"), file_name=f"jaldrishti_compliance_{sel}.md", mime="text/markdown")
    eps = cr.episodes_frame(result, lang)
    c2.download_button(t("firm_episodes_download", lang), eps.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"jaldrishti_periods_outside_{sel}.csv", mime="text/csv", disabled=eps.empty)
    with st.expander("Preview", expanded=True):
        st.markdown(md)
