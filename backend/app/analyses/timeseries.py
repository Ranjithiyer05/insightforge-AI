"""Forecasting with honest baselines: every model is compared to naive forecasts on a holdout."""
from __future__ import annotations

from .base import Assessment, Finding, Method, Recommendation, Stage, fmt_num, header, metric_value

CODE = r'''
import warnings
df = ifrt.load_df(parse_dates=[P["date_col"]])
d, v = P["date_col"], P["value_col"]
freq = P.get("freq") or "MS"
agg = P.get("agg", "sum")
s = df[[d, v]].dropna().set_index(d)[v].astype(float).resample(freq).agg(agg)
# drop a trailing partial period (fewer observations than typical)
counts = df[[d, v]].dropna().set_index(d)[v].resample(freq).count()
if len(counts) > 3 and counts.iloc[-1] < 0.6 * counts.iloc[:-1].median():
    s = s.iloc[:-1]
    ifrt.warn("The final period looked incomplete and was dropped before forecasting.")
n = len(s)
if n < 8:
    raise ValueError(f"Only {n} periods after aggregation; at least 8 are needed for a holdout evaluation.")
season = {"MS": 12, "M": 12, "W": 52, "W-SUN": 52, "D": 7, "QS": 4}.get(freq, 1)
h = int(P.get("horizon") or min(6, max(2, n // 5)))
train, test = s.iloc[:-h], s.iloc[-h:]
ifrt.metric("periods", n)
ifrt.metric("holdout_periods", h)
ifrt.metric("frequency", freq)

def fit_predict(series, steps, strategy):
    if strategy == "seasonal_naive":
        if len(series) < season:
            return np.repeat(series.iloc[-1], steps), None
        return np.array([series.iloc[-season + (i % season)] for i in range(steps)]), None
    if strategy == "linear_trend":
        t = np.arange(len(series))
        coef = np.polyfit(t, series.to_numpy(), 1)
        tt = np.arange(len(series), len(series) + steps)
        fitted = np.polyval(coef, t)
        return np.polyval(coef, tt), series.to_numpy() - fitted
    if strategy == "holt_winters":
        from statsmodels.tsa.holtwinters import ExponentialSmoothing
        seasonal = "add" if len(series) >= 2 * season and season > 1 else None
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            m = ExponentialSmoothing(series.to_numpy(), trend="add", seasonal=seasonal, seasonal_periods=season if seasonal else None,
                                     initialization_method="estimated").fit()
        return m.forecast(steps), series.to_numpy() - m.fittedvalues
    raise ValueError(f"unknown strategy {strategy}")

strategy = P["strategy"]
pred, _ = fit_predict(train, h, strategy)
naive = np.repeat(train.iloc[-1], h)
snaive, _ = fit_predict(train, h, "seasonal_naive")
def mae(a, b): return float(np.mean(np.abs(np.asarray(a) - np.asarray(b))))
def mape(a, b):
    a = np.asarray(a); b = np.asarray(b)
    mask = a != 0
    return float(np.mean(np.abs((a[mask] - b[mask]) / a[mask])) * 100) if mask.any() else None
ifrt.metric("mae", mae(test, pred), split=f"last {h} periods held out")
ifrt.metric("mape", mape(test, pred), unit="%")
ifrt.metric("naive_mae", mae(test, naive), note="last observed value")
ifrt.metric("seasonal_naive_mae", mae(test, snaive), note=f"same period one season ({season}) earlier")
best_baseline = min(mae(test, naive), mae(test, snaive))
ifrt.metric("skill_vs_best_baseline", 1 - mae(test, pred) / best_baseline if best_baseline else None)
ifrt.claim("mae", "Holdout MAE", mae(test, pred), {"kind": "prediction_metric", "metric": "mae", "task": "forecast"})
ifrt.artifact("predictions", {"y_true": [float(x) for x in test], "y_pred": [float(x) for x in pred]})

# Refit on all data and forecast forward, with intervals from holdout error spread.
future, resid = fit_predict(s, h, strategy)
err_sd = float(np.std(np.asarray(test) - pred, ddof=1)) if h > 1 else float(abs(test.iloc[0] - pred[0]))
idx = pd.date_range(s.index[-1], periods=h + 1, freq=freq)[1:]
rows = [{"period": str(k.date()), "actual": float(val), "type": "actual"} for k, val in s.items()]
for i, k in enumerate(test.index):
    rows[-h + i]["holdout_prediction"] = float(pred[i])
for i, k in enumerate(idx):
    rows.append({"period": str(k.date()), "forecast": float(future[i]), "lower": float(future[i] - 1.96 * err_sd * np.sqrt(i + 1)),
                 "upper": float(future[i] + 1.96 * err_sd * np.sqrt(i + 1)), "type": "forecast"})
ifrt.table("forecast", pd.DataFrame(rows))
ifrt.chart("forecast", "forecast", f"{v} ({agg} per period): history, holdout check and forecast", rows, "period",
           [{"key": "actual", "label": "Actual"}, {"key": "holdout_prediction", "label": "Holdout prediction"}, {"key": "forecast", "label": "Forecast"}],
           band=["lower", "upper"])
ifrt.metric("next_period_forecast", float(future[0]), interval95=[float(future[0] - 1.96 * err_sd), float(future[0] + 1.96 * err_sd)])
ifrt.note("Forecast intervals are approximate (based on holdout error, widening with horizon) and assume past patterns continue.")
ifrt.emit()
'''


