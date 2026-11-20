"""Report tab of the Firms view: pick a period, generate, preview and download."""
import inspect
import os
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from .. import company as C
from .. import insights as I
from .. import report_build as RB
from .. import report_out as RO
from .. import standards as std
from .whi_panel import data_fingerprint, kind_of

PRI = {"high": "#d64545", "medium": "#f28c28", "low": "#6c8ebf"}
BASIS_OPTIONS = {"reading": "each reading", "mean_1h": "1 h average", "mean_24h": "24 h average"}


def _stretch():
    try:
        return {"width": "stretch"} if "width" in inspect.signature(st.button).parameters else {"use_container_width": True}
    except (TypeError, ValueError):
        return {}


def _num(t):
    return C.num(str(t).replace(",", "")) if str(t).strip() else None


def merge_profiles(base, local, org):
    if not base and not local:
        return None
    out = {"name": (base or {}).get("name") or org or "Your company", "limits": dict((base or {}).get("limits", {})),
           "policies": list((base or {}).get("policies", [])), "warnings": list((base or {}).get("warnings", []))}
    if local:
        out["limits"].update(local["limits"])
        out["policies"] += [x for x in local["policies"] if x not in out["policies"]]
    return out


def _editor(email, org, current):
    saved = C.load_local(email)
    cur = (saved.get("limits") or {})
    pol0 = "\n".join(saved.get("policies") or [])
    with st.expander("Limits and policies for this report (optional)", expanded=not (current and (current["limits"] or current["policies"]))):
        st.caption("Leave Minimum and Maximum empty when there is no limit. Anything saved here is added to the limits already saved in the Compliance limits tab.")
        with st.form("fr_limits_form"):
            entered = {}
            options = list(BASIS_OPTIONS.values())
            for p in C.PARAMS:
                c = cur.get(p, {})
                st.markdown("**" + C.LABEL[p] + (f" ({C.UNIT[p]})" if C.UNIT[p] else "") + "**")
                a, b = st.columns(2)
                lo = a.text_input("Minimum", value="" if c.get("lo") is None else str(c["lo"]), key=f"fr_lim_{p}_lo", placeholder="no minimum")
                hi = b.text_input("Maximum", value="" if c.get("hi") is None else str(c["hi"]), key=f"fr_lim_{p}_hi", placeholder="no maximum")
                a, b = st.columns(2)
                basis = a.selectbox("Compared as", options, index=options.index(BASIS_OPTIONS.get(c.get("basis", "reading"), options[0])), key=f"fr_lim_{p}_basis")
                ref = b.text_input("Policy reference (optional)", value=c.get("ref", ""), key=f"fr_lim_{p}_ref")
                entered[p] = (lo, hi, basis, ref)
            pol = st.text_area("Other policies or requirements you must follow (one per line)", value=pol0, key="fr_policies",
                               placeholder="for example: Effluent pH must stay between 6.5 and 8.5\nReport any BOD above 30 mg/L to the board within 24 h")
            saved_now = st.form_submit_button("Save")
        if saved_now:
            lim, bad = {}, []
            inv = {v: k for k, v in BASIS_OPTIONS.items()}
            for p, (lo, hi, basis, ref) in entered.items():
                lo_n, hi_n = _num(lo), _num(hi)
                if (lo.strip() and lo_n is None) or (hi.strip() and hi_n is None):
                    bad.append(C.LABEL[p] + ": please type numbers only")
                    continue
                if lo_n is None and hi_n is None:
                    continue
                if lo_n is not None and hi_n is not None and lo_n > hi_n:
                    bad.append(C.LABEL[p] + ": the minimum is above the maximum")
                    continue
                lim[p] = {"lo": lo_n, "hi": hi_n, "basis": inv[basis], "ref": ref.strip()}
            if bad:
                for x in bad:
                    st.error(x)
            else:
                C.save_local(email, {"limits": lim, "policies": [x.strip() for x in pol.splitlines() if x.strip()]})
                st.session_state["fr_saved_msg"] = True
                st.rerun()
    if st.session_state.pop("fr_saved_msg", False):
        st.success("Saved.")


def _models(df, kind, site, end):
    key = (site.get("id"), len(df), str(df["timestamp"].iloc[-1]), data_fingerprint(df), kind, str(pd.Timestamp(end).floor("1h")))
    cache = st.session_state.setdefault("rpt_models", {})
    if key not in cache:
        if len(cache) >= 3:
            cache.pop(next(iter(cache)))
        cache[key] = I.build_models(df, kind, end)
    return cache[key]


