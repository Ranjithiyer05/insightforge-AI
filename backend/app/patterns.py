"""Pattern modules: anomalies, forecasts and segments (clusters), each with honest checks.

- Anomalies: Isolation Forest over numeric columns (row-level), and robust
  z-scores on a time series (period-level). Every flagged row lists the values
  that make it unusual. "Unusual" is not "wrong".
- Forecast: Holt-Winters / linear trend / seasonal naive, chosen on a holdout
  of the latest periods and compared with a naive forecast. Intervals come
  from holdout errors. If no model beats naive, that is reported.
- Segments: k-means on scaled features with k chosen by silhouette score; a
  weak silhouette is reported as "no clear segments".
"""
from __future__ import annotations

import warnings
from typing import Any

import numpy as np
import pandas as pd

from .eda import _f, pick_date, pick_measure

SEED = 42
FREQ = {"day": "D", "week": "W", "month": "MS", "quarter": "QS", "year": "YS"}
SEASON = {"D": 7, "W": 52, "MS": 12, "QS": 4, "YS": 1}


class PatternError(ValueError):
    pass


def _numeric_cols(df: pd.DataFrame, profile: dict[str, Any]) -> list[str]:
    ids = set(profile.get("identifier_columns", []) or [])
    return [c for c in profile.get("numeric_columns", []) if c in df.columns and c not in ids]


def anomalies(df: pd.DataFrame, profile: dict[str, Any], columns: list[str] | None = None, contamination: float = 0.01, top: int = 50) -> dict[str, Any]:
    from sklearn.ensemble import IsolationForest
    cols = [c for c in (columns or _numeric_cols(df, profile)) if c in df.columns]
    if not cols:
        raise PatternError("Anomaly detection needs at least one numeric column.")
    X = df[cols].apply(pd.to_numeric, errors="coerce")
    ok = X.notna().all(axis=1)
    if ok.sum() < 50:
        raise PatternError("At least 50 complete rows are needed.")
    Xo = X[ok]
    sample = Xo.sample(min(len(Xo), 50_000), random_state=SEED)
    iso = IsolationForest(n_estimators=200, contamination=contamination, random_state=SEED).fit(sample)
    score = -iso.score_samples(Xo)  # higher = more unusual
    flag = iso.predict(Xo) == -1
    med, mad = Xo.median(), (Xo - Xo.median()).abs().median().replace(0, np.nan)
    rz = ((Xo - med) / (1.4826 * mad)).fillna(0)
    order = np.argsort(-score)
    rows = []
    for i in order[: min(top, int(flag.sum()))]:
        idx = Xo.index[i]
        reasons = rz.loc[idx].abs().sort_values(ascending=False)
        why = [f"{c} = {_f(Xo.at[idx, c], 4)} ({'above' if rz.at[idx, c] > 0 else 'below'} typical by {abs(rz.at[idx, c]):.1f} robust SD)" for c in reasons.index[:3] if abs(reasons[c]) >= 2]
        rows.append({"row": int(idx) + 1, "score": _f(float(score[i]), 4), "why": why or ["Unusual combination of values rather than one extreme value."],
                     **{c: _f(df.at[idx, c], 6) for c in cols[:8]}})
    out: dict[str, Any] = {"columns": cols, "rows_checked": int(ok.sum()), "rows_skipped_missing": int((~ok).sum()), "flagged": int(flag.sum()),
                           "contamination": contamination, "top": rows,
                           "scatter": None, "method": "Isolation Forest (200 trees) on the listed numeric columns; reasons use robust z-scores (median and MAD).",
                           "caveat": f"The model flags about {contamination:.0%} of rows by design. Flagged rows are unusual, not necessarily errors; review them before removing anything."}
    if len(cols) >= 2:
        pick = Xo.sample(min(len(Xo), 1500), random_state=SEED)
        fl = pd.Series(flag, index=Xo.index).loc[pick.index]
        out["scatter"] = {"x": cols[0], "y": cols[1], "points": [{"x": _f(a, 5), "y": _f(b, 5), "group": "anomaly" if f else "normal"}
                                                                  for a, b, f in zip(pick[cols[0]], pick[cols[1]], fl)]}
    # period-level anomalies on the main measure
    date, measure = pick_date(profile), pick_measure(profile)
    if date and measure:
        when = pd.to_datetime(df[date], errors="coerce", format="mixed")
        s = pd.to_numeric(df[measure], errors="coerce").groupby(when.dt.to_period("D").astype(str)).sum()
        s = s[s.index != "NaT"]
        if len(s) >= 30:
            roll = s.rolling(14, min_periods=7, center=True)
            med_ = roll.median()
            mad_ = (s - med_).abs().rolling(14, min_periods=7, center=True).median().replace(0, np.nan)
            z = ((s - med_) / (1.4826 * mad_)).dropna()
            hits = z[z.abs() >= 4].sort_values(key=abs, ascending=False).head(15)
            out["periods"] = {"measure": measure, "date": date, "threshold": 4,
                              "series": [{"period": k, "value": _f(v, 4), "flag": bool(k in hits.index)} for k, v in s.items()][-400:],
                              "hits": [{"period": k, "value": _f(s[k], 4), "typical": _f(med_[k], 4), "z": _f(v, 3)} for k, v in hits.items()],
                              "method": f"Daily total of {measure} compared with the median of the surrounding 14 days; flagged when more than 4 robust SD away."}
    return out


