"""Data completeness, flag counts and connection status for the technical view."""
import pandas as pd
from . import config


def summarise(df, cadence, now=None):
    now = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    out = {"n_readings": len(df), "cadence": cadence, "last_received": None, "age_minutes": None,
           "connection": "nodata", "completeness": {}, "flags": {}}
    if df.empty:
        return out
    latest = df["timestamp"].max()
    age = (now - latest).total_seconds() / 60
    out["last_received"], out["age_minutes"] = latest, age
    out["connection"] = "stale" if age > max(config.STALE_AFTER_MINUTES, 6 * cadence) else "online"
    window = df[df["timestamp"] > latest - pd.Timedelta(hours=24)]
    expected = max(1, int(24 * 60 / cadence))
    for p in config.PARAMS:
        ok = int(window[f"{p}_flag"].eq("ok").sum())
        out["completeness"][p] = min(100.0, 100.0 * ok / expected)
        counts = df[f"{p}_flag"].value_counts()
        out["flags"][p] = {k: int(counts.get(k, 0)) for k in ("ok", "missing", "invalid", "implausible", "flatline")}
    return out
