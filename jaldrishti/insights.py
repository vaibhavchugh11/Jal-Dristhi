import io
import numpy as np
import pandas as pd
from . import standards as std
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import average_precision_score, f1_score, precision_score, recall_score
from sklearn.preprocessing import StandardScaler

try:
    import xgboost as xgb
except ImportError:
    xgb = None

PARAMS = ["ph", "turbidity", "tds", "do", "temperature"]
HORIZON = 6                  # hours ahead
MIN_SPAN_DAYS = 21           # less history than this and nothing is trained
MIN_ROWS = (150, 50, 50)     # train, validation, test rows needed
MIN_EVENTS_TRAIN_VAL = 15
MIN_EVENTS_TEST = 6
BEAT_BY = 0.05               # a model must beat the best simple baseline by 5 percent
RISE_MIN_NTU = 2.0


# ------------------------------------------------------------ reading the table

def _usable(df, p):
    try:
        from .validation import usable
        return pd.Series(np.asarray(pd.to_numeric(pd.Series(np.asarray(usable(df, p))), errors="coerce"), dtype=float), index=df.index)
    except Exception:
        s = pd.to_numeric(df[p], errors="coerce")
        f = p + "_flag"
        if f in df.columns:
            s = s.where(df[f].astype(str) == "ok")
        return s


def hourly_table(df):
    # one row per hour (mean of the good readings). an hour needs at least half of its readings
    ts = pd.DatetimeIndex(pd.to_datetime(df["timestamp"], utc=True))
    t = pd.DataFrame({p: _usable(df, p).values for p in PARAMS if p in df.columns}, index=ts)
    t = t[~t.index.isna()]
    t = t[~t.index.duplicated(keep="last")].sort_index()
    if len(t) < 2:
        return t
    minutes = t.index.to_series().diff().median() / pd.Timedelta(minutes=1)
    if not minutes or np.isnan(minutes) or minutes <= 0:
        minutes = 5
    need = max(1, int(round(0.5 * 60 / minutes)))
    g = t.resample("1h")
    return g.mean().where(g.count() >= need)


def kind_from_tds(h):
    if "tds" not in h or h["tds"].dropna().empty:
        return "freshwater"
    m = h["tds"].dropna().iloc[-24 * 7:].median()
    return "freshwater" if m < 500 else ("brackish" if m < 30000 else "seawater")


def do_sat_mgl(temp_c, salinity=0.0):
    # Benson and Krause 1984 (the equations USGS uses), sea level
    T = np.asarray(temp_c, dtype=float) + 273.15
    lnC = (-139.34411 + 1.575701e5 / T - 6.642308e7 / T ** 2 + 1.243800e10 / T ** 3 - 8.621949e11 / T ** 4)
    lnC = lnC - salinity * (1.7674e-2 - 1.0754e1 / T + 2.1407e3 / T ** 2)
    return np.exp(lnC)


def add_columns(h):
    h = h.copy()
    sal = 0.0
    if "tds" in h and h["tds"].notna().any():
        sal = float(np.clip(h["tds"].dropna().median() / 1000.0, 0, 42))
    h["salinity"] = sal
    if "do" in h and "temperature" in h:
        h["do_sat_mgl"] = do_sat_mgl(h["temperature"], sal)
        h["do_sat"] = 100.0 * h["do"] / h["do_sat_mgl"]
    if "turbidity" in h:
        h["logturb"] = np.log1p(h["turbidity"].clip(lower=0))
    return h


def readiness(h):
    need = [c for c in ("do_sat", "temperature") if c in h]
    ok = h[need].dropna() if need else h.iloc[0:0]
    span = (h.index.max() - h.index.min()).days if len(h) else 0
    out = {"span_days": int(span), "valid_hours": int(len(ok))}
    out["ready"] = span >= MIN_SPAN_DAYS and len(ok) >= sum(MIN_ROWS) + 3 * HORIZON
    out["message"] = ("" if out["ready"] else
                      f"Collecting data: {span} day(s) of history and {len(ok)} usable hours so far. "
                      f"At least {MIN_SPAN_DAYS} days and about {sum(MIN_ROWS)} usable hours are needed before a forecast is tested on this site.")
    return out


# ------------------------------------------------------------ features