def _fc(series: pd.Series, steps: int, strategy: str, season: int) -> np.ndarray:
    if strategy == "naive":
        return np.repeat(series.iloc[-1], steps)
    if strategy == "seasonal_naive":
        if len(series) < season or season < 2:
            return np.repeat(series.iloc[-1], steps)
        return np.array([series.iloc[-season + (i % season)] for i in range(steps)])
    if strategy == "linear_trend":
        t = np.arange(len(series))
        coef = np.polyfit(t, series.to_numpy(), 1)
        return np.polyval(coef, np.arange(len(series), len(series) + steps))
    from statsmodels.tsa.holtwinters import ExponentialSmoothing
    seasonal = "add" if season >= 2 and len(series) >= 2 * season else None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m = ExponentialSmoothing(series.to_numpy(), trend="add", seasonal=seasonal, seasonal_periods=season if seasonal else None,
                                 initialization_method="estimated").fit()
    return m.forecast(steps)


def forecast(df: pd.DataFrame, profile: dict[str, Any], date_col: str | None = None, measure: str | None = None, grain: str = "month",
             agg: str = "sum", horizon: int | None = None) -> dict[str, Any]:
    date_col = date_col or pick_date(profile)
    measure = measure if measure is not None else pick_measure(profile)
    if not date_col or date_col not in df.columns:
        raise PatternError("Forecasting needs a date column.")
    if grain not in FREQ:
        raise PatternError("Grain must be day, week, month, quarter or year.")
    freq = FREQ[grain]
    when = pd.to_datetime(df[date_col], errors="coerce", format="mixed")
    if measure:
        vals = pd.to_numeric(df[measure], errors="coerce")
        frame = pd.DataFrame({"t": when, "v": vals}).dropna()
        s = frame.set_index("t")["v"].resample(freq).agg(agg)
        counts = frame.set_index("t")["v"].resample(freq).count()
    else:
        frame = pd.DataFrame({"t": when}).dropna().assign(v=1)
        s = counts = frame.set_index("t")["v"].resample(freq).count()
        agg = "count"
    notes = []
    if len(counts) > 3 and counts.iloc[-1] < 0.6 * counts.iloc[:-1].median():
        s = s.iloc[:-1]
        notes.append("The latest period looked incomplete (far fewer records than usual) and was left out.")
    s = s.astype(float)
    n = len(s)
    if n < 8:
        raise PatternError(f"Only {n} {grain}s of data after aggregation; at least 8 are needed to test a forecast on held-out periods.")
    season = SEASON[freq]
    h = horizon or min(6, max(2, n // 5))
    hold = min(h, max(2, n // 4))
    train, test = s.iloc[:-hold], s.iloc[-hold:]
    results = []
    for strat in ("naive", "seasonal_naive", "linear_trend", "holt_winters"):
        try:
            pred = _fc(train, hold, strat, season)
            err = test.to_numpy() - pred
            mae = float(np.mean(np.abs(err)))
            mape = float(np.mean(np.abs(err) / np.abs(test.to_numpy()))) * 100 if (test != 0).all() else None
            results.append({"model": strat, "mae": _f(mae, 4), "mape_pct": _f(mape, 3), "holdout_errors": [_f(e, 4) for e in err]})
        except Exception as exc:  # noqa: BLE001
            results.append({"model": strat, "error": type(exc).__name__})
    valid = [r for r in results if "mae" in r]
    best = min(valid, key=lambda r: r["mae"])
    naive_mae = next(r["mae"] for r in valid if r["model"] == "naive")
    future = _fc(s, h, best["model"], season)
    errs = np.abs(np.array(best["holdout_errors"], dtype=float))
    width = float(np.quantile(errs, 0.9)) if len(errs) >= 3 else float(errs.max())
    idx = pd.date_range(s.index[-1], periods=h + 1, freq=freq)[1:]
    fmt = {"D": "%Y-%m-%d", "W": "%Y-%m-%d", "MS": "%Y-%m", "QS": "%Y-%m", "YS": "%Y"}[freq]
    series = [{"period": t.strftime(fmt), "actual": _f(v, 4)} for t, v in s.items()]
    for t, v in zip(idx, future):
        series.append({"period": t.strftime(fmt), "forecast": _f(v, 4), "low": _f(v - width, 4), "high": _f(v + width, 4)})
    beats = best["model"] != "naive" and best["mae"] < naive_mae * 0.95
    return {
        "date_col": date_col, "measure": measure, "aggregation": agg, "grain": grain, "periods": n, "holdout": hold, "horizon": h,
        "models": results, "best_model": best["model"], "beats_naive": beats, "series": series, "interval": "Range from the 90th percentile of holdout errors (approximate).",
        "notes": notes + ([] if beats else ["No model beat the naive forecast (repeat the last value) by at least 5% on the held-out periods, so treat the forecast as a rough guide only."]),
        "method": f"Each model was fitted on all but the last {hold} {grain}s and scored on those (mean absolute error). The best one was refitted on all data.",
    }


def segments(df: pd.DataFrame, profile: dict[str, Any], columns: list[str] | None = None, k: int | None = None) -> dict[str, Any]:
    from sklearn.cluster import KMeans
    from sklearn.decomposition import PCA
    from sklearn.metrics import silhouette_score
    from sklearn.preprocessing import StandardScaler
    cols = [c for c in (columns or _numeric_cols(df, profile)) if c in df.columns]
    if len(cols) < 2:
        raise PatternError("Segmentation needs at least two numeric columns.")
    X = df[cols].apply(pd.to_numeric, errors="coerce").dropna()
    if len(X) < 50:
        raise PatternError("At least 50 complete rows are needed.")
    if len(X) > 10_000:
        X = X.sample(10_000, random_state=SEED)
    Z = StandardScaler().fit_transform(X)
    tries = []
    ks = [k] if k else range(2, 9)
    sil_sample = min(len(Z), 2000)
    best = None
    for kk in ks:
        km = KMeans(n_clusters=kk, n_init=3, random_state=SEED).fit(Z)
        sil = float(silhouette_score(Z, km.labels_, sample_size=sil_sample, random_state=SEED))
        tries.append({"k": kk, "silhouette": _f(sil, 4)})
        if best is None or sil > best[1]:
            best = (km, sil)
    km, sil = best
    labels = km.labels_
    overall = X.mean()
    prof = []
    for c in range(km.n_clusters):
        part = X[labels == c]
        z = (part.mean() - overall) / X.std().replace(0, np.nan)
        dist = z.abs().sort_values(ascending=False)
        desc = [f"{col} {'higher' if z[col] > 0 else 'lower'} ({_f(part[col].mean(), 4)} vs {_f(overall[col], 4)} overall)" for col in dist.index[:3] if abs(z[col]) >= 0.3]
        prof.append({"segment": c + 1, "rows": int(len(part)), "share": _f(len(part) / len(X), 4),
                     "means": {col: _f(part[col].mean(), 4) for col in cols}, "distinctive": desc or ["Close to the overall average on every column."]})
    pcs = PCA(2, random_state=SEED).fit(Z)
    P2 = pcs.transform(Z)
    pick = np.random.default_rng(SEED).choice(len(Z), min(len(Z), 1500), replace=False)
    strength = "clear" if sil >= 0.5 else "moderate" if sil >= 0.25 else "weak"
    return {
        "columns": cols, "rows_used": int(len(X)), "k": int(km.n_clusters), "silhouette": _f(sil, 4), "strength": strength, "tries": tries,
        "segments": sorted(prof, key=lambda p: -p["rows"]),
        "projection": [{"x": _f(P2[i, 0], 4), "y": _f(P2[i, 1], 4), "group": f"{labels[i] + 1}"} for i in pick],
        "explained_variance": [_f(v, 4) for v in pcs.explained_variance_ratio_],
        "method": "k-means on standardised columns; k chosen by the highest silhouette score (2 to 8). The chart projects rows onto the first two principal components.",
        "caveat": ("Silhouette below 0.25: the data does not split into well-separated groups, so these segments are arbitrary cut lines rather than natural groups."
                   if strength == "weak" else "Segments describe the data as it is; they are not causes and may change with different columns."),
    }
