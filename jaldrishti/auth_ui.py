import os

import streamlit as st

from . import auth, config

# Hindi and Marathi are drafts and need a fluent speaker to check them (same rule as the rest of the app)
TXT = {
    "en": {
        "language": "Language",
        "tab_login": "Log in", "tab_signup": "Create account",
        "email": "Email", "password": "Password", "confirm": "Repeat password", "name": "Your name",
        "role_label": "I am a...",
        "role_consumer": "General user (fisher, local community)",
        "role_government": "Government / authority",
        "role_firm": "Firm / company",
        "org_firm": "Company name", "org_government": "Department / organisation name",
        "gov_code": "Authority access code",
        "water_label": "Type of water body",
        "water_auto": "Auto-detect from TDS (choose this if you are not sure)",
        "water_freshwater": "Freshwater", "water_brackish": "Brackish water", "water_seawater": "Seawater",
        "water_help": "By TDS: freshwater up to about 500 mg/L, brackish about 500 to 30,000 mg/L, seawater above about 30,000 mg/L.",
        "btn_login": "Log in", "btn_signup": "Create account", "logout": "Log out",
        "signed_in": "{name} ({role})",
        "privacy": "Passwords are stored as salted hashes. You are logged out when you close or refresh the page.",
        "err_name": "Please enter your name.", "err_email": "Please enter a valid email address.",
        "err_password": "The password must have at least 8 characters.",
        "err_mismatch": "The two passwords are not the same.", "err_role": "Please choose who you are.",
        "err_org": "Please enter the company or organisation name.",
        "err_exists": "An account with this email already exists.",
        "err_gov_code": "The authority access code is not correct.",
        "err_login": "Email or password is not correct.",
        "err_locked": "Too many wrong attempts. Please try again in a few minutes.",
        "tab_compliance": "Compliance limits", "tab_report": "Report",
        "wt_selected": "Water type: {kind} (your choice)",
        "wt_auto": "Water type: {kind} (auto-detected from TDS, about {tds} mg/L)",
        "wt_none": "Water type: not enough TDS readings yet to auto-detect, so the standard freshwater settings are used.",
        "zone_middle": "typical range", "zone_upper": "upper end of its range",
        "zone_border": "close to the border with {other}",
        "zone_tidal": "TDS swings widely (likely tidal), treated as brackish",
        "wt_mismatch": "TDS (about {tds} mg/L) looks like {data_kind}, not {kind}. Consider choosing auto-detect in Settings.",
    },
    "hi": {
        "language": "भाषा",
        "tab_login": "लॉग इन", "tab_signup": "खाता बनाएँ",
        "email": "ईमेल", "password": "पासवर्ड", "confirm": "पासवर्ड दोबारा लिखें", "name": "आपका नाम",
        "role_label": "आप कौन हैं?",
        "role_consumer": "आम उपयोगकर्ता (मछुआरे, स्थानीय समुदाय)",
        "role_government": "सरकार / प्राधिकरण",
        "role_firm": "कंपनी / फर्म",
        "org_firm": "कंपनी का नाम", "org_government": "विभाग / संस्था का नाम",
        "gov_code": "प्राधिकरण पहुँच कोड",
        "water_label": "पानी का प्रकार",
        "water_auto": "TDS से अपने-आप पहचानें (पता न हो तो यही चुनें)",
        "water_freshwater": "मीठा पानी", "water_brackish": "खारा-मिश्रित (ब्रैकिश) पानी", "water_seawater": "समुद्री पानी",
        "water_help": "TDS के अनुसार: मीठा पानी लगभग 500 mg/L तक, ब्रैकिश लगभग 500 से 30,000 mg/L, समुद्री पानी लगभग 30,000 mg/L से ऊपर।",
        "btn_login": "लॉग इन करें", "btn_signup": "खाता बनाएँ", "logout": "लॉग आउट",
        "signed_in": "{name} ({role})",
        "privacy": "पासवर्ड सुरक्षित रूप (हैश) में रखे जाते हैं। पेज बंद करने या रिफ्रेश करने पर आप लॉग आउट हो जाएँगे।",
        "err_name": "कृपया अपना नाम लिखें।", "err_email": "कृपया सही ईमेल लिखें।",
        "err_password": "पासवर्ड कम से कम 8 अक्षरों का होना चाहिए।",
        "err_mismatch": "दोनों पासवर्ड एक जैसे नहीं हैं।", "err_role": "कृपया अपनी श्रेणी चुनें।",
        "err_org": "कृपया कंपनी या संस्था का नाम लिखें।",
        "err_exists": "इस ईमेल से खाता पहले से है।",
        "err_gov_code": "प्राधिकरण पहुँच कोड सही नहीं है।",
        "err_login": "ईमेल या पासवर्ड गलत है।",
        "err_locked": "बहुत ज़्यादा गलत प्रयास। कुछ मिनट बाद फिर कोशिश करें।",
        "tab_compliance": "अनुपालन सीमाएँ", "tab_report": "रिपोर्ट",
        "wt_selected": "पानी का प्रकार: {kind} (आपकी पसंद)",
        "wt_auto": "पानी का प्रकार: {kind} (TDS लगभग {tds} mg/L से अपने-आप पहचाना)",
        "wt_none": "पानी का प्रकार: अपने-आप पहचानने के लिए अभी TDS रीडिंग पर्याप्त नहीं हैं, इसलिए सामान्य मीठे पानी की सेटिंग लगी है।",
        "zone_middle": "सामान्य दायरा", "zone_upper": "अपने दायरे के ऊपरी सिरे पर",
        "zone_border": "{other} की सीमा के पास",
        "zone_tidal": "TDS बहुत घटता-बढ़ता है (संभवतः ज्वार), ब्रैकिश माना गया",
        "wt_mismatch": "TDS (लगभग {tds} mg/L) {data_kind} जैसा दिखता है, {kind} जैसा नहीं। सेटिंग में अपने-आप पहचानने का विकल्प चुनने पर विचार करें।",
    },
    "mr": {
        "language": "भाषा",
        "tab_login": "लॉग इन", "tab_signup": "खाते तयार करा",
        "email": "ईमेल", "password": "पासवर्ड", "confirm": "पासवर्ड पुन्हा लिहा", "name": "तुमचे नाव",
        "role_label": "तुम्ही कोण आहात?",
        "role_consumer": "सामान्य वापरकर्ता (मच्छीमार, स्थानिक समुदाय)",
        "role_government": "सरकार / प्राधिकरण",
        "role_firm": "कंपनी / फर्म",
        "org_firm": "कंपनीचे नाव", "org_government": "विभाग / संस्थेचे नाव",
        "gov_code": "प्राधिकरण प्रवेश कोड",
        "water_label": "पाण्याचा प्रकार",
        "water_auto": "TDS वरून आपोआप ओळखा (माहीत नसल्यास हे निवडा)",
        "water_freshwater": "गोडे पाणी", "water_brackish": "निमखारे पाणी", "water_seawater": "समुद्राचे पाणी",
        "water_help": "TDS नुसार: गोडे पाणी सुमारे 500 mg/L पर्यंत, निमखारे सुमारे 500 ते 30,000 mg/L, समुद्राचे पाणी सुमारे 30,000 mg/L पेक्षा जास्त.",
        "btn_login": "लॉग इन करा", "btn_signup": "खाते तयार करा", "logout": "लॉग आउट",
        "signed_in": "{name} ({role})",
        "privacy": "पासवर्ड सुरक्षित स्वरूपात (हॅश) साठवले जातात. पेज बंद केल्यावर किंवा रिफ्रेश केल्यावर तुम्ही लॉग आउट व्हाल.",
        "err_name": "कृपया तुमचे नाव लिहा.", "err_email": "कृपया बरोबर ईमेल लिहा.",
        "err_password": "पासवर्ड किमान 8 अक्षरांचा असावा.",
        "err_mismatch": "दोन्ही पासवर्ड सारखे नाहीत.", "err_role": "कृपया तुमची श्रेणी निवडा.",
        "err_org": "कृपया कंपनीचे किंवा संस्थेचे नाव लिहा.",
        "err_exists": "या ईमेलने खाते आधीच आहे.",
        "err_gov_code": "प्राधिकरण प्रवेश कोड चुकीचा आहे.",
        "err_login": "ईमेल किंवा पासवर्ड चुकीचा आहे.",
        "err_locked": "खूप चुकीचे प्रयत्न झाले. काही मिनिटांनी पुन्हा प्रयत्न करा.",
        "tab_compliance": "अनुपालन मर्यादा", "tab_report": "अहवाल",
        "wt_selected": "पाण्याचा प्रकार: {kind} (तुमची निवड)",
        "wt_auto": "पाण्याचा प्रकार: {kind} (TDS सुमारे {tds} mg/L वरून आपोआप ओळखले)",
        "wt_none": "पाण्याचा प्रकार: आपोआप ओळखण्यासाठी अजून पुरेसे TDS रीडिंग नाहीत, म्हणून सामान्य गोड्या पाण्याची सेटिंग वापरली आहे.",
        "zone_middle": "सामान्य मर्यादा", "zone_upper": "मर्यादेच्या वरच्या टोकाजवळ",
        "zone_border": "{other} च्या सीमेजवळ",
        "zone_tidal": "TDS खूप वर-खाली होते (बहुधा भरती-ओहोटी), निमखारे मानले",
        "wt_mismatch": "TDS (सुमारे {tds} mg/L) {data_kind} सारखे दिसते, {kind} सारखे नाही. सेटिंगमध्ये आपोआप ओळखण्याचा पर्याय निवडण्याचा विचार करा.",
    },
}

