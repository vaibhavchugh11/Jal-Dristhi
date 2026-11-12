"""Translation lookup and locale-aware formatting. Missing keys fall back to English."""
import math
import pandas as pd
from . import config
from .translations import STRINGS


class _Safe(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def t(key, lang="en", **kw):
    text = STRINGS.get(lang, {}).get(key)
    if text is None:
        text = STRINGS["en"].get(key, key)
    if isinstance(text, str) and kw:
        return text.format_map(_Safe(**kw))
    return text


def param_label(param, lang):
    return t(f"sensor_{param}", lang)


def to_local(ts):
    ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert(config.DISPLAY_TZ)


def fmt_datetime(ts, lang):
    if ts is None or pd.isna(ts):
        return t("no_reading", lang)
    ts = to_local(ts)
    month = t("months_short", lang)[ts.month - 1]
    return f"{ts.day} {month} {ts.year}, {ts.hour:02d}:{ts.minute:02d}"


def fmt_relative(minutes, lang):
    if minutes is None or (isinstance(minutes, float) and math.isnan(minutes)):
        return t("no_reading", lang)
    m = max(0, int(minutes))
    if m < 1:
        return t("just_now", lang)
    if m < 60:
        return t("min_ago", lang, n=m)
    if m < 60 * 48:
        return t("hr_ago", lang, n=m // 60)
    return t("day_ago", lang, n=m // 1440)


def fmt_value(value, param):
    if value is None or pd.isna(value):
        return "—"
    return f"{value:.{config.DECIMALS[param]}f}"


def fmt_with_unit(value, param):
    unit = config.UNITS[param]
    v = fmt_value(value, param)
    return f"{v} {unit}".strip() if v != "—" else v
