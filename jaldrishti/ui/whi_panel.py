"""Colour-coded Water Health Index (CPCB and BIS limits) shown to all three audiences."""
import html

import numpy as np
import pandas as pd
import streamlit as st

from .. import insights as I
from .. import standards as std

TZ = "Asia/Kolkata"
LABEL = std.LABEL
UNIT = std.UNIT
DEC = {"ph": 2, "turbidity": 1, "tds": 0, "do": 2, "temperature": 1}
DAYS = 30


def kind_of(ctx, h=None):
    wt = ctx.get("water_type")
    k = getattr(wt, "kind", None)
    if k in ("freshwater", "brackish", "seawater"):
        return k
    return I.kind_from_tds(h) if h is not None else "freshwater"


@st.cache_data(show_spinner=False, max_entries=4)
def _grade(_df, stamp, kind_hint):
    ts = pd.to_datetime(_df["timestamp"], utc=True)
    df = _df[ts >= ts.max() - pd.Timedelta(days=DAYS + 32)]       # the turbidity-free index needs no long history
    h = I.add_columns(I.hourly_table(df))
    if len(h) < 2:
        return None
    kind = kind_hint or I.kind_from_tds(h)
    f, w, src = I.whi_frame(h, kind)
    f = f[f.index >= f.index.max() - pd.Timedelta(days=DAYS)]
    return {"kind": kind, "frame": f, "latest": I.latest_grading(h, kind), "weights": {k: float(v) for k, v in w.items()}, "source": src}


def data_fingerprint(df):
    # changes when recent readings or their quality flags change, not only when rows are added
    tail = df.tail(2000)
    flags = tail.filter(like="_flag")
    bad = int((flags.astype(str) != "ok").to_numpy().sum()) if flags.shape[1] else 0
    vals = tail.select_dtypes("number")
    return (bad, round(float(vals.sum().sum()), 3))


def _fmt(p, v):
    if v is None:
        return "-"
    return f"{v:.{DEC[p]}f}" + ((" " + UNIT[p]) if UNIT[p] else "")


def _chip(label, value, tier, sub):
    fill = std.COLOURS.get(tier, std.GREY)
    fg = std.TEXT_ON.get(tier, "#222222")
    return (f"<div style='background:{fill};color:{fg};border-radius:8px;padding:8px 10px;flex:1 1 150px;min-width:140px'>"
            f"<div style='font-size:.78em;opacity:.95'>{html.escape(label)}</div><div style='font-size:1.15em;font-weight:700'>{html.escape(value)}</div>"
            f"<div style='font-size:.78em'>{html.escape(sub)}</div></div>")


def _day_strip(frame):
    f = frame.dropna(subset=["whi"])
    if f.empty:
        return ""
    loc = f.index.tz_convert(TZ)
    g = f.groupby(loc.floor("1D"))
    cells = []
    for day, grp in g:
        m = float(grp["whi"].mean())
        red = float((grp["worst_tier"] >= 4).mean())
        edge = "border-bottom:5px solid #7a0019;" if red >= 0.10 else ""
        tip = f"{day.strftime('%d %b')}: {std.band_name(m)}, index {m:.0f}" + (f". A parameter was Red in {red * 100:.0f}% of the hours." if red >= 0.10 else "")
        cells.append(f"<div title='{tip}' style='background:{std.band_colour(m)};color:{std.band_text_on(m)};{edge}width:34px;height:34px;box-sizing:border-box;"
                     f"border-radius:5px;display:flex;align-items:center;justify-content:center;font-size:.72em'>{day.day}</div>")
    return "<div style='display:flex;flex-wrap:wrap;gap:4px;margin:6px 0'>" + "".join(cells) + "</div>"


def _band_share_html(frame, days):
    cut = frame.index.max() - pd.Timedelta(days=days)
    v = frame[frame.index > cut]["whi"].dropna()
    if v.empty:
        return ""
    idx = v.map(std.band_index)
    cells = ""
    for i, (lower, name) in enumerate(std.bands()):
        share = float((idx == i).mean()) * 100
        cells += (f"<td style='background:{std.BAND_COLOURS[i]};color:{std.BAND_TEXT_ON[i]};text-align:center;padding:4px 8px'>{share:.0f}%</td>" if share >= 1
                  else "<td style='text-align:center;color:#999;padding:4px 8px'>0%</td>")
    head = "".join(f"<th style='padding:4px 8px'>{n}<br><span style='font-weight:400;font-size:.8em'>{std.band_range_text(i)}</span></th>" for i, (_, n) in enumerate(std.bands()))
    return (f"<div style='overflow-x:auto'><table style='border-collapse:collapse;width:100%;font-size:.9em'><tr>{head}</tr><tr>{cells}</tr></table></div>"
            f"<div style='font-size:.8em;color:#555'>Share of hours by index value (higher is better). Average {v.mean():.0f}, lowest {v.min():.0f}.</div>")


