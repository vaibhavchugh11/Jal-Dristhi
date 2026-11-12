"""The data table tab, shared by the community, government and firm views."""
import pandas as pd
import streamlit as st
from .. import config
from ..i18n import t, param_label, fmt_value


def date_filter(df, lang, key):
    if df.empty:
        return df
    local = pd.DatetimeIndex(df["timestamp"]).tz_convert(config.DISPLAY_TZ)
    dmin, dmax = local.min().date(), local.max().date()
    start = max(dmin, (local.max() - pd.Timedelta(days=3)).date())
    val = st.date_input(t("date_range", lang), value=(start, dmax), min_value=dmin, max_value=dmax, key=key)
    lo, hi = (val[0], val[1]) if isinstance(val, (tuple, list)) and len(val) == 2 else (val[0] if isinstance(val, (tuple, list)) else val,) * 2
    mask = (local.date >= lo) & (local.date <= hi)
    return df[mask]


def flag_summary(row, lang):
    parts = [f"{param_label(p, lang)}: {t('flag_' + row[f'{p}_flag'], lang)}" for p in config.PARAMS if row[f"{p}_flag"] != "ok"]
    return "; ".join(parts)


def render(ctx):
    lang, b = ctx["lang"], ctx["bundle"]
    st.subheader(t("data_heading", lang))
    st.caption(t("tz_note", lang))
    if b.df.empty:
        st.info(t("no_rows", lang))
        return
    view = date_filter(b.df, lang, "data_range")
    if st.checkbox(t("filter_flags", lang)):
        view = view[(view[[f"{p}_flag" for p in config.PARAMS]] != "ok").any(axis=1)]
    if view.empty:
        st.info(t("no_rows", lang))
        return
    shown = pd.DataFrame({t("col_time", lang): pd.DatetimeIndex(view["timestamp"]).tz_convert(config.DISPLAY_TZ).strftime("%Y-%m-%d %H:%M"),
                          t("col_device", lang): view["device_id"].to_numpy()})
    for p in config.PARAMS:
        unit = config.UNITS[p]
        shown[f"{param_label(p, lang)}{' (' + unit + ')' if unit else ''}"] = [fmt_value(v, p) for v in view[p]]
    shown[t("col_flag", lang)] = [flag_summary(r, lang) for _, r in view.iterrows()]
    st.dataframe(shown.iloc[::-1].head(1000), hide_index=True, use_container_width=True)
    out = view.copy()
    out["timestamp"] = pd.DatetimeIndex(out["timestamp"]).strftime("%Y-%m-%dT%H:%M:%SZ")
    out["received_at"] = pd.DatetimeIndex(out["received_at"]).strftime("%Y-%m-%dT%H:%M:%SZ")
    st.download_button(t("download_csv", lang), out.to_csv(index=False).encode("utf-8-sig"),
                       file_name=f"jaldrishti_{ctx['site']['id']}.csv", mime="text/csv")