def make_features(h, states):
    F = pd.DataFrame(index=h.index)
    for s in states:
        x = h[s]
        F[s] = x
        for k in (1, 3, 6, 24):
            F["%s_d%d" % (s, k)] = x - x.shift(k)
        for w in (6, 24):
            r = x.rolling(w, min_periods=w)
            F["%s_m%d" % (s, w)] = r.mean()
            F["%s_sd%d" % (s, w)] = r.std()
    hr = h.index.hour.values
    F["hsin"] = np.sin(2 * np.pi * hr / 24)
    F["hcos"] = np.cos(2 * np.pi * hr / 24)
    return F


def split_masks(index, valid):
    # chronological 60 / 20 / 20 of the valid rows, with a gap of HORIZON hours so no target looks into the next part
    vi = index[valid]
    n = len(vi)
    t1, t2 = vi[int(0.6 * n)], vi[int(0.8 * n)]
    gap = pd.Timedelta(hours=HORIZON)
    tr = valid & (index < t1 - gap)
    va = valid & (index >= t1) & (index < t2 - gap)
    te = valid & (index >= t2)
    return tr, va, te


def diurnal_profile(x, train_mask):
    # average shape of the day (daily mean removed), built from training hours only
    s = x[train_mask]
    anom = s - s.rolling(24, center=True, min_periods=18).mean()
    return anom.groupby(anom.index.hour).mean().reindex(range(24)).fillna(0.0).values


def rmse(a, b):
    return float(np.sqrt(np.mean((np.asarray(a) - np.asarray(b)) ** 2)))


# ------------------------------------------------------------ DO forecast

def do_forecast(h):
    out = {"name": "DO forecast", "horizon_h": HORIZON}
    r = readiness(h)
    if not r["ready"]:
        out.update(status="collecting", message=r["message"])
        return out
    states = [c for c in ("do_sat", "temperature", "ph", "logturb") if c in h and h[c].notna().sum() > 50]
    F = make_features(h, states)
    y = h["do_sat"].shift(-HORIZON) - h["do_sat"]
    valid = (F.notna().all(axis=1) & y.notna()).values
    tr, va, te = split_masks(h.index, valid)
    if tr.sum() < MIN_ROWS[0] or va.sum() < MIN_ROWS[1] or te.sum() < MIN_ROWS[2]:
        out.update(status="collecting", message="There are enough days but too few complete hours in a row to test a forecast yet.")
        return out
    prof = diurnal_profile(h["do_sat"], pd.Series(tr, index=h.index))
    hr = h.index.hour.values
    diur = prof[(hr + HORIZON) % 24] - prof[hr % 24]
    yv = y.values
    lvl = h["do_sat"][tr].groupby(h.index[tr].hour).mean().reindex(range(24)).interpolate(limit_direction="both").values
    base = {"persistence": np.zeros(len(h)), "daily_shape": diur, "hourly_mean": lvl[(hr + HORIZON) % 24] - h["do_sat"].values}
    scores = {}
    for nm, p in base.items():
        scores[nm] = {"val": rmse(yv[va], p[va]), "test": rmse(yv[te], p[te])}
    cols = list(F.columns)
    X = F.values
    models = {}
    sc = StandardScaler().fit(X[tr])
    rg = Ridge(alpha=10.0).fit(sc.transform(X[tr]), yv[tr])
    models["ridge"] = (lambda M, rg=rg, sc=sc: rg.predict(sc.transform(M)))
    best_iter = None
    if xgb is not None:
        xm = xgb.XGBRegressor(n_estimators=300, learning_rate=0.05, max_depth=3, subsample=0.8, colsample_bytree=0.8,
                              min_child_weight=5, early_stopping_rounds=30, random_state=0, n_jobs=1)
        xm.fit(X[tr], yv[tr], eval_set=[(X[va], yv[va])], verbose=False)
        best_iter = int(xm.best_iteration) + 1
        models["xgboost"] = xm.predict
    for nm, f in models.items():
        p = np.full(len(h), np.nan)
        p[va | te] = f(X[va | te])
        scores[nm] = {"val": rmse(yv[va], p[va]), "test": rmse(yv[te], p[te])}
        base[nm] = p
    best_base = min(("persistence", "daily_shape", "hourly_mean"), key=lambda k: scores[k]["val"])
    cand = [k for k in models]
    best_model = min(cand, key=lambda k: scores[k]["val"])
    adopt = (scores[best_model]["val"] <= (1 - BEAT_BY) * scores[best_base]["val"] and
             scores[best_model]["test"] <= (1 - BEAT_BY) * scores[best_base]["test"])
    used = best_model if adopt else best_base
    # the forecast for the newest hour: refit the chosen model on every usable hour
    last = F.index[F.notna().all(axis=1).values][-1]
    xnow = F.loc[[last]].values
    if used == "persistence":
        d = 0.0
    elif used == "daily_shape":
        d = float(prof[(last.hour + HORIZON) % 24] - prof[last.hour % 24])
    elif used == "hourly_mean":
        d = float(lvl[(last.hour + HORIZON) % 24] - h.loc[last, "do_sat"])
    elif used == "ridge":
        sc2 = StandardScaler().fit(X[valid])
        d = float(Ridge(alpha=10.0).fit(sc2.transform(X[valid]), yv[valid]).predict(sc2.transform(xnow))[0])
    else:
        xm2 = xgb.XGBRegressor(n_estimators=best_iter or 100, learning_rate=0.05, max_depth=3, subsample=0.8,
                               colsample_bytree=0.8, min_child_weight=5, random_state=0, n_jobs=1)
        xm2.fit(X[valid], yv[valid])
        d = float(xm2.predict(xnow)[0])
    resid = (yv[te] - np.asarray(base[used])[te]) if used in base else np.array([0.0])
    lo_q, hi_q = (np.percentile(resid, 5), np.percentile(resid, 95)) if len(resid) > 20 else (-2.0, 2.0)
    now = float(h.loc[last, "do_sat"])
    sat_now = float(h.loc[last, "do_sat_mgl"])
    out.update(status="ready", used=used, adopted_model=bool(adopt), best_model=best_model, best_baseline=best_base,
               scores={k: {a: round(b, 3) for a, b in v.items()} for k, v in scores.items()},
               rows={"train": int(tr.sum()), "val": int(va.sum()), "test": int(te.sum())},
               as_of=last, data_end=h.index.max(), now_pct=now, pred_pct=now + d, lo_pct=now + d + lo_q, hi_pct=now + d + hi_q,
               now_mgl=now / 100 * sat_now, pred_mgl=(now + d) / 100 * sat_now, lo_mgl=(now + d + lo_q) / 100 * sat_now,
               hi_mgl=(now + d + hi_q) / 100 * sat_now,
               gain_vs_best_baseline_test=round(1 - scores[best_model]["test"] / scores[best_base]["test"], 3))
    return out