def _share_table(frame, kind, params, days):
    cut = frame.index.max() - pd.Timedelta(days=days)
    f = frame[frame.index > cut]
    rows = ""
    for p in params:
        tv = f[p + "_tier"].dropna()
        if tv.empty:
            continue
        cells = ""
        for t in (1, 2, 3, 4):
            v = float((tv == t).mean()) * 100
            cells += (f"<td style='background:{std.COLOURS[t]};color:{std.TEXT_ON[t]};text-align:center'>{v:.0f}%</td>" if v >= 1 else "<td style='text-align:center;color:#999'>0%</td>")
        sp = std.spec(p, kind)
        rows += f"<tr><td>{LABEL[p]}</td><td style='font-size:.85em'>{html.escape(sp['tiers'][1]['std'])}: {html.escape(std.rule_text(p, kind, 1))}</td>{cells}</tr>"
    head = "<tr><th style='text-align:left'>Parameter</th><th style='text-align:left'>Green limit</th>" + "".join(f"<th>{n}</th>" for n in ("Green", "Yellow", "Orange", "Red")) + "</tr>"
    return f"<div style='overflow-x:auto'><table style='border-collapse:collapse;width:100%;font-size:.9em'>{head}{rows}</table></div>"


def standards_expander(kind):
    with st.expander("What the colours and the number mean"):
        st.markdown("**The index number: higher is better.** 100 is the best and 0 is the worst.")
        rows = "".join(f"<tr><td style='background:{std.BAND_COLOURS[i]};color:{std.BAND_TEXT_ON[i]};padding:4px 10px'>{n}</td><td style='padding:4px 10px'>{std.band_range_text(i)}</td></tr>"
                       for i, (_, n) in enumerate(std.bands()))
        st.markdown(f"<table style='border-collapse:collapse;font-size:.9em'>{rows}</table>", unsafe_allow_html=True)
        st.caption("These index bands are provisional design choices, not taken from a regulation. The number is a weighted average of the sensor scores.")
        st.markdown("**The colour of each sensor** comes from CPCB and BIS limits, and is a separate alert from the index number.")
        st.caption("Green = the strictest class limit is met, Yellow = the next, Orange = only the most relaxed, Red = outside every limit. "
                   "Rows marked 'check' were entered from memory and should be confirmed against the official CPCB and BIS documents.")
        rows = std.table_rows(kind)
        body = ""
        for x in rows:
            fill = std.COLOURS.get(x["tier"], std.GREY)
            body += (f"<tr><td>{html.escape(x['label'])}</td><td style='background:{fill};color:{std.TEXT_ON.get(x['tier'], '#222')}'>{x['colour']}</td>"
                     f"<td>{html.escape(x['rule'])}</td><td>{html.escape(x['std'])}{(' (' + html.escape(x['use']) + ')') if x['use'] else ''}</td><td>{'check' if x['verify'] else ''}</td></tr>")
        st.markdown("<div style='overflow-x:auto'><table style='border-collapse:collapse;width:100%;font-size:.85em'>"
                    "<tr><th style='text-align:left'>Parameter</th><th>Colour</th><th style='text-align:left'>Rule</th><th style='text-align:left'>Standard</th><th>Verify</th></tr>"
                    + body + "</table></div>", unsafe_allow_html=True)