ROLE_TO_MODE = {"consumer": "community", "government": "technical", "firm": "firm"}


def tx(key, lang, **kw):
    s = TXT.get(lang, TXT["en"]).get(key) or TXT["en"][key]
    return s.format(**kw) if kw else s


def current_user():
    return st.session_state.get("user")


def login_user(user):
    st.session_state["user"] = user
    st.session_state["mode_key"] = ROLE_TO_MODE[user["role"]]


def logout():
    for k in list(st.session_state.keys()):
        if k == "user" or k.startswith("fr_") or k.startswith("gate_"):
            del st.session_state[k]


def allowed_modes(user):
    if os.getenv("JALDRISHTI_ALLOW_ALL_VIEWS", "") == "1":
        return ["community", "technical", "firm"]
    return [ROLE_TO_MODE[user["role"]]]


def water_label(pref, lang):
    return tx("water_" + pref, lang)


def gate(lang):
    # login / sign-up page. Shown instead of the app until someone is logged in
    c_brand, c_lang = st.columns([6, 2])
    with c_brand:
        try:
            from .ui import components as c
            c.brand(lang)
        except Exception:
            st.title("JalDrishti")
    with c_lang:
        lang = st.selectbox(tx("language", lang), list(config.LANGUAGES), format_func=config.LANGUAGES.get, key="lang_code")
    tab_in, tab_up = st.tabs([tx("tab_login", lang), tx("tab_signup", lang)])
    with tab_in:
        with st.form("gate_login"):
            email = st.text_input(tx("email", lang), key="gate_login_email")
            pw = st.text_input(tx("password", lang), type="password", key="gate_login_pw")
            go = st.form_submit_button(tx("btn_login", lang), type="primary")
        if go:
            user, err = auth.authenticate(email, pw)
            if err:
                st.error(tx(err, lang))
            else:
                login_user(user)
                st.rerun()
    with tab_up:
        name = st.text_input(tx("name", lang), key="gate_name")
        email = st.text_input(tx("email", lang), key="gate_email")
        c1, c2 = st.columns(2)
        pw = c1.text_input(tx("password", lang), type="password", key="gate_pw")
        pw2 = c2.text_input(tx("confirm", lang), type="password", key="gate_pw2")
        role = st.radio(tx("role_label", lang), auth.ROLES, key="gate_role", format_func=lambda r: tx("role_" + r, lang))
        org = ""
        if role in ("firm", "government"):
            org = st.text_input(tx("org_" + role, lang), key="gate_org")
        code = ""
        if role == "government" and auth.gov_code_needed():
            code = st.text_input(tx("gov_code", lang), type="password", key="gate_code")
        wt = st.selectbox(tx("water_label", lang), auth.WATER_PREFS, key="gate_water", format_func=lambda k: water_label(k, lang))
        st.caption(tx("water_help", lang))
        if st.button(tx("btn_signup", lang), type="primary", key="gate_signup"):
            user, err = auth.create_user(email, name, pw, pw2, role, org, wt, code)
            if err:
                st.error(tx(err, lang))
            else:
                login_user(user)
                st.rerun()
        st.caption(tx("privacy", lang))
    return lang