# ------------------------------------------------------------ turbidity rise warning

def turbidity_events(t):
    # rise above the past 30 day median that is bigger than normal wobble (past data only)
    med = t.shift(1).rolling(720, min_periods=24).median()
    dev = (t - med).abs()
    mad = dev.shift(1).rolling(720, min_periods=24).median() * 1.4826
    return ((t - med) > np.maximum(RISE_MIN_NTU, 3 * mad)).where(t.notna() & med.notna() & mad.notna())


def best_f1_threshold(y, s):
    best, thr = -1.0, float(np.max(s))
    for q in np.unique(np.quantile(s, np.linspace(0.5, 0.995, 60))):
        f = f1_score(y, s >= q, zero_division=0)
        if f > best:
            best, thr = f, float(q)
    return thr


def turbidity_warning(h):
    out = {"name": "Turbidity rise warning", "horizon_h": HORIZON}
    if "turbidity" not in h or h["turbidity"].notna().sum() < 200:
        out.update(status="collecting", message="No turbidity history yet.")
        return out
    r = readiness(h)
    if not r["ready"]:
        out.update(status="collecting", message=r["message"])
        return out
    ev = turbidity_events(h["turbidity"])
    fut = pd.concat([ev.shift(-k) for k in range(1, HORIZON + 1)], axis=1)
    anyfut = fut.max(axis=1).where(fut.notna().all(axis=1))
    y = ((anyfut > 0) & (ev == 0)).astype(float)
    ok_row = anyfut.notna() & ev.notna() & (ev == 0)
    states = [c for c in ("logturb", "do_sat", "temperature", "ph") if c in h and h[c].notna().sum() > 50]
    F = make_features(h, states)
    valid = (ok_row & F.notna().all(axis=1)).values
    if valid.sum() < sum(MIN_ROWS):
        out.update(status="collecting", message="Too few complete hours to test a warning yet.")
        return out
    tr, va, te = split_masks(h.index, valid)
    yy = y.values
    n_tv, n_te = int(yy[tr | va].sum()), int(yy[te].sum())
    out["events"] = {"train_val": n_tv, "test": n_te}
    if n_tv < MIN_EVENTS_TRAIN_VAL or n_te < MIN_EVENTS_TEST:
        out.update(status="too_few_events",
                   message=f"Only {n_tv} turbidity rises in the earlier data and {n_te} in the latest part. "
                           f"At least {MIN_EVENTS_TRAIN_VAL} and {MIN_EVENTS_TEST} are needed to test a warning, so none is shown yet.")
        return out
    X = F.values
    scores, preds = {}, {}
    rule = F["logturb_d3"].values
    preds["rule"] = rule
    sc = StandardScaler().fit(X[tr])
    lg = LogisticRegression(C=0.3, class_weight="balanced", max_iter=500).fit(sc.transform(X[tr]), yy[tr])
    p = np.full(len(h), np.nan)
    p[va | te] = lg.predict_proba(sc.transform(X[va | te]))[:, 1]
    preds["logistic"] = p
    if xgb is not None:
        pos = max(float(yy[tr].sum()), 1.0)
        xm = xgb.XGBClassifier(n_estimators=300, learning_rate=0.05, max_depth=3, subsample=0.8, colsample_bytree=0.8,
                               min_child_weight=3, scale_pos_weight=float((tr.sum() - pos) / pos), eval_metric="aucpr",
                               early_stopping_rounds=30, random_state=0, n_jobs=1)
        xm.fit(X[tr], yy[tr], eval_set=[(X[va], yy[va])], verbose=False)
        p2 = np.full(len(h), np.nan)
        p2[va | te] = xm.predict_proba(X[va | te])[:, 1]
        preds["xgboost"] = p2
    for nm, s in preds.items():
        scores[nm] = {"val": float(average_precision_score(yy[va], s[va])), "test": float(average_precision_score(yy[te], s[te]))}
    base_rate = float(yy[te].mean())
    cands = [k for k in preds if k != "rule"]
    best = max(cands, key=lambda k: scores[k]["val"])
    adopt = (scores[best]["val"] >= 1.1 * scores["rule"]["val"] and scores[best]["test"] >= 1.1 * scores["rule"]["test"]
             and scores[best]["test"] >= 2 * base_rate)
    used = best if adopt else "rule"
    useful = scores[used]["test"] >= 2 * base_rate
    out.update(used=used, adopted_model=bool(adopt), best_model=best, base_rate_test=round(base_rate, 3),
               scores={k: {a: round(b, 3) for a, b in v.items()} for k, v in scores.items()})
    if not useful:
        out.update(status="not_useful",
                   message="On this site's latest data the warning was not clearly better than guessing, so no warning is shown.")
        return out
    s_used = preds[used]
    thr = best_f1_threshold(yy[va], s_used[va])
    flag = s_used[te] >= thr
    out["test_precision"] = round(float(precision_score(yy[te], flag, zero_division=0)), 3)
    out["test_recall"] = round(float(recall_score(yy[te], flag, zero_division=0)), 3)
    # current state
    last = F.index[F.notna().all(axis=1).values][-1]
    if used == "rule":
        now_score = float(F.loc[last, "logturb_d3"])
    elif used == "logistic":
        sc2 = StandardScaler().fit(X[tr | va])
        lg2 = LogisticRegression(C=0.3, class_weight="balanced", max_iter=500).fit(sc2.transform(X[tr | va]), yy[tr | va])
        now_score = float(lg2.predict_proba(sc2.transform(F.loc[[last]].values))[:, 1][0])
    else:
        now_score = float(xm.predict_proba(F.loc[[last]].values)[:, 1][0])
    out.update(status="ready", as_of=last, score=now_score, threshold=thr, elevated=bool(now_score >= thr),
               already_high=bool(ev.get(last, 0) == 1))
    return out


