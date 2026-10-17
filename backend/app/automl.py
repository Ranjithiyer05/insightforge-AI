"""AutoML with leakage-safe evaluation and model explanations.

- Task is detected from the target (classification or regression) unless given.
- Identifier columns, columns flagged as possible leakage, and features that
  predict the target almost perfectly on their own are excluded and reported.
- All preprocessing lives inside a scikit-learn Pipeline, so imputation,
  scaling and encoding are learned from training folds only.
- Candidates (including a naive baseline) are compared by 5-fold
  cross-validation on the training split. Only the chosen model is scored on
  the held-out test split, once. A time-ordered split is used when requested.
- Explanations: permutation importance on the test split, sampling-based
  Shapley value estimates (Strumbelj-Kononenko permutation sampling against a
  background sample; exactly additive per sample), and partial dependence.
"""
from __future__ import annotations

import io
import time
import warnings
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier, DummyRegressor
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor, RandomForestClassifier, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.metrics import (accuracy_score, average_precision_score, balanced_accuracy_score, confusion_matrix, f1_score, mean_absolute_error,
                             mean_squared_error, precision_score, r2_score, recall_score, roc_auc_score, roc_curve)
from sklearn.model_selection import KFold, StratifiedKFold, cross_validate, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from .profiler import _finite

SEED = 42


class AutoMLError(ValueError):
    pass


def _r(x: Any, nd: int = 5) -> Any:
    v = _finite(x)
    return round(v, nd) if isinstance(v, float) else v


def detect_task(y: pd.Series) -> str:
    num = pd.to_numeric(y, errors="coerce")
    if num.notna().mean() > 0.95 and num.nunique() > 15:
        return "regression"
    return "classification"


def _prep(num: list[str], cat: list[str], scale: bool) -> ColumnTransformer:
    num_steps = [("impute", SimpleImputer(strategy="median"))] + ([("scale", StandardScaler())] if scale else [])
    return ColumnTransformer([
        ("num", Pipeline(num_steps), num),
        ("cat", Pipeline([("impute", SimpleImputer(strategy="most_frequent")),
                          ("onehot", OneHotEncoder(handle_unknown="infrequent_if_exist", min_frequency=5, sparse_output=False))]), cat),
    ])


def candidates(task: str, small: bool) -> dict[str, tuple[Any, bool, str]]:
    """name -> (estimator, needs_scaling, description)."""
    trees = 150 if small else 200
    if task == "classification":
        return {
            "baseline": (DummyClassifier(strategy="prior"), False, "Predicts class frequencies; any useful model must beat it."),
            "logistic_regression": (LogisticRegression(max_iter=2000, class_weight="balanced"), True, "Linear, class-balanced; easy to interpret."),
            "random_forest": (RandomForestClassifier(n_estimators=trees, min_samples_leaf=3, class_weight="balanced_subsample", random_state=SEED, n_jobs=1), False,
                              "Averages many decision trees; handles non-linear effects."),
            "gradient_boosting": (HistGradientBoostingClassifier(max_iter=250, learning_rate=0.06, class_weight="balanced", random_state=SEED), False,
                                  "Boosted trees; usually strongest on tabular data."),
        }
    return {
        "baseline": (DummyRegressor(strategy="mean"), False, "Predicts the training mean; any useful model must beat it."),
        "ridge_regression": (Ridge(alpha=1.0), True, "Linear with mild regularisation; easy to interpret."),
        "random_forest": (RandomForestRegressor(n_estimators=trees, min_samples_leaf=3, random_state=SEED, n_jobs=1), False, "Averages many decision trees."),
        "gradient_boosting": (HistGradientBoostingRegressor(max_iter=250, learning_rate=0.06, random_state=SEED), False, "Boosted trees."),
    }


