"""Community mode: large readable cards, plain language, cautious wording."""
import streamlit as st
from .. import config, observations
from ..charts import param_figure
from ..explain import next_steps, params_text
from ..i18n import t, param_label, fmt_datetime
from . import components as c
from .data_view import render as data_tab


def render(ctx):
    lang, b = ctx["lang"], ctx["bundle"]
    status = ctx["status"]
    low = st.checkbox(t("low_data", lang), key="low_data")
    tab_now, tab_trends, tab_data, tab_learn, tab_obs = st.tabs(
        [t("tab_now", lang), t("tab_trends", lang), t("tab_data", lang), t("tab_learn", lang), t("tab_observations", lang)])

    with tab_now:
        st.subheader(t("now_heading", lang))
        c.status_banner(status, lang)
        c.listen_button(status, lang)
        st.markdown(f"#### {t('readings_heading', lang)}")
        latest = b.df.iloc[-1] if len(b.df) else None
        c.sensor_cards(latest, lang, sig=b.analysis.signals, big=True, explain=True)
        if status.findings:
            with st.expander(t("why_flagged", lang), expanded=True):
                st.write(t("why_flagged_body", lang, params=params_text([f.param for f in status.findings], lang)))
                if any(f.param == "turbidity" for f in status.findings):
                    st.info(t("turbidity_note", lang))
        steps = next_steps(status, lang)
        if steps:
            st.markdown(f"#### {t('next_steps', lang)}")
            for s in steps:
                st.markdown(f"- {s}")
        coords = ctx["site"].get("coords")
        if coords and not low:
            import pandas as pd
            st.map(pd.DataFrame({"latitude": [coords[0]], "longitude": [coords[1]]}), size=40)

    with tab_trends:
        st.markdown(f"#### {t('trend_heading', lang)}")
        if low:
            st.caption(t("low_data", lang))
        else:
            p = st.selectbox(t("pick_parameter", lang), config.PARAMS, format_func=lambda k: param_label(k, lang), key="comm_param")
            recent = b.df[b.df["timestamp"] > b.df["timestamp"].max() - __import__("pandas").Timedelta(hours=24)] if len(b.df) else b.df
            if len(recent):
                st.plotly_chart(param_figure(lang, recent, p, sig=b.analysis.signals, show_baseline=True, height=300),
                                width="stretch", config={"displayModeBar": False})
            else:
                st.info(t("no_rows", lang))

    with tab_data:
        data_tab(ctx)

    with tab_learn:
        st.subheader(t("learn_heading", lang))
        for p in config.PARAMS:
            st.markdown(f"**{param_label(p, lang)}** — {t('explain_' + p, lang)}")
        st.info(t("turbidity_note", lang))
        st.write(t("learn_limits", lang))
        st.write(t("learn_flag_meaning", lang))
        c.translation_note(lang)

    with tab_obs:
        render_observations(ctx)


def render_observations(ctx):
    lang, site = ctx["lang"], ctx["site"]
    st.subheader(t("obs_heading", lang))
    st.caption(t("obs_help", lang))
    colours = {"normal": "obs_colour_normal", "brown": "obs_colour_brown", "green": "obs_colour_green", "other": "obs_colour_other"}
    with st.form("obs_form", clear_on_submit=True):
        colour = st.selectbox(t("obs_colour", lang), list(colours), format_func=lambda k: t(colours[k], lang))
        smell = st.selectbox(t("obs_smell", lang), ["none", "unusual"], format_func=lambda k: t("obs_smell_" + k, lang))
        fish = st.selectbox(t("obs_fish", lang), ["none", "seen"], format_func=lambda k: t("obs_fish_" + k, lang))
        notes = st.text_area(t("obs_notes", lang), max_chars=500)
        sent = st.form_submit_button(t("obs_submit", lang))
    if sent:
        if ctx["is_demo"]:
            st.warning(t("obs_demo_blocked", lang))
        else:
            observations.add_observation(site["id"], colour, smell, fish, notes)
            st.success(t("obs_saved", lang))
    st.markdown(f"#### {t('obs_recent', lang)}")
    obs = observations.load_observations(site["id"]).head(10)
    if obs.empty:
        st.caption(t("obs_none", lang))
    for _, r in obs.iterrows():
        st.markdown(f"- **{fmt_datetime(r['recorded_at'], lang)}** · {t(colours.get(r['colour'], 'obs_colour_other'), lang)} · "
                    f"{t('obs_smell_' + r['smell'], lang) if r['smell'] in ('none', 'unusual') else ''} · "
                    f"{t('obs_fish_' + r['dead_fish'], lang) if r['dead_fish'] in ('none', 'seen') else ''}  \n"
                    f"  {r['notes']}  \n  _{t('obs_unverified', lang)}_")