# ------------------------------------------------------------ SINDy (own small version)

def stlsq(Theta, y, thr, alpha=1e-3, iters=10):
    scale = np.sqrt((Theta ** 2).mean(axis=0))
    scale[scale == 0] = 1.0
    A = Theta / scale
    p = A.shape[1]
    active = np.ones(p, dtype=bool)
    coef = np.zeros(p)
    for _ in range(iters):
        Aa = A[:, active]
        ca = np.linalg.solve(Aa.T @ Aa + alpha * len(A) * np.eye(Aa.shape[1]), Aa.T @ y)
        coef = np.zeros(p)
        coef[active] = ca
        small = np.abs(coef) < thr
        new = active & ~small
        if new.sum() == active.sum() or not new.any():
            coef[small] = 0
            break
        active = new
    coef[~active] = 0
    return coef / scale


def sindy_library(Z, hours, kind, names):
    n = len(Z)
    cols, nm = [np.ones(n)], ["1"]
    if kind == "coupled":
        for i, s in enumerate(names):
            cols.append(Z[:, i])
            nm.append(s)
    cols += [np.sin(2 * np.pi * hours / 24), np.cos(2 * np.pi * hours / 24)]
    nm += ["sin24", "cos24"]
    return np.column_stack(cols), nm


def sindy_fit(h, states, kind, thr, mask):
    X = h[states]
    nxt = X.shift(-1)
    ok = (X.notna().all(axis=1) & nxt.notna().all(axis=1) & mask).values
    Xt, Xn = X.values[ok], nxt.values[ok]
    mean, std = Xt.mean(axis=0), Xt.std(axis=0)
    std[std == 0] = 1.0
    step = (Xn - Xt).std(axis=0)
    step[step == 0] = 1.0
    Z = (Xt - mean) / std
    T, names = sindy_library(Z, h.index.hour.values[ok], kind, states)
    coef = np.column_stack([stlsq(T, (Xn[:, k] - Xt[:, k]) / step[k], thr) for k in range(len(states))])
    return {"coef": coef, "names": names, "mean": mean, "std": std, "step": step, "kind": kind, "states": states,
            "thr": thr, "lo": Xt.min(axis=0), "hi": Xt.max(axis=0), "n": int(ok.sum())}