class ForecastMethod(Method):
    key = "forecasting"
    task_type = "forecasting"
    title = "Time-series forecast"
    strategies = ["holt_winters", "linear_trend", "seasonal_naive"]
    retry_map = {"not_better_than_baseline": ["holt_winters", "seasonal_naive", "linear_trend"], "model_error": ["linear_trend", "seasonal_naive"]}

    def requirements(self, profile, params):
        miss = []
        if not params.get("date_col"):
            miss.append("a date column")
        if not params.get("value_col"):
            miss.append("a numeric value column to forecast")
        return miss

    def stages(self, params, strategy):
        return [Stage("forecast", f"Fit {strategy.replace('_', ' ')} and evaluate on a holdout against naive baselines",
                      header(params, strategy, "import numpy as np\nimport pandas as pd") + CODE,
                      "Aggregates to a regular frequency, holds out the most recent periods, and only trusts the model if it beats naive forecasts.")]

    def assess(self, result, params, strategy):
        skill = metric_value(result, "skill_vs_best_baseline")
        if metric_value(result, "mae") is None:
            return Assessment("failed", "No forecast metrics were produced.", "model_error")
        if strategy != "seasonal_naive" and (skill is None or skill <= 0):
            return Assessment("weak", f"The {strategy} forecast was not more accurate than a naive baseline on the holdout (skill {skill:.2f}).",
                              "not_better_than_baseline", ("skill_vs_best_baseline", skill))
        return Assessment("succeeded", headline_metric=("skill_vs_best_baseline", skill))

    def conditions(self, df, profile, params):
        return {"frequency": params.get("freq") or "MS"}

    def findings(self, result, params):
        mv = lambda k, d=None: metric_value(result, k, d)  # noqa: E731
        nf = result.get("metrics", {}).get("next_period_forecast", {})
        iv = nf.get("interval95", [None, None])
        F = [Finding(f"Next-period forecast for {params.get('value_col')}: {fmt_num(nf.get('value'))}",
                     f"Approximate 95% interval {fmt_num(iv[0])} to {fmt_num(iv[1])}. This is a model projection, not an observed outcome.",
                     ["next_period_forecast"], "inference", "medium"),
             Finding("Holdout accuracy versus naive baselines",
                     f"MAE {fmt_num(mv('mae'))} on the last {mv('holdout_periods')} periods vs naive {fmt_num(mv('naive_mae'))} and seasonal naive {fmt_num(mv('seasonal_naive_mae'))} "
                     f"(skill {mv('skill_vs_best_baseline', 0):+.2f}; positive means better than the best baseline).", ["mae"], "observation", "high")]
        R = [Recommendation("Re-run the forecast as new periods arrive and compare it with actual results.", "Forecast accuracy was measured on only a few holdout periods.", ["mae"])]
        L = ["Forecasts assume historical patterns continue; promotions, price changes or shocks are not modelled.", f"Accuracy was assessed on only {mv('holdout_periods')} holdout periods."]
        return F, R, L
