"""Reusable HTML/Streamlit pieces shared by the community and technical views."""
import base64
import html
import json
import streamlit as st
import streamlit.components.v1 as components
from .. import config
from ..alerts import vs_usual
from ..explain import status_label, reason_text, issues_text, speech_summary
from ..i18n import t, param_label, fmt_with_unit, fmt_datetime, fmt_relative

ICON = {"normal": "✓", "investigate": "▲", "verified": "◆", "unavailable": "■"}
def esc(s):
    return html.escape(str(s))


ASSETS = config.ROOT / "assets"


@st.cache_resource
def _b64(name):
    return base64.b64encode((ASSETS / name).read_bytes()).decode("ascii")


def brand(lang):
    st.markdown(
        f'<div class="jd-brand"><img class="jd-mark" alt="" src="data:image/png;base64,{_b64("logo_mark.png")}">'
        f'<div class="jd-words"><div class="jd-wordmark" aria-label="JalDrishti"><span class="jd-latin">JAL</span>'
        f'<span class="jd-deva">दृष्टि</span></div><div class="jd-tagline">WAVES OF INSIGHT</div>'
        f'<div class="jd-tag2">{esc(t("tagline", lang))}</div></div></div>', unsafe_allow_html=True)


def logo_card():
    st.markdown(f'<div class="jd-logo-card"><img alt="JalDrishti - Waves of Insight" src="data:image/png;base64,{_b64("logo_full.png")}"></div>',
                unsafe_allow_html=True)


def demo_banner(lang):
    st.markdown(f'<div class="jd-demo" role="note">{esc(t("demo_banner", lang))}</div>', unsafe_allow_html=True)


def status_banner(status, lang, technical=False):
    state = status.state
    label = status_label(state, lang, technical)
    meta = f'{t("last_update", lang)}: {fmt_datetime(status.latest_time, lang)} ({fmt_relative(status.age_minutes, lang)})'
    extra = issues_text(status, lang)
    extra_html = f'<div class="jd-reason jd-warn">⚠ {esc(extra)}</div>' if extra else ""
    st.markdown(
        f'<div class="jd-card jd-status jd-s-{state}" role="status"><div class="jd-icon" aria-hidden="true">{ICON[state]}</div>'
        f'<div><div class="jd-label">{esc(label)}</div><div class="jd-reason">{esc(reason_text(status, lang))}</div>'
        f'{extra_html}<div class="jd-meta">{esc(meta)}</div></div></div>', unsafe_allow_html=True)


def sensor_cards(latest, lang, sig=None, big=False, explain=False):
    cards = []
    for p in config.PARAMS:
        flag = latest[f"{p}_flag"] if latest is not None else "missing"
        val = latest[p] if latest is not None else None
        shown = fmt_with_unit(val, p) if flag == "ok" else "—"
        number, _, unit = shown.partition(" ")
        sub = ""
        if flag != "ok":
            sub = f'<div class="jd-sub jd-warn">⚠ {esc(t("flag_" + flag, lang))}</div>'
        elif sig is not None:
            v = vs_usual(sig, p)
            mark, cls = {"higher": ("▲", "jd-warn"), "lower": ("▼", "jd-warn"), "similar": ("●", "jd-ok"), "unknown": ("○", "jd-note")}[v]
            sub = f'<div class="jd-sub {cls}">{mark} {esc(t("vs_usual_" + v, lang))}</div>'
        exp = f'<div class="jd-exp">{esc(t("explain_" + p, lang))}</div>' if explain else ""
        cards.append(f'<div class="jd-card jd-sensor"><div class="jd-sname">{esc(param_label(p, lang))}</div>'
                     f'<div class="jd-val">{esc(number)}<span class="jd-unit">{esc(unit)}</span></div>{sub}{exp}</div>')
    cls = "jd-grid jd-grid-big" if big else "jd-grid"
    st.markdown(f'<div class="{cls}">{"".join(cards)}</div>', unsafe_allow_html=True)


def _embed(html_text, height):
    if hasattr(st, "iframe"):          # newer Streamlit
        st.iframe(html_text, height=height)
    else:
        components.html(html_text, height=height)


def listen_button(status, lang):
    text = speech_summary(status, lang)
    payload = {"text": text, "lang": config.TTS_LANG[lang], "unsupported": t("listen_unsupported", lang),
               "novoice": t("listen_no_voice", lang)}
    _embed(f"""
<button id="b" style="font:600 15px Inter,Segoe UI,Arial,sans-serif;padding:10px 16px;border-radius:8px;border:2px solid #0f766e;background:#fff;color:#0f766e;cursor:pointer" aria-label="{esc(t('listen', lang))}">🔊 {esc(t('listen', lang))}</button>
<span id="m" style="font:14px Arial;color:#51606f;margin-left:10px"></span>
<script>
const P = {json.dumps(payload).replace('</', '<' + chr(92) + '/')};
document.getElementById('b').onclick = () => {{
  const m = document.getElementById('m'); m.textContent = '';
  if (!('speechSynthesis' in window)) {{ m.textContent = P.unsupported; return; }}
  const base = P.lang.split('-')[0].toLowerCase();
  const voices = speechSynthesis.getVoices();
  if (voices.length && !voices.some(v => v.lang.toLowerCase().startsWith(base))) {{ m.textContent = P.novoice; return; }}
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(P.text); u.lang = P.lang; speechSynthesis.speak(u);
}};
</script>""", 56)


def translation_note(lang):
    if not config.TRANSLATIONS_REVIEWED.get(lang, True):
        st.caption("ℹ " + t("translation_review", lang))


def footer(lang):
    st.markdown(f'<div class="jd-footer">{esc(t("footer", lang))}</div>', unsafe_allow_html=True)