def sindy_rollout(m, x0, hour0, H):
    x = x0.copy()
    out = np.zeros((len(x), H, x.shape[1]))
    span = m["hi"] - m["lo"]
    lo, hi = m["lo"] - 0.5 * span, m["hi"] + 0.5 * span
    for k in range(H):
        T, _ = sindy_library((x - m["mean"]) / m["std"], (hour0 + k) % 24, m["kind"], m["states"])
        x = np.clip(x + (T @ m["coef"]) * m["step"], lo, hi)
        out[:, k, :] = x
    return out


def sindy_eval(h, m, states, mask, prof, lvl):
    X = h[states].values
    ok = ~np.isnan(X).any(axis=1)
    run = pd.Series(ok.astype(int)).rolling(HORIZON + 1).sum().values == HORIZON + 1   # window ending at i
    starts = [i - HORIZON for i in range(HORIZON, len(h)) if run[i] and mask[i - HORIZON]][::3]
    if len(starts) < 20:
        return None
    starts = np.array(starts)
    truth = X[starts + HORIZON]
    hr = h.index.hour.values[starts]
    pred = sindy_rollout(m, X[starts], hr, HORIZON)[:, -1, :]
    pers = X[starts]
    diur = X[starts] + (prof[(hr + HORIZON) % 24] - prof[hr % 24])
    clim = lvl[(hr + HORIZON) % 24]
    sd = m["std"]
    f = lambda a: float(np.mean(np.sqrt(((a - truth) ** 2).mean(axis=0)) / sd))
    return {"sindy": f(pred), "persistence": f(pers), "daily_shape": f(diur), "hourly_mean": f(clim), "n": int(len(starts))}