def render(ctx, mode, user=None):
    df = ctx["bundle"].df
    if df is None or len(df) == 0:
        return
    site = ctx.get("site") or {}
    stamp = (site.get("id"), len(df), str(df["timestamp"].iloc[-1]), data_fingerprint(df))
    wt = ctx.get("water_type")
    hint = getattr(wt, "kind", None)
    g = _grade(df, stamp, hint if hint in ("freshwater", "brackish", "seawater") else None)
    st.markdown("### Water Health Index")
    if g is None or g["latest"] is None:
        st.info("Not enough valid sensor readings yet to work out the Water Health Index. It needs at least three working sensors in the same hour.")
        return
    lg, kind, f = g["latest"], g["kind"], g["frame"]
    params = list(lg["tiers"])
    score = lg["whi"]
    bname, bcol, bfg = std.band_name(score), std.band_colour(score), std.band_text_on(score)
    asof = pd.Timestamp(lg["as_of"]).tz_convert(TZ).strftime("%d %b %H:%M")
    big = f"<div style='font-size:2.1em;font-weight:800;line-height:1.1'>{score:.0f}<span style='font-size:.45em;font-weight:500'> / 100</span> &nbsp; {bname}</div>"
    if mode == "community":
        body = (big + f"<div>{std.BAND_PLAIN[bname]} Higher is better.</div>"
                f"<div style='font-size:.85em;margin-top:4px'>Latest complete hour: {asof} IST. This is a provisional summary of the sensors we have.</div>")
    else:
        body = (big + "<div>Water Health Index. Higher is better: 100 is the best, 0 is the worst.</div>"
                f"<div style='font-size:.85em;margin-top:4px'>Latest complete hour: {asof} IST. Provisional number; the colour comes from the number only. "
                "Weak individual sensors are shown separately below.</div>")
    st.markdown(f"<div style='background:{bcol};color:{bfg};border-radius:10px;padding:12px 16px;margin:6px 0'>{body}</div>", unsafe_allow_html=True)
    bad = [(p, tr) for p, tr in lg["tiers"].items() if tr is not None and tr >= 3]
    if bad:
        worst = max(tr for _, tr in bad)
        lines = ""
        for p, tr in sorted(bad, key=lambda x: -x[1]):
            if mode == "community":
                txt = f"{LABEL[p]}: {std.PLAIN[p][tr]} ({_fmt(p, lg['values'][p])})"
            else:
                txt = f"{LABEL[p]} - {std.NAMES[tr]} - {_fmt(p, lg['values'][p])}: {std.tier_phrase(p, kind, tr).split(': ', 1)[1]}"
            lines += f"<div style='margin-top:2px'>{html.escape(txt)}</div>"
        st.markdown(f"<div style='border-left:8px solid {std.COLOURS[worst]};background:{std.COLOURS[worst]}22;padding:8px 12px;border-radius:6px;margin:6px 0'>"
                    f"<b>Parameter alert</b> (this does not change the index number above)" + lines + "</div>", unsafe_allow_html=True)
    age_h = (pd.Timestamp.now(tz="UTC") - pd.Timestamp(lg["data_end"])).total_seconds() / 3600
    if age_h > 6:
        st.caption(f"The newest reading is {age_h:.0f} hours old, so the buoy may be offline. The index shows the last hour with enough working sensors.")
    chips = ""
    for p in params:
        tr = lg["tiers"][p]
        if tr is None:
            continue
        sub = std.NAMES[tr] + (": " + std.spec(p, kind)["tiers"][tr]["std"] if tr in std.spec(p, kind)["tiers"] else "")
        if mode == "community":
            sub = std.PLAIN[p][tr]
        chips += _chip(LABEL[p], _fmt(p, lg["values"][p]), tr, sub)
    st.markdown(f"<div style='display:flex;flex-wrap:wrap;gap:6px;margin:6px 0'>{chips}</div>", unsafe_allow_html=True)
    if mode == "technical":
        st.markdown("**Share of hours by index value, and by sensor colour**")
        d7, d30 = st.tabs(["Last 7 days", "Last 30 days"])
        with d7:
            st.markdown(_band_share_html(f, 7), unsafe_allow_html=True)
            st.markdown(_share_table(f, kind, params, 7), unsafe_allow_html=True)
        with d30:
            st.markdown(_band_share_html(f, 30), unsafe_allow_html=True)
            st.markdown(_share_table(f, kind, params, 30), unsafe_allow_html=True)
    st.markdown("**Last 30 days** (each square is a day, coloured by its index band; a dark red bottom edge means a parameter was Red for 10% or more of that day)")
    st.markdown(_day_strip(f), unsafe_allow_html=True)
    if mode == "firm":
        st.caption("Open the Report tab for the full report with statistics, forecasts and advice written for your company.")
    if "tds" in std.NOT_GRADED[std.group(kind)]:
        st.caption("TDS is not coloured here because dissolved salt is natural in brackish and sea water.")
    standards_expander(kind)
