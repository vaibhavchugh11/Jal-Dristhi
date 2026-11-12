"""Plain-language wording for statuses, reasons, next steps and spoken summaries."""
from . import config
from .i18n import t, param_label, fmt_relative


def status_label(state, lang, technical=False):
    if state == "normal":
        return t("status_normal", lang)
    if state == "unavailable":
        return t("status_unavailable", lang)
    if state == "verified":
        return t("status_verified", lang) if technical else t("status_unusual", lang)
    return t("status_investigate" if technical else "status_unusual", lang)


def params_text(params, lang):
    return ", ".join(param_label(p, lang) for p in params)


def reason_text(status, lang):
    r = status.reason
    if r == "ok":
        return t("reason_ok", lang)
    if r in ("unusual", "verified"):
        text = t("reason_unusual", lang, params=params_text([f.param for f in status.findings], lang))
        return text + (" " + t("reason_verified", lang) if r == "verified" else "")
    if r == "stale":
        return t("reason_stale", lang, age=fmt_relative(status.age_minutes, lang))
    key = {"no_data": "reason_no_data", "unreliable": "reason_unreliable",
           "insufficient_baseline": "reason_insufficient_baseline"}[r]
    return t(key, lang)


def issues_text(status, lang):
    if not status.sensor_issues:
        return ""
    return t("sensor_issues_note", lang, params=params_text(list(status.sensor_issues), lang))


def next_steps(status, lang):
    if status.state in ("investigate", "verified"):
        keys = ["next_check_water", "next_avoid_contact", "next_inform", "next_confirm", "next_equipment"]
    elif status.state == "unavailable" or status.sensor_issues:
        keys = ["next_equipment"]
    else:
        keys = []
    return [t(k, lang) for k in keys]


def speech_summary(status, lang):
    parts = [t("speech_status", lang, status=status_label(status.state, lang))]
    if status.age_minutes is not None:
        parts.append(t("speech_updated", lang, age=fmt_relative(status.age_minutes, lang)))
    parts.append(reason_text(status, lang))
    parts.append(t("speech_disclaimer", lang))
    return " ".join(parts)


def pattern_key(event):
    """Describes how readings moved during an event. Never names a cause or a pollutant."""
    d = event.direction
    turb, tds = d.get("turbidity"), d.get("tds")
    if turb == "up" and tds == "up":
        return "pattern_turb_tds_up"
    if turb == "up" and tds == "down":
        return "pattern_turb_up_tds_down"
    if turb == "up":
        return "pattern_turb_up"
    if d.get("do") == "down":
        return "pattern_do_down"
    if "ph" in d:
        return "pattern_ph"
    return "pattern_generic"


def pattern_text(event, lang):
    return t(pattern_key(event), lang)
