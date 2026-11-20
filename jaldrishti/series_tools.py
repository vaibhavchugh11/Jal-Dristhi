import numpy as np
import pandas as pd

from .validation import usable


def usable_series(df, p):
    # readings of one parameter that passed the quality checks, indexed by UTC time.
    # "passed the quality checks" is decided by validation.usable, the same function the alert logic uses
    empty = pd.Series(dtype=float, index=pd.DatetimeIndex([], tz="UTC"))
    if df is None or len(df) == 0:
        return empty
    try:
        v = np.asarray(pd.to_numeric(pd.Series(np.asarray(usable(df, p))), errors="coerce"), dtype=float)
    except KeyError:
        return empty
    ts = pd.to_datetime(df["timestamp"], utc=True)
    s = pd.Series(v, index=pd.DatetimeIndex(ts))
    s = s[~s.index.isna()].sort_index()
    return s[~s.index.duplicated(keep="last")]
