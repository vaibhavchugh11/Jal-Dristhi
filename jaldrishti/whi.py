"""Provisional Water Health Index: weighted sum of four 0-100 sub-indices. No silent zero-filling."""
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
from . import config, data_store


def get_curves(site_id=None):
    curves = {p: [tuple(pt) for pt in pts] for p, pts in config.WHI_CURVES.items()}
    over = data_store.load_whi_overrides().get(site_id, {}) if site_id else {}
    for p, pts in over.items():
        if p in curves and len(pts) >= 2:
            curves[p] = [tuple(pt) for pt in pts]
    return curves


def subindex(param, value, curves):
    xs, ys = zip(*sorted(curves[param]))
    return float(np.interp(value, xs, ys))


def band_for(score):
    for lower, name in config.WHI_BANDS:
        if score >= lower:
            return name
    return config.WHI_BANDS[-1][1]


@dataclass
class WhiResult:
    score: float = None
    band: str = None
    components: list = field(default_factory=list)
    missing: list = field(default_factory=list)


def compute_row(row, curves):
    comps, missing = [], []
    for p, w in config.WHI_WEIGHTS.items():
        ok = row.get(f"{p}_flag") == "ok" and not pd.isna(row.get(p))
        if not ok:
            missing.append(p)
            continue
        sub = subindex(p, row[p], curves)
        comps.append({"param": p, "value": float(row[p]), "subindex": sub, "weight": w, "contribution": sub * w})
    if missing:
        return WhiResult(None, None, comps, missing)
    total = 0.0
    for c in comps:                       # plain accumulation, identical to compute_series (sum() rounds differently)
        total += c["contribution"]
    score = float(np.round(total, 1))
    return WhiResult(score, band_for(score), comps, [])


def compute_series(df, curves):
    total = pd.Series(0.0, index=df.index)
    complete = pd.Series(True, index=df.index)
    for p, w in config.WHI_WEIGHTS.items():
        ok = df[f"{p}_flag"].eq("ok") & df[p].notna()
        xs, ys = zip(*sorted(curves[p]))
        sub = pd.Series(np.interp(df[p].fillna(0), xs, ys), index=df.index)
        total += sub * w
        complete &= ok
    return total.where(complete).round(1)
