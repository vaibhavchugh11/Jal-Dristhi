"""JalDrishti - run with: streamlit run app.py"""
import streamlit as st
from PIL import Image

from jaldrishti import config, data_store, demo_data
from jaldrishti.i18n import t
from jaldrishti.ui import community, components as c, data_access as da, firm, technical
from jaldrishti.ui.styles import CSS

st.set_page_config(page_title="JalDrishti", page_icon=Image.open(config.ROOT / "assets" / "favicon.png"),
                   layout="wide", initial_sidebar_state="collapsed")
st.markdown(CSS, unsafe_allow_html=True)

has_local = config.RAW_READINGS_PATH.exists() and config.RAW_READINGS_PATH.stat().st_size > 0
st.session_state.setdefault("lang_code", "en")
st.session_state.setdefault("mode_key", "community")
st.session_state.setdefault("source", "local" if has_local else "demo")
st.session_state.setdefault("scenario", "normal")

lang = st.session_state["lang_code"]
c_brand, c_lang, c_mode = st.columns([5, 2, 4])
with c_brand:
    c.brand(lang)
with c_lang:
    lang = st.selectbox(t("language", lang), list(config.LANGUAGES), format_func=config.LANGUAGES.get, key="lang_code")
with c_mode:
    mode = st.radio(t("view_mode", lang), ["community", "technical", "firm"], horizontal=True, key="mode_key",
                    format_func=lambda k: t("mode_" + k, lang))

# settings live in the page (not the sidebar) so they are easy to reach on a phone
with st.expander("⚙ " + t("sidebar_heading", lang)):
    source = st.radio(t("data_source", lang), ["local", "demo"], key="source", horizontal=True,
                      format_func=lambda k: t("source_local" if k == "local" else "source_demo", lang))
    scenario = st.session_state["scenario"]
    if source == "demo":
        scenario = st.selectbox(t("demo_scenario", lang), demo_data.SCENARIOS, key="scenario",
                                format_func=lambda k: t("scenario_" + k, lang))
    stamp = da.data_stamp()
    sites = da.sites_for(source, scenario, stamp)
    site_id = None
    if sites:
        site_id = st.selectbox(t("site", lang), [s["id"] for s in sites],
                               format_func=lambda i: next(s["name"] for s in sites if s["id"] == i))
    if st.button(t("refresh", lang)):
        st.cache_data.clear()
        st.rerun()

if not sites:
    c.logo_card()
    st.subheader(t("empty_title", lang))
    st.info(t("empty_body", lang, path=str(config.RAW_READINGS_PATH)))
    st.button(t("source_demo", lang), on_click=lambda: st.session_state.update(source="demo"))
    c.footer(lang)
    st.stop()

site = next(s for s in sites if s["id"] == site_id)
is_demo = source == "demo" or demo_data.is_demo_id(site_id)
if is_demo:
    c.demo_banner(lang)
st.caption(f"{t('site', lang)}: {site['name']}")

try:
    bundle = da.bundle_for(source, scenario, site_id, stamp)
except Exception as e:   # unreadable file etc.
    st.error(t("err_data", lang, err=str(e)))
    st.stop()

status, verified_keys = da.with_verification(bundle.analysis, site_id)
ctx = {"lang": lang, "technical": mode == "technical", "site": site, "is_demo": is_demo, "bundle": bundle,
       "status": status, "verified_keys": verified_keys, "calibration": data_store.load_calibration()}

if bundle.df.empty:
    st.subheader(t("empty_title", lang))
    st.info(t("empty_body", lang, path=str(config.RAW_READINGS_PATH)))
elif mode == "community":
    community.render(ctx)
elif mode == "firm":
    firm.render(ctx)
else:
    technical.render(ctx)
c.footer(lang)