def sindy_block(h, kind_water):
    out = {"name": "SINDy daily-pattern model"}
    r = readiness(h)
    if not r["ready"]:
        out.update(status="collecting", message=r["message"])
        return out
    states = [c for c in ("temperature", "do_sat", "ph", "logturb") if c in h and h[c].notna().sum() > 100]
    if kind_water == "freshwater" and "tds" in h and h["tds"].notna().sum() > 100:
        states.append("tds")
    ok = h[states].notna().all(axis=1).values
    if ok.sum() < sum(MIN_ROWS) or len(states) < 2:
        out.update(status="collecting", message="Too few complete hours to fit the model yet.")
        return out
    tr, va, te = split_masks(h.index, ok)
    prof = np.column_stack([diurnal_profile(h[s], pd.Series(tr, index=h.index)) for s in states])
    lvl = np.column_stack([h[s][tr].groupby(h.index[tr].hour).mean().reindex(range(24)).interpolate(limit_direction="both").values for s in states])
    best = None
    for kind in ("driver_only", "coupled"):
        for thr in (0.02, 0.05, 0.1, 0.2):
            m = sindy_fit(h, states, kind, thr, pd.Series(tr, index=h.index))
            e = sindy_eval(h, m, states, va, prof, lvl)
            if e is None:
                continue
            if best is None or e["sindy"] < best[0]:
                best = (e["sindy"], m)
    if best is None:
        out.update(status="collecting", message="Too few clean stretches to test the model yet.")
        return out
    m = best[1]
    et = sindy_eval(h, m, states, te, prof, lvl)
    if et is None:
        out.update(status="collecting", message="Too few clean stretches in the latest part to test the model yet.")
        return out
    beats = et["sindy"] <= (1 - BEAT_BY) * min(et["persistence"], et["daily_shape"], et["hourly_mean"])
    # daily swing from the driver terms only, fitted on everything usable
    md = sindy_fit(h, states, "driver_only", 0.0, pd.Series(ok, index=h.index))
    swing = {}
    hrs = np.arange(24)
    for k, s in enumerate(states):
        d = ((md["coef"][1, k] * np.sin(2 * np.pi * hrs / 24) + md["coef"][2, k] * np.cos(2 * np.pi * hrs / 24)) * md["step"][k])
        curve = np.concatenate([[0.0], np.cumsum(d)[:-1]])
        curve = curve - curve.mean()
        swing[s] = {"swing": float(curve.max() - curve.min()), "peak_hour_utc": int(curve.argmax()), "low_hour_utc": int(curve.argmin())}
    eqs = {}
    for k, s in enumerate(states):
        t = [("%.3g*%s" % (m["coef"][i, k], m["names"][i])) for i in range(len(m["names"])) if m["coef"][i, k] != 0]
        eqs[s] = " + ".join(t) if t else "0"
    curves = {}
    for k, s_ in enumerate(states):
        d = ((md["coef"][1, k] * np.sin(2 * np.pi * hrs / 24) + md["coef"][2, k] * np.cos(2 * np.pi * hrs / 24)) * md["step"][k])
        c = np.concatenate([[0.0], np.cumsum(d)[:-1]])
        curves[s_] = [float(v) for v in (c - c.mean())]
    out.update(status="ready", states=states, family=m["kind"], thr=m["thr"], beats_baselines=bool(beats),
               test_error={k: round(v, 3) for k, v in et.items() if k != "n"}, test_starts=et["n"],
               daily_swing=swing, equations=eqs, daily_curve=curves)
    return out


def sindy_expected(h, s_out):
    # expected value = centred 24 h average of what was measured + the learned daily curve for that hour
    exp = pd.DataFrame(index=h.index)
    for s in s_out["states"]:
        curve = np.array(s_out["daily_curve"][s])
        exp[s] = h[s].rolling(24, center=True, min_periods=18).mean() + curve[h.index.hour.values]
    return exp


def sindy_deviations(h, s_out, z=3.0, min_hours=3):
    # stretches where a value stayed far from the learned daily pattern (experimental: not tested against known events)
    out = []
    if s_out.get("status") != "ready":
        return out
    exp = sindy_expected(h, s_out)
    for st_ in ("do_sat", "ph", "logturb"):
        if st_ not in s_out["states"]:
            continue
        r = h[st_] - exp[st_]
        med = r.median()
        sigma = max(1.4826 * float((r - med).abs().median()), 1e-6)
        zz = (r - med) / sigma
        sign = np.sign(zz.where(zz.abs() > z)).fillna(0).values
        i = 0
        while i < len(sign):
            if sign[i] == 0:
                i += 1
                continue
            j = i
            while j + 1 < len(sign) and sign[j + 1] == sign[i]:
                j += 1
            if j - i + 1 >= min_hours:
                seg = zz.iloc[i:j + 1]
                out.append({"state": st_, "start": h.index[i], "end": h.index[j], "hours": j - i + 1,
                            "direction": "above" if sign[i] > 0 else "below", "max_z": float(seg.abs().max()),
                            "observed": float(h[st_].iloc[i:j + 1].mean()), "expected": float(exp[st_].iloc[i:j + 1].mean())})
            i = j + 1
    out.sort(key=lambda e: e["start"])
    return out