def screen_features(df: pd.DataFrame, target: str, features: list[str], task: str, profile: dict[str, Any]) -> tuple[list[str], list[dict[str, str]]]:
    """Drop identifiers, dates, near-constant columns and features that alone predict the target almost perfectly."""
    excluded: list[dict[str, str]] = []
    ids = set(profile.get("identifier_columns", []) or []) | set((profile.get("roles", {}) or {}).get("id", []))
    dates = set(profile.get("datetime_columns", []) or [])
    flagged = {h["feature"]: h["message"] for h in profile.get("leakage_hints", []) if h.get("target") == target}
    types = {c["name"]: c.get("semantic_type") for c in profile.get("columns", [])}
    keep = []
    y = df[target]
    for f in features:
        if f == target or f not in df.columns:
            continue
        s = df[f]
        if f in ids or types.get(f) == "identifier":
            excluded.append({"feature": f, "reason": "Identifier column: unique per row, so it cannot generalise."})
            continue
        if f in dates or types.get(f) == "datetime":
            excluded.append({"feature": f, "reason": "Date column: used for the time-ordered split, not as a feature."})
            continue
        if types.get(f) == "text":
            excluded.append({"feature": f, "reason": "Free-text column: not encoded by this model."})
            continue
        if s.nunique(dropna=True) <= 1:
            excluded.append({"feature": f, "reason": "Constant column: carries no information."})
            continue
        if f in flagged:
            excluded.append({"feature": f, "reason": f"Possible leakage: {flagged[f]}"})
            continue
        # single-feature check for leakage the profiler may not have seen
        ok = y.notna() & s.notna()
        if ok.sum() >= 30:
            xs = pd.to_numeric(s[ok], errors="coerce")
            if task == "regression" and xs.notna().all():
                r = np.corrcoef(xs, pd.to_numeric(y[ok], errors="coerce"))[0, 1]
                if np.isfinite(r) and abs(r) > 0.98:
                    excluded.append({"feature": f, "reason": f"Possible leakage: correlates {r:.3f} with {target} on its own."})
                    continue
            if task == "classification" and s.nunique() > 1:
                purity = df[ok].groupby(f)[target].agg(lambda v: v.value_counts(normalize=True).iloc[0])
                sizes = df[ok].groupby(f).size()
                wp = float((purity * sizes).sum() / sizes.sum())
                base = float(y[ok].value_counts(normalize=True).iloc[0])
                if wp > 0.99 and base < 0.95 and s.nunique() < 0.5 * ok.sum():
                    excluded.append({"feature": f, "reason": f"Possible leakage: its values determine {target} {wp:.0%} of the time."})
                    continue
        keep.append(f)
    return keep, excluded


def shapley(predict, X: pd.DataFrame, background: pd.DataFrame, n_perm: int = 24, seed: int = SEED) -> tuple[np.ndarray, np.ndarray]:
    """Permutation-sampling Shapley estimates for each row of X.

    For each row, each sampled permutation walks features in order, switching
    them from a random background row to the row's own values; each feature's
    contribution is the change in prediction. Contributions of one walk sum
    exactly to f(x) - f(z). Returns (phi [rows x features], expected value per row).
    """
    rng = np.random.default_rng(seed)
    n, p = X.shape
    phi = np.zeros((n, p))
    base = np.zeros(n)
    cols = list(X.columns)
    for i in range(n):
        x = X.iloc[[i]]
        batch, orders = [], []
        for _ in range(n_perm):
            z = background.iloc[[int(rng.integers(len(background)))]].copy()
            order = rng.permutation(p)
            cur = z.copy()
            batch.append(cur.copy())
            for j in order:
                cur[cols[j]] = x[cols[j]].to_numpy()
                batch.append(cur.copy())
            orders.append(order)
        preds = predict(pd.concat(batch, ignore_index=True))
        k = 0
        for order in orders:
            seq = preds[k:k + p + 1]
            base[i] += seq[0]
            for step, j in enumerate(order):
                phi[i, j] += seq[step + 1] - seq[step]
            k += p + 1
    return phi / n_perm, base / n_perm


def _predict_fn(pipe: Pipeline, task: str, binary: bool):
    if task == "classification" and binary:
        return lambda d: pipe.predict_proba(d)[:, 1]
    if task == "classification":
        return lambda d: pipe.predict_proba(d).max(axis=1)
    return lambda d: pipe.predict(d)


