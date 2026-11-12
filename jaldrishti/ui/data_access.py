"""Cached loading + analysis so the app stays fast when widgets are clicked."""
import time
from dataclasses import dataclass
import pandas as pd
import streamlit as st
from .. import alerts, config, data_store, demo_data, quality, reviews, validation, whi


@dataclass
class Bundle:
    df: pd.DataFrame
    analysis: alerts.Analysis
    whi_latest: whi.WhiResult
    whi_series: pd.Series
    quality: dict
    rows_rejected: int
    duplicates_removed: int
    curves: dict


def _stamp():
    p = config.RAW_READINGS_PATH
    file_part = (p.stat().st_mtime_ns, p.stat().st_size) if p.exists() else (0, 0)
    return (file_part, int(time.time() // 60))


def _load(source, scenario):
    if source == "demo":
        raw = demo_data.generate(scenario)
    else:
        raw = data_store.load_raw()
    return validation.process(raw)


@st.cache_data(show_spinner=False, max_entries=8)
def sites_for(source, scenario, stamp):
    proc = _load(source, scenario)
    known = data_store.load_sites()
    ids = list(dict.fromkeys(proc.df["location_id"].tolist() + known["location_id"].tolist()))
    out = []
    for sid in ids:
        row = known[known["location_id"] == sid]
        name = sid
        coords = None
        if sid == demo_data.DEMO_SITE:
            name = demo_data.DEMO_SITE_NAME
        elif not row.empty:
            name = row.iloc[0]["name"] or sid
            coords = data_store.valid_coords(row.iloc[0]["latitude"], row.iloc[0]["longitude"])
        out.append({"id": sid, "name": name, "coords": coords,
                    "latitude": coords[0] if coords else None, "longitude": coords[1] if coords else None})
    return out


@st.cache_data(show_spinner=False, max_entries=16)
def bundle_for(source, scenario, site_id, stamp):
    proc = _load(source, scenario)
    df = proc.df[proc.df["location_id"] == site_id].reset_index(drop=True)
    analysis = alerts.analyse(df, site_id)
    curves = whi.get_curves(site_id)
    latest = df.iloc[-1] if len(df) else None
    whi_latest = whi.compute_row(latest, curves) if latest is not None else whi.WhiResult(missing=list(config.WHI_WEIGHTS))
    series = whi.compute_series(df, curves) if len(df) else pd.Series(dtype=float)
    q = quality.summarise(df, analysis.signals.cadence)
    return Bundle(df, analysis, whi_latest, series, q, proc.rows_rejected, proc.duplicates_removed, curves)


def with_verification(analysis, site_id):
    """Marks the current event verified only if a reviewer's recorded decision says so."""
    status = analysis.status
    keys = reviews.verified_keys(site_id)
    if status.state == "investigate" and status.event is not None and status.event.key in keys:
        status.state, status.reason = "verified", "verified"
    return status, keys


def data_stamp():
    return _stamp()
