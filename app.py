"""JalDrishti - run with: streamlit run app.py"""
from pathlib import Path

import streamlit as st

# The update files must be copied INTO your original JalDrishti project folder, on top of the old files.
# If some files are missing, say so here instead of crashing with an import error.
_HERE = Path(__file__).resolve().parent
_OLD = ["__init__.py", "config.py", "alerts.py", "validation.py", "data_store.py", "demo_data.py", "i18n.py",
        "ui/community.py", "ui/components.py", "ui/data_access.py", "ui/firm.py", "ui/styles.py", "ui/technical.py"]
_NEW = ["auth.py", "auth_ui.py", "water_types.py", "standards.py", "insights.py", "insights_report.py", "company.py", "advice.py",
        "report_build.py", "report_out.py", "ui/whi_panel.py", "ui/report_tab.py"]
_lost_old = ["jaldrishti/" + f for f in _OLD if not (_HERE / "jaldrishti" / f).exists()]
if not (_HERE / "assets" / "favicon.png").exists():
    _lost_old.append("assets/favicon.png")
_lost_new = ["jaldrishti/" + f for f in _NEW if not (_HERE / "jaldrishti" / f).exists()]
if _lost_old or _lost_new:
    st.set_page_config(page_title="JalDrishti - setup", layout="centered")
    st.title("Some JalDrishti files are missing")
    st.write("This app is running from: " + str(_HERE))
    if _lost_old:
        st.error("Files from your ORIGINAL JalDrishti project are not in this folder:\n\n- " + "\n- ".join(_lost_old))
        st.write("The update is not a full app. Copy its files INTO your original JalDrishti project folder "
                 "(the one that already has jaldrishti/config.py), say yes to replace app.py, and run the app from there.")
    if _lost_new:
        st.error("Files from the update are not in this folder:\n\n- " + "\n- ".join(_lost_new))
        st.write("Copy the jaldrishti and tests folders from the update into the project folder as well.")
    st.stop()

from PIL import Image
from jaldrishti import auth, auth_ui, config, data_store, demo_data, water_types
from jaldrishti.i18n import t
from jaldrishti.ui import community, components as c, data_access as da, firm, report_tab, technical, whi_panel
from jaldrishti.ui.styles import CSS
st.set_page_config(page_title="JalDrishti", page_icon=Image.open(config.ROOT / "assets" / "favicon.png"),
                   layout="wide", initial_sidebar_state="collapsed")
st.markdown(CSS, unsafe_allow_html=True)
auth.init()
water_types.prepare_config()
has_local = config.RAW_READINGS_PATH.exists() and config.RAW_READINGS_PATH.stat().st_size > 0
st.session_state.setdefault("lang_code", "en")
st.session_state.setdefault("mode_key", "community")
st.session_state.setdefault("source", "local" if has_local else "demo")
st.session_state.setdefault("scenario", "normal")
lang = st.session_state["lang_code"]

# nobody gets past this point without logging in
user = auth_ui.current_user()
if user is None:
    auth_ui.gate(lang)
    c.footer(st.session_state["lang_code"])
    st.stop()
allowed = auth_ui.allowed_modes(user)
if st.session_state["mode_key"] not in allowed:
    st.session_state["mode_key"] = allowed[0]

c_brand, c_lang, c_mode = st.columns([5, 2, 4])
with c_brand:
    c.brand(lang)
with c_lang:
    lang = st.selectbox(t("language", lang), list(config.LANGUAGES), format_func=config.LANGUAGES.get, key="lang_code")
with c_mode:
    if len(allowed) > 1:
        mode = st.radio(t("view_mode", lang), allowed, horizontal=True, key="mode_key",
                        format_func=lambda k: t("mode_" + k, lang))
    else:
        mode = allowed[0]
    auth_ui.account_chip(user, lang)
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
    auth_ui.water_type_setting(user, lang)
    if st.button(t("refresh", lang)):
        st.cache_data.clear()
        st.rerun()
user = auth_ui.current_user()
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
# pick the water type (the user's choice, or auto from TDS) and set the app limits and curves for it
wt = water_types.resolve(user.get("water_type", "auto"), bundle.df)
if water_types.apply_calibration(wt):
    st.cache_data.clear()
    bundle = da.bundle_for(source, scenario, site_id, stamp)
status, verified_keys = da.with_verification(bundle.analysis, site_id)
ctx = {"lang": lang, "technical": mode == "technical", "site": site, "is_demo": is_demo, "bundle": bundle,
       "status": status, "verified_keys": verified_keys, "calibration": data_store.load_calibration(), "water_type": wt}
auth_ui.water_banner(wt, lang)
if not bundle.df.empty:
    whi_panel.render(ctx, mode, user)      # colour-coded Water Health Index (CPCB and BIS limits) for all three audiences
if bundle.df.empty:
    st.subheader(t("empty_title", lang))
    st.info(t("empty_body", lang, path=str(config.RAW_READINGS_PATH)))
elif mode == "community":
    community.render(ctx)
elif mode == "firm":
    tab_limits, tab_report = st.tabs([auth_ui.tx("tab_compliance", lang), auth_ui.tx("tab_report", lang)])
    with tab_limits:
        firm.render(ctx)
    with tab_report:
        report_tab.render(ctx, user)
else:
    technical.render(ctx)
c.footer(lang)