def partial_dependence(predict, X: pd.DataFrame, col: str, grid_n: int = 16) -> list[dict[str, Any]]:
    x = pd.to_numeric(X[col], errors="coerce").dropna()
    if x.nunique() < 3:
        return []
    grid = np.unique(np.quantile(x, np.linspace(0.05, 0.95, grid_n)))
    samp = X.sample(min(len(X), 300), random_state=SEED)
    out = []
    for g in grid:
        d = samp.copy()
        d[col] = g
        out.append({"value": _r(float(g), 4), "prediction": _r(float(np.mean(predict(d))), 5)})
    return out


def train(df: pd.DataFrame, profile: dict[str, Any], target: str, features: list[str] | None = None, task: str | None = None,
          split: str = "random", date_col: str | None = None, positive_class: str | None = None, max_rows: int = 50_000,
          progress=lambda msg: None) -> dict[str, Any]:
    t0 = time.perf_counter()
    if target not in df.columns:
        raise AutoMLError(f"{target} is not a column.")
    df = df[df[target].notna()].reset_index(drop=True)
    notes: list[str] = []
    if len(df) > max_rows:
        df = df.sample(max_rows, random_state=SEED).reset_index(drop=True)
        notes.append(f"Trained on a random sample of {max_rows:,} rows to stay within server memory.")
    task = task or detect_task(df[target])
    features = features or [c for c in df.columns if c != target]
    feats, excluded = screen_features(df, target, features, task, profile)
    if not feats:
        raise AutoMLError("No usable feature columns remain after excluding identifiers, dates and possible leakage.")
    if len(df) < 60:
        raise AutoMLError("At least 60 rows with a known target are needed for a train/test split with cross-validation.")

    X = df[feats].copy()
    num = [c for c in feats if pd.to_numeric(X[c], errors="coerce").notna().mean() > 0.95 and X[c].nunique() > 10]
    for c in num:
        X[c] = pd.to_numeric(X[c], errors="coerce")
    cat = [c for c in feats if c not in num]
    for c in cat:
        X[c] = X[c].astype(str).where(X[c].notna(), None).astype(object)

    binary, pos, classes = False, None, None
    if task == "classification":
        y_raw = df[target].astype(str)
        classes = sorted(y_raw.unique())
        if len(classes) < 2:
            raise AutoMLError("The target has only one value; there is nothing to predict.")
        if len(classes) > 30:
            raise AutoMLError(f"{target} has {len(classes)} distinct values; choose a column with fewer classes or a numeric target.")
        counts = y_raw.value_counts()
        if counts.min() < 5:
            raise AutoMLError(f"Class {counts.idxmin()!r} has only {counts.min()} rows; each class needs at least 5.")
        binary = len(classes) == 2
        if binary:
            pref = [c for c in classes if c.lower() in ("1", "1.0", "yes", "true", "y")]
            pos = str(positive_class) if positive_class in classes else (pref[0] if pref else counts.idxmin())
            y = (y_raw == pos).astype(int)
        else:
            y = y_raw
    else:
        y = pd.to_numeric(df[target], errors="coerce")
        keep = y.notna()
        X, y, df = X[keep].reset_index(drop=True), y[keep].reset_index(drop=True), df[keep].reset_index(drop=True)

    # split
    if split == "time":
        dc = date_col or (profile.get("datetime_columns") or [None])[0]
        if not dc or dc not in df.columns:
            raise AutoMLError("A time-ordered split needs a date column.")
        when = pd.to_datetime(df[dc], errors="coerce", format="mixed")
        order = when.sort_values(kind="stable", na_position="first").index
        cut = int(len(order) * 0.75)
        tr_idx, te_idx = order[:cut], order[cut:]
        split_desc = f"Time-ordered: trained on the earliest 75% by {dc}, tested on the latest 25% ({when[te_idx].min():%Y-%m-%d} onward)."
    else:
        strat = y if task == "classification" else None
        tr_idx, te_idx = train_test_split(np.arange(len(df)), test_size=0.25, random_state=SEED, stratify=strat)
        split_desc = "Random 75/25 split" + (", stratified by class." if task == "classification" else ".")
    Xtr, Xte, ytr, yte = X.iloc[tr_idx], X.iloc[te_idx], y.iloc[tr_idx], y.iloc[te_idx]
    if task == "classification" and (pd.Series(ytr).nunique() < 2 or pd.Series(yte).nunique() < 2):
        raise AutoMLError("One of the splits has a single class; there is too little data to evaluate.")

    # compare candidates by CV on training data only
    if task == "classification":
        cv = StratifiedKFold(5, shuffle=True, random_state=SEED) if split != "time" else KFold(5)
        scoring = {"balanced_accuracy": "balanced_accuracy", "f1": "f1" if binary else "f1_macro"}
        if binary:
            scoring["roc_auc"] = "roc_auc"
        primary = "roc_auc" if binary else "balanced_accuracy"
    else:
        cv = KFold(5, shuffle=split != "time", random_state=SEED if split != "time" else None)
        scoring = {"r2": "r2", "rmse": "neg_root_mean_squared_error", "mae": "neg_mean_absolute_error"}
        primary = "r2"
    board = []
    for name, (est, scale, desc) in candidates(task, len(Xtr) < 2000).items():
        progress(f"Cross-validating {name.replace('_', ' ')}")
        pipe = Pipeline([("prep", _prep(num, cat, scale)), ("model", est)])
        s0 = time.perf_counter()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            r = cross_validate(pipe, Xtr, ytr, cv=cv, scoring=scoring, return_train_score=True, error_score="raise")
        row = {"model": name, "description": desc, "fit_seconds": round(time.perf_counter() - s0, 2)}
        for k in scoring:
            sign = -1 if scoring[k].startswith("neg_") else 1
            row[f"cv_{k}"] = _r(sign * float(np.mean(r[f"test_{k}"])))
            row[f"cv_{k}_sd"] = _r(float(np.std(r[f"test_{k}"])))
        row["cv_train_" + primary] = _r(float(np.mean(r[f"train_{primary}"])))
        board.append(row)
    best = max((b for b in board if b["model"] != "baseline"), key=lambda b: b[f"cv_{primary}"])
    base_row = next(b for b in board if b["model"] == "baseline")

    progress(f"Fitting {best['model'].replace('_', ' ')} and testing once on held-out data")
    est, scale, _ = candidates(task, len(Xtr) < 2000)[best["model"]]
    pipe = Pipeline([("prep", _prep(num, cat, scale)), ("model", est)])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pipe.fit(Xtr, ytr)
    pred = pipe.predict(Xte)
    charts: dict[str, Any] = {}
    test: dict[str, Any] = {}
    warn: list[str] = []
    if task == "classification":
        avg = "binary" if binary else "macro"
        test = {"accuracy": accuracy_score(yte, pred), "balanced_accuracy": balanced_accuracy_score(yte, pred),
                "precision": precision_score(yte, pred, average=avg, zero_division=0), "recall": recall_score(yte, pred, average=avg, zero_division=0),
                "f1": f1_score(yte, pred, average=avg, zero_division=0)}
        test["majority_baseline_accuracy"] = float((yte == pd.Series(ytr).value_counts().idxmax()).mean())
        if binary:
            score = pipe.predict_proba(Xte)[:, 1]
            test["roc_auc"] = roc_auc_score(yte, score)
            test["pr_auc"] = average_precision_score(yte, score)
            test["positive_rate"] = float(np.mean(yte))
            fpr, tpr, _ = roc_curve(yte, score)
            idx = np.unique(np.linspace(0, len(fpr) - 1, min(60, len(fpr))).astype(int))
            charts["roc"] = [{"fpr": _r(fpr[i], 4), "tpr": _r(tpr[i], 4)} for i in idx]
            bins = pd.cut(score, np.linspace(0, 1, 11), include_lowest=True)
            cal = pd.DataFrame({"bin": bins, "p": score, "y": np.asarray(yte)}).groupby("bin", observed=True).agg(predicted=("p", "mean"), observed=("y", "mean"), n=("y", "size"))
            charts["calibration"] = [{"predicted": _r(r.predicted, 3), "observed": _r(r.observed, 3), "n": int(r.n)} for r in cal.itertuples() if r.n >= 5]
        labels = [0, 1] if binary else classes
        names = ([f"not {pos}", str(pos)] if binary else classes)
        cm = confusion_matrix(yte, pred, labels=labels)
        charts["confusion"] = {"labels": names, "matrix": cm.tolist()}
        if binary and test["recall"] < 0.3:
            warn.append(f"Recall for {pos} is {test['recall']:.2f}: the model misses most positive cases at the default 0.5 threshold.")
        if test["balanced_accuracy"] > 0.99:
            warn.append("Near-perfect test score. Check that no feature is recorded after the outcome (leakage) before trusting it.")
    else:
        test = {"r2": r2_score(yte, pred), "rmse": float(np.sqrt(mean_squared_error(yte, pred))), "mae": mean_absolute_error(yte, pred),
                "baseline_rmse": float(np.sqrt(mean_squared_error(yte, np.full(len(yte), float(ytr.mean())))))}
        samp = np.random.default_rng(SEED).choice(len(yte), min(300, len(yte)), replace=False)
        ya = np.asarray(yte)
        charts["pred_vs_actual"] = [{"actual": _r(ya[i], 4), "predicted": _r(pred[i], 4)} for i in samp]
        charts["residuals"] = [{"predicted": _r(pred[i], 4), "residual": _r(ya[i] - pred[i], 4)} for i in samp]
        if test["r2"] > 0.995:
            warn.append("Near-perfect test score. Check that no feature is derived from the target (leakage) before trusting it.")
    gap = (best.get("cv_train_" + primary) or 0) - (best.get(f"cv_{primary}") or 0)
    if gap > 0.15:
        warn.append(f"Training score exceeds cross-validated score by {gap:.2f}: the model partly memorises the training data.")
    if best[f"cv_{primary}"] is not None and base_row[f"cv_{primary}"] is not None and best[f"cv_{primary}"] - base_row[f"cv_{primary}"] < 0.02:
        warn.append("The best model barely beats the naive baseline; these features carry little predictive signal.")
    if len(df) < 500:
        warn.append(f"Only {len(df):,} rows: estimates are noisy, so treat small differences between models as ties.")

    # explanations
    progress("Computing explanations")
    predict = _predict_fn(pipe, task, binary)
    pi = permutation_importance(pipe, Xte, yte, n_repeats=5, random_state=SEED, scoring="roc_auc" if binary else ("balanced_accuracy" if task == "classification" else "r2"))
    imp = sorted([{"feature": f, "importance": _r(m), "std": _r(s)} for f, m, s in zip(feats, pi.importances_mean, pi.importances_std)],
                 key=lambda r: -(r["importance"] or 0))
    bg = Xtr.sample(min(len(Xtr), 100), random_state=SEED)
    ex = Xte.sample(min(len(Xte), 40), random_state=SEED)
    n_perm = max(6, min(24, 2400 // max(1, len(feats))))
    phi, base = shapley(predict, ex, bg, n_perm=n_perm)
    shap_global = sorted([{"feature": f, "mean_abs_shap": _r(float(np.mean(np.abs(phi[:, j]))))} for j, f in enumerate(feats)],
                         key=lambda r: -(r["mean_abs_shap"] or 0))
    pdp = {}
    for r in imp[:4]:
        if r["feature"] in num:
            pdp[r["feature"]] = partial_dependence(predict, Xtr, r["feature"])

    bundle = io.BytesIO()
    joblib.dump({"pipe": pipe, "target": target, "features": feats, "num": num, "cat": cat, "task": task, "binary": binary, "positive_class": pos,
                 "background": bg,
                 "categories": {c: sorted(Xtr[c].dropna().astype(str).unique().tolist()) for c in cat}}, bundle, compress=3)
    schema = []
    for c in feats:
        if c in num:
            s = Xtr[c]
            schema.append({"name": c, "kind": "numeric", "min": _r(s.min()), "max": _r(s.max()), "median": _r(s.median())})
        else:
            vc = Xtr[c].value_counts()
            schema.append({"name": c, "kind": "category", "options": [str(v) for v in vc.index[:50]], "mode": str(vc.index[0]) if len(vc) else None})
    return {
        "task": task, "target": target, "binary": binary, "positive_class": pos, "classes": classes, "primary_metric": primary,
        "features": feats, "excluded": excluded, "numeric_features": num, "categorical_features": cat,
        "n_rows": int(len(df)), "n_train": int(len(Xtr)), "n_test": int(len(Xte)), "split": split, "split_description": split_desc,
        "leaderboard": board, "best_model": best["model"], "test_metrics": {k: _r(v) for k, v in test.items()},
        "charts": charts, "importance": imp, "shap_global": shap_global,
        "shap_note": f"Sampling-based Shapley estimates: {len(ex)} test rows, {n_perm} permutations each, against {len(bg)} background rows from the training data. "
                     "They describe how the model uses each feature, not causal effects.",
        "partial_dependence": pdp, "warnings": warn, "notes": notes, "input_schema": schema,
        "seconds": round(time.perf_counter() - t0, 1),
    }, bundle.getvalue()


def predict_rows(model_bytes: bytes, rows: list[dict[str, Any]], explain: bool = True) -> list[dict[str, Any]]:
    b = joblib.load(io.BytesIO(model_bytes))
    feats, num = b["features"], b["num"]
    X = pd.DataFrame([{f: r.get(f) for f in feats} for r in rows], columns=feats)
    for c in feats:
        if c in num:
            X[c] = pd.to_numeric(X[c], errors="coerce")
        else:
            X[c] = X[c].astype(str).where(X[c].notna() & (X[c] != ""), None).astype(object)
    pipe, task, binary = b["pipe"], b["task"], b["binary"]
    predict = _predict_fn(pipe, task, binary)
    out = []
    preds = pipe.predict(X)
    proba = pipe.predict_proba(X) if task == "classification" else None
    phi, base = shapley(predict, X, b["background"], n_perm=40) if explain else (None, None)
    for i in range(len(X)):
        r: dict[str, Any] = {}
        if task == "classification":
            classes = list(pipe.classes_)
            if binary:
                p1 = float(proba[i][classes.index(1)])
                label = f"{b.get('target', 'target')} = {b['positive_class']}"
                r.update(prediction=label if p1 >= 0.5 else f"not {label}", probability=_r(p1, 4))
            else:
                r.update(prediction=str(preds[i]), probability=_r(float(proba[i].max()), 4))
        else:
            r["prediction"] = _r(float(preds[i]), 4)
        if explain:
            contrib = sorted([{"feature": f, "value": None if pd.isna(X.iloc[i][f]) else (X.iloc[i][f] if isinstance(X.iloc[i][f], str) else _r(float(X.iloc[i][f]), 4)),
                               "contribution": _r(float(phi[i, j]), 5)} for j, f in enumerate(feats)], key=lambda c: -abs(c["contribution"] or 0))
            r["explanation"] = {"base_value": _r(float(base[i]), 5), "output": _r(float(base[i] + phi[i].sum()), 5), "contributions": contrib,
                                "scale": "probability of " + str(b["positive_class"]) if binary else ("probability of the predicted class" if task == "classification" else "prediction")}
        out.append(r)
    return out


def run_scenario(model_bytes: bytes, df: pd.DataFrame, changes: list[dict[str, Any]], filters: list[dict[str, Any]] | None = None,
                 n_boot: int = 300, max_rows: int = 20_000) -> dict[str, Any]:
    """What-if: apply changes to every (or every filtered) row, compare the model's average prediction before and after.

    The difference is a model-based estimate with a bootstrap 95% interval over rows. It shows what the model expects,
    not what would happen if the change were made in reality (that needs an experiment).
    """
    b = joblib.load(io.BytesIO(model_bytes))
    feats, num = b["features"], b["num"]
    if not changes:
        raise AutoMLError("Add at least one change.")
    d = df.copy()
    for f in filters or []:
        c, op, v = f.get("column"), f.get("op", "=="), f.get("value")
        if c not in d.columns:
            raise AutoMLError(f"Unknown filter column {c!r}.")
        if op == "==":
            d = d[d[c].astype(str) == str(v)]
        elif op == "!=":
            d = d[d[c].astype(str) != str(v)]
        elif op in (">", ">=", "<", "<="):
            x = pd.to_numeric(d[c], errors="coerce")
            d = d[{">": x > float(v), ">=": x >= float(v), "<": x < float(v), "<=": x <= float(v)}[op]]
        else:
            raise AutoMLError(f"Unknown filter operator {op!r}.")
    if len(d) < 10:
        raise AutoMLError(f"Only {len(d)} rows match the filter; at least 10 are needed.")
    if len(d) > max_rows:
        d = d.sample(max_rows, random_state=SEED)
    X = pd.DataFrame({f: d[f] if f in d.columns else None for f in feats})
    for c in feats:
        if c in num:
            X[c] = pd.to_numeric(X[c], errors="coerce")
        else:
            X[c] = X[c].astype(str).where(X[c].notna(), None).astype(object)
    X2 = X.copy()
    applied = []
    for ch in changes:
        f, op, v = ch.get("feature"), ch.get("op", "set"), ch.get("value")
        if f not in feats:
            raise AutoMLError(f"{f!r} is not a model feature.")
        if f in num:
            try:
                v = float(v)
            except (TypeError, ValueError):
                raise AutoMLError(f"{f} is numeric; give a number.") from None
            if op == "set":
                X2[f] = v
            elif op == "add":
                X2[f] = X2[f] + v
            elif op == "multiply":
                X2[f] = X2[f] * v
            elif op == "percent":
                X2[f] = X2[f] * (1 + v / 100)
            else:
                raise AutoMLError(f"Unknown change {op!r}.")
            lo, hi = float(X[f].min()), float(X[f].max())
            outside = float(((X2[f] < lo) | (X2[f] > hi)).mean())
            applied.append({"feature": f, "op": op, "value": v, "share_outside_observed_range": _r(outside, 3)})
        else:
            if op != "set":
                raise AutoMLError(f"{f} is categorical; only 'set' applies.")
            known = set(b.get("categories", {}).get(f) or df[f].dropna().astype(str))
            if str(v) not in known:
                raise AutoMLError(f"{v!r} never appears in {f}; the model has no basis for it.")
            X2[f] = str(v)
            applied.append({"feature": f, "op": "set", "value": str(v), "rows_changed": int((X[f] != str(v)).sum())})
    predict = _predict_fn(b["pipe"], b["task"], b["binary"])
    p0, p1 = np.asarray(predict(X), dtype=float), np.asarray(predict(X2), dtype=float)
    diff = p1 - p0
    rng = np.random.default_rng(SEED)
    boots = [diff[rng.integers(0, len(diff), len(diff))].mean() for _ in range(n_boot)]
    lo, hi = np.percentile(boots, [2.5, 97.5])
    unit = f"probability of {b.get('target')} = {b['positive_class']}" if b["binary"] else ("probability of the predicted class" if b["task"] == "classification" else f"predicted {b.get('target')}")
    warnings_ = []
    for a in applied:
        if a.get("share_outside_observed_range", 0) > 0.05:
            warnings_.append(f"{a['share_outside_observed_range']:.0%} of rows move {a['feature']} outside the range seen in training; the model is extrapolating there.")
    hist_edges = np.histogram_bin_edges(np.concatenate([p0, p1]), bins=20)
    h0, _ = np.histogram(p0, hist_edges)
    h1, _ = np.histogram(p1, hist_edges)
    return {
        "rows": int(len(d)), "unit": unit, "changes": applied,
        "before_mean": _r(float(p0.mean())), "after_mean": _r(float(p1.mean())), "difference": _r(float(diff.mean())),
        "ci95": [_r(float(lo)), _r(float(hi))], "share_increased": _r(float((diff > 1e-9).mean()), 3), "share_decreased": _r(float((diff < -1e-9).mean()), 3),
        "total_before": _r(float(p0.sum())) if b["task"] == "regression" else None, "total_after": _r(float(p1.sum())) if b["task"] == "regression" else None,
        "histogram": [{"bin": f"{hist_edges[i]:.3g}", "before": int(h0[i]), "after": int(h1[i])} for i in range(len(h0))],
        "warnings": warnings_,
        "caveat": "This is what the trained model predicts if only these inputs change. It is not a causal estimate: in reality other factors may change too.",
    }