# ------------------------------------------------------------ Water Health Index on CPCB / BIS limits

WHI_PAIRS = {
    "freshwater": {"do>ph": 2, "do>turbidity": 3, "do>tds": 3, "ph>turbidity": 2, "ph>tds": 2, "turbidity>tds": 1},
    "coastal": {"do>ph": 2, "do>turbidity": 3, "ph>turbidity": 2},
}
WHI_SOURCE = {
    "freshwater": "CPCB designated-best-use classes (DO, pH, TDS) and BIS IS 10500 (turbidity)",
    "coastal": "CPCB coastal-water classes SW-I to SW-V (DO against the larger of the mg/L value and the % saturation, pH, turbidity); TDS is natural salt and is not scored",
}
MIN_PARAMS = 3


def ahp(params, pairs):
    n = len(params)
    ix = {p: i for i, p in enumerate(params)}
    A = np.ones((n, n))
    for k, v in pairs.items():
        a, b = k.split(">")
        if a in ix and b in ix:
            A[ix[a], ix[b]] = v
            A[ix[b], ix[a]] = 1.0 / v
    vals, vecs = np.linalg.eig(A)
    w = np.abs(vecs[:, np.argmax(vals.real)].real)
    return pd.Series(w / w.sum(), index=params)


def grade_hourly(h, kind):
    # score (0 to 100) and colour tier (1 green to 4 red) of every graded parameter, hour by hour
    S, T = pd.DataFrame(index=h.index), pd.DataFrame(index=h.index)
    sat = h["do_sat_mgl"].values if "do_sat_mgl" in h else None
    for p in std.graded(kind):
        if p not in h:
            continue
        t, sc = std.grade(p, h[p].values, kind, sat)
        S[p], T[p] = sc, t
    return S, T


def weights_for(params, group):
    """Weights of the graded parameters, adding up to 1. The project's own weights (config.WHI_WEIGHTS) are used when the
    project has them for every graded parameter; otherwise placeholder weights from a pairwise comparison."""
    try:
        from . import config
        raw = {p: float(config.WHI_WEIGHTS[p]) for p in params}
        tot = sum(v for v in raw.values() if v > 0)
        if tot > 0 and all(v >= 0 for v in raw.values()):
            return pd.Series({p: raw[p] / tot for p in params}), "the project's own weights (config.WHI_WEIGHTS)"
    except Exception:
        pass
    return ahp(list(params), WHI_PAIRS[group]), "placeholder weights from a pairwise comparison (not yet confirmed by experts)"


def whi_table(h, kind):
    # Water Health Index = weighted AVERAGE of the parameter scores (0 to 100). HIGHER IS BETTER.
    S, T = grade_hourly(h, kind)
    g = std.group(kind)
    w, _ = weights_for(list(S.columns), g)
    W = S.notna().mul(w, axis=1)
    tot = W.sum(axis=1).replace(0, np.nan)
    whi = (S.fillna(0.0) * W).sum(axis=1) / tot
    whi[S.notna().sum(axis=1) < MIN_PARAMS] = np.nan
    return S, whi, w, WHI_SOURCE[g]


def whi_frame(h, kind):
    # hourly table: index value, worst colour, the limiting parameter, and every parameter's colour
    S, whi, w, src = whi_table(h, kind)
    _, T = grade_hourly(h, kind)
    ok = S.notna().sum(axis=1) >= MIN_PARAMS
    worst = T.max(axis=1).where(ok)
    key = (T.fillna(-1) * 1000 + (100 - S.fillna(100)))
    limiting = key.idxmax(axis=1).where(ok & worst.notna())
    f = pd.DataFrame({"whi": whi, "worst_tier": worst, "limiting": limiting})
    for p in S.columns:
        f[p + "_tier"], f[p + "_score"] = T[p], S[p]
    return f, w, src