def account_chip(user, lang):
    st.caption(tx("signed_in", lang, name=user["name"], role=tx("role_" + user["role"], lang)))
    if st.button(tx("logout", lang), key="logout_btn"):
        logout()
        st.rerun()


def water_type_setting(user, lang):
    cur = user.get("water_type", "auto")
    new = st.selectbox(tx("water_label", lang), auth.WATER_PREFS, index=auth.WATER_PREFS.index(cur), key="set_water",
                       format_func=lambda k: water_label(k, lang))
    if new != cur:
        auth.set_water_type(user["email"], new)
        st.session_state["user"] = dict(user, water_type=new)
    st.caption(tx("water_help", lang))


def water_banner(res, lang):
    # shows which water type the app is using and why
    if res.kind is None:
        st.caption(tx("wt_none", lang))
        return
    kind = water_label(res.kind, lang)
    tds = "{:,.0f}".format(res.tds_median) if res.tds_median else "?"
    head = tx("wt_auto", lang, kind=kind, tds=tds) if res.source == "auto" else tx("wt_selected", lang, kind=kind)
    zone = ""
    if res.zone in ("middle", "upper", "tidal"):
        zone = tx("zone_" + res.zone, lang)
    elif res.zone == "border":
        zone = tx("zone_border", lang, other=water_label(res.other, lang) if res.other else "-")
    st.caption(head + (" - " + zone if zone else ""))
    if res.mismatch:
        st.warning(tx("wt_mismatch", lang, tds=tds, data_kind=water_label(res.data_kind, lang), kind=kind))