def render(ctx, user):
    df = ctx["bundle"].df
    site = ctx.get("site") or {}
    org = (user or {}).get("org") or ""
    email = (user or {}).get("email") or "account"
    st.subheader("Report")
    if df is None or len(df) == 0:
        st.info("No readings yet.")
        return
    h0 = None
    kind = getattr(ctx.get("water_type"), "kind", None)
    if kind not in ("freshwater", "brackish", "seawater"):
        h0 = I.add_columns(I.hourly_table(df.tail(20000)))
        kind = I.kind_from_tds(h0) if len(h0) else "freshwater"
    profiles, why = C.load_profiles()
    shared = os.getenv("JALDRISHTI_SHARED_PROFILES", "") == "1"
    base = C.pick_profile(profiles, org, strict=not shared)
    if base is None and shared and len(profiles) > 1:
        names = [p["name"] for p in profiles]
        base = profiles[names.index(st.selectbox("Which saved company profile should this report use?", names, key="fr_profile_pick"))]
    local = C.profile_from_local(email, org)
    profile = merge_profiles(base, local, org)
    if base is not None:
        st.caption(f"Using the saved company profile: {base['name']}" + (" plus the limits saved on this page." if local else "."))
    elif profiles and not shared:
        st.info(f"No saved profile named '{org}' was found in the Compliance limits tab. Save it there with the same company name as your account, or enter the limits below.")
    _editor(email, org, profile)

    st.markdown("**Choose the period**")
    sw = _stretch()
    c1, c2, c3 = st.columns(3)
    pick = None
    if c1.button("Today", key="fr_b_today", **sw):
        pick = ("today", None)
    if c2.button("This month", key="fr_b_month", **sw):
        pick = ("month", None)
    if c3.button("This year", key="fr_b_year", **sw):
        pick = ("year", None)
    today = date.today()
    rng = st.date_input("Or choose a range of dates", value=(today - timedelta(days=7), today), key="fr_range", max_value=today)
    if st.button("Generate report for these dates", key="fr_b_custom", **sw):
        if isinstance(rng, (tuple, list)) and len(rng) == 2:
            pick = ("custom", (rng[0], rng[1]))
        else:
            st.error("Please pick both a start date and an end date.")
    if pick:
        try:
            last = pd.to_datetime(df["timestamp"], utc=True).max()
            period = RB.period_bounds(pick[0], now=max(pd.Timestamp.now(tz="UTC"), last) if pick[0] != "custom" else pd.Timestamp.now(tz="UTC"), rng=pick[1])
        except ValueError as e:
            st.error(str(e))
            return
        with st.spinner("Training and checking the models on this site's data, then building the report..."):
            models = _models(df, kind, site, period[1])
            rep = RB.build_report(df, site, period, profile, kind, user, models, is_demo=bool(ctx.get("is_demo")))
            pdf = RO.to_pdf(rep)
            st.session_state["fr_report"] = {"R": rep, "pdf": pdf, "html": RO.to_html(rep), "zip": RO.to_zip(rep, pdf), "label": period[2]}
    out = st.session_state.get("fr_report")
    if not out:
        st.info("Pick Today, This month, This year or a range of dates to generate the report.")
        return
    rep = out["R"]
    st.markdown(f"#### Report for {out['label']}")
    for b in rep.doc:
        if b["t"] == "callout" and b["level"] == "low" and b["title"] == "DEMO DATA":
            st.warning(b["lines"][0])
    card = next((b for b in rep.doc if b["t"] == "card"), None)
    if card:
        st.markdown(f"<div style='background:{card['fill']};color:{card['fg']};border-radius:10px;padding:12px 16px;margin:6px 0'><div style='font-size:1.25em;font-weight:800'>{card['title']}</div>"
                    + "".join(f"<div>{x}</div>" for x in card["lines"]) + "</div>", unsafe_allow_html=True)
    chips = next((b for b in rep.doc if b["t"] == "chips"), None)
    if chips:
        st.markdown("<div style='display:flex;flex-wrap:wrap;gap:6px'>" + "".join(
            f"<div style='background:{c['fill']};color:{c['fg']};border-radius:8px;padding:6px 10px;flex:1 1 130px'><div style='font-size:.78em'>{c['label']}</div><b>{c['value']}</b></div>" for c in chips["items"]) + "</div>", unsafe_allow_html=True)
    ids = [i for i, b in enumerate(rep.doc) if b["t"] == "callout" and b["title"][:1].isdigit()]
    if ids:
        st.markdown("**Top findings**")
        for i in ids[:3]:
            b = rep.doc[i]
            st.markdown(f"<div style='border-left:6px solid {PRI[b['level']]};background:#f6f6f6;padding:6px 10px;margin:6px 0;color:#222'><b>{b['title']}</b><br>{b['lines'][0]}</div>", unsafe_allow_html=True)
    elif rep.summary.get("status") != "nodata":
        st.success("No problems were found in this period.")
    d1, d2, d3 = st.columns(3)
    d1.download_button("Download PDF", out["pdf"], "JalDrishti_report.pdf", "application/pdf", key="fr_dl_pdf", **sw)
    d2.download_button("Download web page (HTML)", out["html"], "JalDrishti_report.html", "text/html", key="fr_dl_html", **sw)
    d3.download_button("Download ZIP with tables (CSV)", out["zip"], "JalDrishti_report.zip", "application/zip", key="fr_dl_zip", **sw)