def whi_block(h, kind, start=None, end=None):
    out = {"name": "Water Health Index", "kind": kind}
    f, w, src = whi_frame(h, kind)
    S, _ = grade_hourly(h, kind)
    if start is not None:
        sel = (h.index >= start) & (h.index <= end)
        f, S = f[sel], S[sel]
    ok = f["whi"].notna()
    if ok.sum() == 0:
        out.update(status="no_data", message="No hours with enough valid sensors in this period.")
        return out
    fv = f[ok]
    params = list(S.columns)
    share = {t: float((fv["worst_tier"] == t).mean()) for t in (1, 2, 3, 4)}
    pshare = {}
    for p in params:
        tv = f.loc[f[p + "_tier"].notna(), p + "_tier"]
        pshare[p] = {t: float((tv == t).mean()) for t in (1, 2, 3, 4)} if len(tv) else {t: 0.0 for t in (1, 2, 3, 4)}
    limiting_share = fv.loc[fv["worst_tier"] >= 2, "limiting"].value_counts(normalize=True)
    # overall band from the NUMBER (higher is better). Parameter colours are kept apart as alerts.
    bidx = fv["whi"].map(std.band_index)
    nb = len(std.bands())
    band_share = {std.bands()[i][1]: float((bidx == i).mean()) for i in range(nb)}
    mean_whi = float(fv["whi"].mean())
    alert_hours = fv["worst_tier"] >= 3
    out.update(band_mean=std.band_name(mean_whi), band_share=band_share, alert_share=float(alert_hours.mean()),
               red_share=float((fv["worst_tier"] >= 4).mean()))
    out.update(status="ready", hours=int(ok.sum()), mean=float(fv["whi"].mean()), lowest=float(fv["whi"].min()),
               p05=float(fv["whi"].quantile(0.05)), sub_means={p: float(S[p].mean()) for p in params},
               weakest_share={p: float(v) for p, v in limiting_share.items()}, weights={p: float(v) for p, v in w.items()},
               weight_source=weights_for(params, std.group(kind))[1],
               source=src, series=f["whi"], subindex=S, frame=f, worst_share=share, param_share=pshare,
               common_tier=int(max(share, key=share.get)), params=params)
    return out


def latest_grading(h, kind):
    # the newest hour with enough valid sensors, with each parameter's value, colour and the limiting parameter
    f, w, src = whi_frame(h, kind)
    ok = f["whi"].notna()
    if not ok.any():
        return None
    ts = f.index[ok][-1]
    row = f.loc[ts]
    params = [c[:-5] for c in f.columns if c.endswith("_tier") and c != "worst_tier"]
    return {"as_of": ts, "whi": float(row["whi"]), "worst_tier": int(row["worst_tier"]), "limiting": row["limiting"],
            "values": {p: (float(h.loc[ts, p]) if p in h and not np.isnan(h.loc[ts, p]) else None) for p in params},
            "tiers": {p: (None if np.isnan(row[p + "_tier"]) else int(row[p + "_tier"])) for p in params},
            "scores": {p: (None if np.isnan(row[p + "_score"]) else float(row[p + "_score"])) for p in params},
            "data_end": h.index.max(), "kind": kind}


# ------------------------------------------------------------ everything together

def build_models(df, kind=None, end=None):
    # the three trained pieces. They depend on the history up to `end` only, so one run serves any report period
    ts = pd.to_datetime(df["timestamp"], utc=True)
    if end is not None:
        df = df[ts <= pd.Timestamp(end)]
    h = add_columns(hourly_table(df))
    if len(h) < 2:
        return {"error": "There are no usable readings yet."}
    kind = kind or kind_from_tds(h)
    sd = sindy_block(h, kind)
    sd["deviations"] = sindy_deviations(h, sd) if sd.get("status") == "ready" else []
    return {"kind": kind, "hours": h, "do": do_forecast(h), "turb": turbidity_warning(h), "sindy": sd, "end": end}


def attach_whi(models, start=None, end=None):
    if "error" in models:
        return models
    out = dict(models)
    out.update(whi=whi_block(models["hours"], models["kind"], start, end), start=start, end=end)
    return out


def build_insights(df, kind=None, start=None, end=None):
    return attach_whi(build_models(df, kind, end), start, end)
