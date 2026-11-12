"""Plotly figures. Text comes from the translation dictionary; times are shown in IST."""
import pandas as pd
import plotly.graph_objects as go
from . import config
from .i18n import t, param_label
from .validation import usable

TEAL = "#0f766e"
NAVY = "#0b2545"
AMBER = "#b45309"
FONT = "Noto Sans Devanagari, Nirmala UI, Mangal, Segoe UI, Arial, sans-serif"


def _local(ts):
    idx = pd.DatetimeIndex(ts)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    return idx.tz_convert(config.DISPLAY_TZ).tz_localize(None)


def _title(param, lang):
    unit = config.UNITS[param]
    label = param_label(param, lang)
    return t("graph_title", lang, param=f"{label} ({unit})" if unit else label)


def _layout(fig, lang, title, height):
    fig.update_layout(
        title=dict(text=title, font=dict(size=15, color=NAVY)), height=height, template="plotly_white",
        margin=dict(l=8, r=8, t=44, b=8), hovermode="x unified", font=dict(family=FONT, size=13),
        legend=dict(orientation="h", yanchor="top", y=-0.42, xanchor="left", x=0),
        xaxis_title=t("axis_time", lang))
    return fig


def param_figure(lang, df, param, sig=None, events=None, show_baseline=True, show_events=True, height=320):
    fig = go.Figure()
    x = _local(df["timestamp"])
    if sig is not None and show_baseline and not sig.median.empty:
        lo, hi = x.min(), x.max()
        gx = _local(sig.median.index)
        m = (gx >= lo) & (gx <= hi)
        med, s = sig.median[param][m], sig.sigma[param][m]
        if med.notna().any():
            fig.add_trace(go.Scatter(x=gx[m], y=med - config.Z_THRESHOLD * s, mode="lines", line=dict(width=0),
                                     showlegend=False, hoverinfo="skip"))
            fig.add_trace(go.Scatter(x=gx[m], y=med + config.Z_THRESHOLD * s, mode="lines", line=dict(width=0),
                                     fill="tonexty", fillcolor="rgba(15,118,110,0.12)", name=t("legend_baseline", lang),
                                     hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x, y=usable(df, param), mode="lines", name=t("legend_reading", lang),
                             line=dict(color=TEAL, width=1.8), connectgaps=False))
    flat = df[f"{param}_flag"].eq("flatline")
    if flat.any():
        fig.add_trace(go.Scatter(x=x[flat.to_numpy()], y=df.loc[flat, param], mode="markers", name=t("legend_invalid", lang),
                                 marker=dict(symbol="x", color=AMBER, size=6)))
    if show_events and events:
        for e in events:
            x0, x1 = _local([e.start])[0], _local([e.end])[0]
            if x1 >= x.min() and x0 <= x.max() and param in e.params:
                fig.add_vrect(x0=x0, x1=x1, fillcolor="rgba(217,119,6,0.18)", line_width=0)
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers", name=t("legend_event", lang),
                                 marker=dict(symbol="square", color="rgba(217,119,6,0.5)", size=10)))
    fig.update_yaxes(title_text=config.UNITS[param] or param_label(param, lang))
    return _layout(fig, lang, _title(param, lang), height)


def whi_figure(lang, df, scores, height=300):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=_local(df["timestamp"]), y=scores, mode="lines", line=dict(color=NAVY, width=1.8),
                             name=t("whi_score", lang), connectgaps=False))
    for lower, name in config.WHI_BANDS[:-1]:
        fig.add_hline(y=lower, line=dict(color="#94a3b8", width=1, dash="dot"),
                      annotation_text=t(f"band_{name}", lang), annotation_position="top left")
    fig.update_yaxes(range=[0, 100], title_text="WHI")
    return _layout(fig, lang, t("whi_heading", lang), height)


def limit_figure(lang, df, param, limit, episodes=(), height=340):
    fig = go.Figure()
    x = _local(df["timestamp"])
    fig.add_trace(go.Scatter(x=x, y=usable(df, param), mode="lines", name=t("legend_reading", lang),
                             line=dict(color=TEAL, width=1.8), connectgaps=False))
    for bound in ("min", "max"):
        if limit.get(bound) is not None:
            fig.add_hline(y=limit[bound], line=dict(color="#b91c1c", width=2, dash="dash"))
    fig.add_trace(go.Scatter(x=[None], y=[None], mode="lines", name=t("legend_limit", lang),
                             line=dict(color="#b91c1c", width=2, dash="dash")))
    for e in episodes:
        fig.add_vrect(x0=_local([e.start])[0], x1=_local([e.end])[0], fillcolor="rgba(185,28,28,0.15)", line_width=0)
    if episodes:
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers", name=t("legend_outside", lang),
                                 marker=dict(symbol="square", color="rgba(185,28,28,0.4)", size=10)))
    fig.update_yaxes(title_text=config.UNITS[param] or param_label(param, lang))
    return _layout(fig, lang, _title(param, lang), height)
