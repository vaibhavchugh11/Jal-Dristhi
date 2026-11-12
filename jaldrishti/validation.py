"""Turns raw as-received rows into checked values plus a quality flag per parameter.

Raw data is never edited: this builds a separate processed table.
Flags: ok, missing, invalid, implausible, flatline.
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd
from . import config

MISSING_TOKENS = {"", "nan", "none", "null", "na", "n/a"}
TZ_RE = r"(?:[Zz]|[+-]\d{2}:?\d{2})$"
FLAG_OK = "ok"


@dataclass
class Processed:
    df: pd.DataFrame
    rows_rejected: int = 0
    duplicates_removed: int = 0


def _parse_iso(series, **kw):
    try:
        return pd.to_datetime(series, errors="coerce", format="ISO8601", **kw)
    except (ValueError, TypeError):
        return pd.to_datetime(series, errors="coerce", format="mixed", **kw)


def parse_timestamps(raw):
    s = raw.astype(str).str.strip()
    has_tz = s.str.contains(TZ_RE, regex=True)
    aware = _parse_iso(s.where(has_tz), utc=True)
    naive = _parse_iso(s.where(~has_tz & s.ne("")))
    naive = naive.dt.tz_localize(config.NAIVE_TIMESTAMP_TZ, ambiguous="NaT", nonexistent="NaT").dt.tz_convert("UTC")
    return aware.fillna(naive)


def _flag_values(raw_col, param):
    s = raw_col.astype(str).str.strip()
    missing = s.str.lower().isin(MISSING_TOKENS)
    num = pd.to_numeric(s.where(~missing), errors="coerce")
    invalid = ~missing & (num.isna() | np.isinf(num))
    lo, hi = config.PLAUSIBLE[param]
    implausible = num.notna() & ~np.isinf(num) & ((num < lo) | (num > hi))
    flag = pd.Series(FLAG_OK, index=s.index, dtype=object)
    flag[missing] = "missing"
    flag[invalid] = "invalid"
    flag[implausible] = "implausible"
    values = num.where(flag.eq(FLAG_OK))
    return values, flag


def _mark_flatlines(df, param):
    n = config.FLATLINE_N[param]
    flag_col = f"{param}_flag"
    for _, grp in df.groupby(["location_id", "device_id"], sort=False):
        ok = grp[grp[flag_col].eq(FLAG_OK)]
        if len(ok) < n:
            continue
        v = ok[param]
        run_id = v.ne(v.shift()).cumsum()
        run_len = v.groupby(run_id).transform("size")
        df.loc[run_len[run_len >= n].index, flag_col] = "flatline"


def process(raw):
    df = raw.copy()
    for col in config.RAW_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df["timestamp"] = parse_timestamps(df["timestamp"])
    df["received_at"] = _parse_iso(df["received_at"].astype(str).str.strip().where(lambda s: s.ne("")), utc=True)
    now = pd.Timestamp.now(tz="UTC")
    bad_ts = df["timestamp"].isna() | (df["timestamp"] > now + pd.Timedelta(minutes=5))
    rejected = int(bad_ts.sum())
    df = df[~bad_ts].copy()
    for col in ("device_id", "location_id"):
        df[col] = df[col].astype(str).str.strip().replace("", "unknown")
    for p in config.PARAMS:
        df[p], df[f"{p}_flag"] = _flag_values(df[config.CSV_COLUMN[p]], p)
    df = df.sort_values(["location_id", "device_id", "timestamp", "received_at"], kind="stable")
    before = len(df)
    df = df.drop_duplicates(["location_id", "device_id", "timestamp"], keep="last")
    dupes = before - len(df)
    df = df.reset_index(drop=True)
    for p in config.PARAMS:
        _mark_flatlines(df, p)
    keep = ["timestamp", "received_at", "device_id", "location_id"]
    keep += config.PARAMS + [f"{p}_flag" for p in config.PARAMS]
    return Processed(df[keep], rejected, dupes)


def usable(df, param):
    """Values that passed every check (NaN otherwise). Never fills with zero."""
    return df[param].where(df[f"{param}_flag"].eq(FLAG_OK))
