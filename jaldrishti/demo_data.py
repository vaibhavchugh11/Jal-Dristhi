"""Synthetic DEMO data for exploring the interface. Never real field measurements."""
import numpy as np
import pandas as pd
from . import config

SCENARIOS = ["normal", "change", "stale", "fault"]
DEMO_DEVICE = "DEMO-DEVICE-01"
DEMO_SITE = "DEMO-SITE-1"
DEMO_SITE_NAME = "Demo site (not a real location)"
DAYS = 7


def is_demo_id(value):
    """Anything with an id starting DEMO is labelled DEMO DATA, even when loaded from a CSV file."""
    return str(value).strip().upper().startswith("DEMO")


def generate(scenario="normal", now=None, seed=42):
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    if now.tzinfo is None:
        now = now.tz_localize("UTC")
    end = now.floor("5min")
    if scenario == "stale":
        end = end - pd.Timedelta(hours=3)
    n = DAYS * 288
    idx = pd.date_range(end=end, periods=n, freq="5min")
    rng = np.random.RandomState(seed)
    hour = (idx.tz_convert(config.DISPLAY_TZ).hour + idx.minute / 60).to_numpy()
    wave = np.sin(2 * np.pi * (hour - 9) / 24)

    ph = 7.45 + 0.04 * wave + rng.normal(0, 0.025, n)
    turb = 6.0 * np.exp(rng.normal(0, 0.12, n))
    tds = 320 + 4 * wave + rng.normal(0, 3, n)
    do = 6.8 + 0.9 * wave + rng.normal(0, 0.08, n)
    temp = 28 + 1.5 * wave + rng.normal(0, 0.08, n)

    def bump(start, length, a_turb, a_tds, a_ph, a_do):
        ramp = np.clip(np.arange(length) / 6.0, 0, 1)
        sl = slice(start, start + length)
        turb[sl] += a_turb * ramp
        tds[sl] += a_tds * ramp
        ph[sl] += a_ph * ramp
        do[sl] += a_do * ramp

    bump(n - 3 * 288 - 40, 24, 30, 55, -0.2, -0.6)      # an earlier synthetic event, so History/Events have content
    if scenario == "change":
        bump(n - 18, 18, 40, 70, -0.25, -0.8)
    cols = {"ph": ph, "turbidity": turb, "tds": tds, "do": do, "temperature": temp}
    text = {p: pd.Series(np.round(v, config.DECIMALS[p]), index=idx).astype(object) for p, v in cols.items()}

    if scenario == "fault":
        text["do"].iloc[-30:] = text["do"].iloc[-30]
        text["temperature"].iloc[-8:] = -127.0
    for p in config.PARAMS:                                   # random dropouts
        drop = rng.rand(n) < 0.01
        text[p][drop] = ""
    gap = slice(n - 5 * 288, n - 5 * 288 + 18)                # a short device outage
    for p in config.PARAMS:
        text[p].iloc[gap] = ""

    raw = pd.DataFrame({
        "received_at": (idx + pd.Timedelta(seconds=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "device_id": DEMO_DEVICE,
        "location_id": DEMO_SITE,
        "timestamp": idx.strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    for p in config.PARAMS:
        raw[config.CSV_COLUMN[p]] = text[p].astype(str).to_numpy()
    return raw.reset_index(drop=True)
