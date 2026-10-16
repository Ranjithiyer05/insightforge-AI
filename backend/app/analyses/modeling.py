"""Supervised learning: classification and regression with leakage-safe pipelines.

All preprocessing lives inside a scikit-learn Pipeline fitted on the training
split only. Cross-validation runs on the training split; the held-out test
split is touched once. Predictions are written out so the verifier can
recompute every reported metric independently.
"""
from __future__ import annotations

from typing import Any

from .base import Assessment, Finding, Method, Recommendation, Stage, header, metric_value

COMMON = r'''
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

df = ifrt.load_df()
target = P["target"]
features = [f for f in P["features"] if f in df.columns and f != target]
df = df[df[target].notna()].reset_index(drop=True)
df["__row_id"] = range(len(df))
X = df[features].copy()
num = [c for c in features if pd.api.types.is_numeric_dtype(X[c])]
cat = [c for c in features if c not in num]
for c in cat:
    X[c] = X[c].astype(str).where(X[c].notna(), None)
ifrt.metric("n_rows_used", int(len(df)))
ifrt.metric("features_used", features)
ifrt.metric("numeric_features", num)
ifrt.metric("categorical_features", cat)
if P.get("excluded_features"):
    ifrt.note("Excluded from modelling (possible leakage or identifiers): " + ", ".join(P["excluded_features"]))

def preprocessor(scale=True):
    steps_num = [("impute", SimpleImputer(strategy="median"))] + ([("scale", StandardScaler())] if scale else [])
    return ColumnTransformer([
        ("num", Pipeline(steps_num), num),
        ("cat", Pipeline([("impute", SimpleImputer(strategy="most_frequent")),
                          ("onehot", OneHotEncoder(handle_unknown="infrequent_if_exist", min_frequency=5, sparse_output=False))]), cat),
    ])

def importance(pipe, Xte, yte, scoring):
    pi = permutation_importance(pipe, Xte, yte, n_repeats=5, random_state=SEED, scoring=scoring)
    imp = pd.DataFrame({"feature": features, "importance": pi.importances_mean, "std": pi.importances_std})
    imp = imp.sort_values("importance", ascending=False).head(15)
    ifrt.table("feature_importance", imp.round(5))
    ifrt.chart("feature_importance", "bar", "Permutation importance on the test set (drop in score when shuffled)",
               imp.round(5).to_dict("records"), "feature", [{"key": "importance", "label": "Importance"}], layout="horizontal")
    ifrt.artifact("top_features", imp["feature"].head(5).tolist())
'''

CLASSIFY = r'''
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, average_precision_score, balanced_accuracy_score, confusion_matrix, f1_score,
                             precision_score, recall_score, roc_auc_score, roc_curve)
from sklearn.model_selection import StratifiedKFold, cross_validate, train_test_split

y_raw = df[target].astype(str)
classes = sorted(y_raw.unique())
if len(classes) < 2:
    raise ValueError("The target has only one class; there is nothing to predict.")
binary = len(classes) == 2
if binary:
    pos = P.get("positive_class")
    if pos is None or str(pos) not in classes:
        pref = [c for c in classes if c.lower() in ("1", "1.0", "yes", "true", "y", "churned", "default", "left")]
        pos = pref[0] if pref else y_raw.value_counts().idxmin()
    pos = str(pos)
    y = (y_raw == pos).astype(int)
    ifrt.metric("positive_class", pos)
else:
    y = y_raw
shares = y_raw.value_counts(normalize=True)
ifrt.metric("minority_share", float(shares.min()))
ifrt.metric("n_classes", int(len(classes)))

s = P["strategy"]
if s == "logistic_regression":
    model, scale = LogisticRegression(max_iter=2000), True
elif s == "logistic_balanced":
    model, scale = LogisticRegression(max_iter=2000, class_weight="balanced"), True
elif s == "random_forest":
    model, scale = RandomForestClassifier(n_estimators=300, min_samples_leaf=3, class_weight="balanced_subsample", random_state=SEED, n_jobs=1), False
elif s == "hist_gradient_boosting":
    model, scale = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.06, class_weight="balanced", random_state=SEED), False
else:
    raise ValueError(f"unknown strategy {s}")
pipe = Pipeline([("prep", preprocessor(scale)), ("model", model)])

Xtr, Xte, ytr, yte, idtr, idte = train_test_split(X, y, df["__row_id"], test_size=0.25, stratify=y, random_state=SEED)
cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=SEED)
scoring = {"balanced_accuracy": "balanced_accuracy", "f1": "f1" if binary else "f1_macro"}
if binary:
    scoring["roc_auc"] = "roc_auc"
cvr = cross_validate(pipe, Xtr, ytr, cv=cv, scoring=scoring, return_train_score=True)
for k in scoring:
    vals = cvr[f"test_{k}"]
    ifrt.metric(f"cv_{k}", float(vals.mean()), sd=float(vals.std()), folds=vals.tolist(), split="5-fold CV on training data")
ifrt.metric("cv_train_balanced_accuracy", float(cvr["train_balanced_accuracy"].mean()))

pipe.fit(Xtr, ytr)
pred = pipe.predict(Xte)
avg = "binary" if binary else "macro"
m = {
    "accuracy": accuracy_score(yte, pred),
    "balanced_accuracy": balanced_accuracy_score(yte, pred),
    "precision": precision_score(yte, pred, average=avg, zero_division=0),
    "recall": recall_score(yte, pred, average=avg, zero_division=0),
    "f1": f1_score(yte, pred, average=avg, zero_division=0),
}
score = None
if binary:
    score = pipe.predict_proba(Xte)[:, 1]
    m["roc_auc"] = roc_auc_score(yte, score)
    m["pr_auc"] = average_precision_score(yte, score)
    fpr, tpr, _ = roc_curve(yte, score)
    idx = np.linspace(0, len(fpr) - 1, min(60, len(fpr))).astype(int)
    ifrt.chart("roc", "line", "ROC curve on the held-out test set", [{"fpr": round(float(fpr[i]), 4), "tpr": round(float(tpr[i]), 4)} for i in idx],
               "fpr", [{"key": "tpr", "label": "True positive rate"}], x_label="False positive rate", diagonal=True)
for k, v in m.items():
    ifrt.metric(k, float(v), split="held-out test (25%)")
    ifrt.claim(f"test_{k}", f"Test-set {k.replace('_', ' ')}", float(v), {"kind": "prediction_metric", "metric": k, "task": "classification"})
majority = float(pd.Series(ytr).value_counts(normalize=True).max())
ifrt.metric("majority_baseline_accuracy", float((yte == pd.Series(ytr).value_counts().idxmax()).mean()), split="held-out test")
labels = [0, 1] if binary else classes
cm = confusion_matrix(yte, pred, labels=labels)
names = (["not " + pos, pos] if binary else classes)
ifrt.table("confusion_matrix", pd.DataFrame(cm, index=[f"actual {n}" for n in names], columns=[f"predicted {n}" for n in names]))
ifrt.artifact("predictions", {"y_true": [int(v) if binary else str(v) for v in yte], "y_pred": [int(v) if binary else str(v) for v in pred],
                              "y_score": [float(v) for v in score] if score is not None else None,
                              "train_ids": [int(v) for v in idtr], "test_ids": [int(v) for v in idte]})
importance(pipe, Xte, yte, "roc_auc" if binary else "balanced_accuracy")
ifrt.emit()
'''

REGRESS = r'''
from sklearn.ensemble import HistGradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.compose import TransformedTargetRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import KFold, cross_validate, train_test_split

y = pd.to_numeric(df[target], errors="coerce")
keep = y.notna()
X, y, ids = X[keep], y[keep], df.loc[keep, "__row_id"]
ifrt.metric("target_skew", float(y.skew()))
s = P["strategy"]
if s == "linear_ridge":
    model, scale = Ridge(alpha=1.0), True
elif s == "log_target_ridge":
    if (y <= -1).any():
        raise ValueError("log1p target transform needs values above -1.")
    model, scale = TransformedTargetRegressor(regressor=Ridge(alpha=1.0), func=np.log1p, inverse_func=np.expm1), True
elif s == "random_forest":
    model, scale = RandomForestRegressor(n_estimators=300, min_samples_leaf=3, random_state=SEED, n_jobs=1), False
elif s == "hist_gradient_boosting":
    model, scale = HistGradientBoostingRegressor(max_iter=300, learning_rate=0.06, random_state=SEED), False
else:
    raise ValueError(f"unknown strategy {s}")
pipe = Pipeline([("prep", preprocessor(scale)), ("model", model)])
Xtr, Xte, ytr, yte, idtr, idte = train_test_split(X, y, ids, test_size=0.25, random_state=SEED)
cvr = cross_validate(pipe, Xtr, ytr, cv=KFold(5, shuffle=True, random_state=SEED), scoring={"r2": "r2", "rmse": "neg_root_mean_squared_error"}, return_train_score=True)
ifrt.metric("cv_r2", float(cvr["test_r2"].mean()), sd=float(cvr["test_r2"].std()), folds=cvr["test_r2"].tolist(), split="5-fold CV on training data")
ifrt.metric("cv_train_r2", float(cvr["train_r2"].mean()))
pipe.fit(Xtr, ytr)
pred = pipe.predict(Xte)
base = np.full(len(yte), float(ytr.mean()))
m = {"rmse": float(np.sqrt(mean_squared_error(yte, pred))), "mae": float(mean_absolute_error(yte, pred)), "r2": float(r2_score(yte, pred))}
for k, v in m.items():
    ifrt.metric(k, v, split="held-out test (25%)")
    ifrt.claim(f"test_{k}", f"Test-set {k.upper()}", v, {"kind": "prediction_metric", "metric": k, "task": "regression"})
ifrt.metric("baseline_rmse", float(np.sqrt(mean_squared_error(yte, base))), note="predicting the training mean")
ifrt.artifact("predictions", {"y_true": [float(v) for v in yte], "y_pred": [float(v) for v in pred],
                              "train_ids": [int(v) for v in idtr], "test_ids": [int(v) for v in idte]})
samp = np.random.default_rng(SEED).choice(len(yte), min(300, len(yte)), replace=False)
ifrt.chart("pred_vs_actual", "scatter", "Predicted vs actual (held-out test sample)",
           [{"x": round(float(np.asarray(yte)[i]), 4), "y": round(float(pred[i]), 4)} for i in samp], "x", [{"key": "y", "label": "Predicted"}],
           x_label="Actual", y_label="Predicted", diagonal=True)
importance(pipe, Xte, yte, "r2")

# Interpretable OLS on numeric features (association, not causation), fitted on the training split.
if num and len(Xtr) > len(num) + 10 and s in ("linear_ridge", "log_target_ridge"):
    import statsmodels.api as sm
    Z = Xtr[num].apply(lambda c: c.fillna(c.median()))
    ols = sm.OLS(ytr.to_numpy(), sm.add_constant(Z.to_numpy(), has_constant="add")).fit()
    ci = ols.conf_int(0.05)
    coef = pd.DataFrame({"term": ["const"] + num, "coef": ols.params, "ci_low": ci[:, 0], "ci_high": ci[:, 1], "p_value": ols.pvalues})
    ifrt.table("ols_coefficients", coef.round(5))
    ifrt.metric("ols_r2_train", float(ols.rsquared))
ifrt.emit()
'''


class ClassificationMethod(Method):
    key = "classification"
    task_type = "classification"
    title = "Classification model"
    strategies = ["logistic_regression", "logistic_balanced", "random_forest", "hist_gradient_boosting"]
    retry_map = {
        "class_imbalance": ["logistic_balanced", "hist_gradient_boosting", "random_forest"],
        "underfit": ["hist_gradient_boosting", "random_forest"],
        "overfit": ["logistic_balanced", "logistic_regression"],
        "model_error": ["random_forest", "logistic_balanced"],
    }

    def requirements(self, profile, params):
        miss = []
        if not params.get("target"):
            miss.append("a target column with the outcome to predict (e.g. churned yes/no)")
        if not params.get("features"):
            miss.append("at least one feature column")
        if profile.get("n_rows", 0) < 60:
            miss.append("at least 60 rows for a train/test split with cross-validation")
        return miss

    def stages(self, params, strategy):
        return [Stage("model", f"Train and evaluate {strategy.replace('_', ' ')} (stratified split + 5-fold CV)",
                      header(params, strategy, "import numpy as np\nimport pandas as pd") + COMMON + CLASSIFY,
                      "Fits a leakage-safe preprocessing + model pipeline on the training split and evaluates once on a held-out test split.")]

    def assess(self, result, params, strategy):
        bal = metric_value(result, "balanced_accuracy")
        if bal is None:
            return Assessment("failed", "The model did not produce metrics.", "model_error")
        rec = metric_value(result, "recall")
        minority = metric_value(result, "minority_share", 0.5)
        gap = (metric_value(result, "cv_train_balanced_accuracy", 0) or 0) - (metric_value(result, "cv_balanced_accuracy", 0) or 0)
        if bal < 0.6 or (metric_value(result, "n_classes") == 2 and rec is not None and rec < 0.3):
            if minority < 0.2:
                return Assessment("weak", f"Balanced accuracy {bal:.2f}, recall on the positive class {rec:.2f}: the model mostly predicts the majority class "
                                  f"(positive share {minority:.0%}).", "class_imbalance", ("balanced_accuracy", bal))
            if gap > 0.1:
                return Assessment("weak", f"Training score exceeds CV score by {gap:.2f}, suggesting overfitting.", "overfit", ("balanced_accuracy", bal))
            return Assessment("weak", f"Balanced accuracy {bal:.2f} is close to chance; a more flexible model may capture non-linear patterns.", "underfit", ("balanced_accuracy", bal))
        return Assessment("succeeded", headline_metric=("balanced_accuracy", bal))

    def conditions(self, df, profile, params):
        t = params.get("target")
        if not t or t not in df:
            return {}
        share = float(df[t].astype(str).value_counts(normalize=True).min())
        return {"imbalance": "severe" if share < 0.2 else "moderate" if share < 0.35 else "balanced",
                "size": "small" if len(df) < 1000 else "large"}

    def findings(self, result, params):
        mv = lambda k, d=None: metric_value(result, k, d)  # noqa: E731
        F, R, L = [], [], []
        auc = mv("roc_auc")
        F.append(Finding(
            f"Model performance on unseen data: balanced accuracy {mv('balanced_accuracy', 0):.2f}" + (f", ROC AUC {auc:.2f}" if auc is not None else ""),
            f"On a 25% held-out test set: precision {mv('precision', 0):.2f}, recall {mv('recall', 0):.2f}, F1 {mv('f1', 0):.2f}. "
            f"A model that always predicts the majority class would score accuracy {mv('majority_baseline_accuracy', 0):.2f}. "
            f"5-fold CV balanced accuracy on the training data: {mv('cv_balanced_accuracy', 0):.2f}.",
            ["test_balanced_accuracy", "test_precision", "test_recall", "test_f1"] + (["test_roc_auc"] if auc is not None else []), "observation", "high"))
        top = result.get("artifacts", {}).get("top_features", [])
        if top:
            F.append(Finding("Most predictive features", "Shuffling these features hurt test performance the most: " + ", ".join(top) + ".",
                             ["feature_importance"], "inference", "medium"))
        R.append(Recommendation("Use predicted probabilities to prioritise outreach, and track real outcomes to confirm the model works in practice.",
                                "Predictions are model estimates, not confirmed outcomes.", ["test_roc_auc" if auc is not None else "test_balanced_accuracy"]))
        L += ["Feature importance shows predictive association, not causal effect.",
              "Performance is estimated on one held-out split from the same data; it may be lower on future data if conditions change."]
        if params.get("excluded_features"):
            L.append("Some columns were excluded as possible leakage or identifiers: " + ", ".join(params["excluded_features"]) + ".")
        return F, R, L


class RegressionMethod(Method):
    key = "regression"
    task_type = "regression"
    title = "Regression model"
    strategies = ["linear_ridge", "log_target_ridge", "random_forest", "hist_gradient_boosting"]
    retry_map = {
        "skewed_target": ["log_target_ridge", "hist_gradient_boosting"],
        "underfit": ["hist_gradient_boosting", "random_forest"],
        "overfit": ["linear_ridge"],
        "model_error": ["random_forest"],
    }

    def requirements(self, profile, params):
        miss = []
        if not params.get("target"):
            miss.append("a numeric target column to predict")
        if not params.get("features"):
            miss.append("at least one feature column")
        if profile.get("n_rows", 0) < 60:
            miss.append("at least 60 rows")
        return miss

    def stages(self, params, strategy):
        return [Stage("model", f"Train and evaluate {strategy.replace('_', ' ')} (train/test split + 5-fold CV)",
                      header(params, strategy, "import numpy as np\nimport pandas as pd") + COMMON + REGRESS,
                      "Fits a leakage-safe pipeline, compares against a mean-prediction baseline, and evaluates once on held-out data.")]

    def assess(self, result, params, strategy):
        r2, rmse, base = metric_value(result, "r2"), metric_value(result, "rmse"), metric_value(result, "baseline_rmse")
        if r2 is None:
            return Assessment("failed", "The model did not produce metrics.", "model_error")
        if r2 < 0.1 or (base and rmse >= 0.97 * base):
            skew = abs(metric_value(result, "target_skew", 0) or 0)
            if skew > 1.5 and strategy == "linear_ridge":
                return Assessment("weak", f"R² {r2:.2f}; the target is strongly skewed ({skew:.1f}), which hurts a linear model.", "skewed_target", ("r2", r2))
            gap = (metric_value(result, "cv_train_r2", 0) or 0) - (metric_value(result, "cv_r2", 0) or 0)
            if gap > 0.2:
                return Assessment("weak", f"Train R² exceeds CV R² by {gap:.2f}: overfitting.", "overfit", ("r2", r2))
            return Assessment("weak", f"R² {r2:.2f} barely beats predicting the mean.", "underfit", ("r2", r2))
        return Assessment("succeeded", headline_metric=("r2", r2))

    def conditions(self, df, profile, params):
        import pandas as pd
        t = params.get("target")
        if not t or t not in df:
            return {}
        sk = float(pd.to_numeric(df[t], errors="coerce").skew())
        return {"target_skew": "high" if abs(sk) > 1.5 else "low", "size": "small" if len(df) < 1000 else "large"}

    def findings(self, result, params):
        mv = lambda k, d=None: metric_value(result, k, d)  # noqa: E731
        F = [Finding(f"Model explains {max(mv('r2', 0), 0) * 100:.0f}% of variance in {params.get('target')} on unseen data",
                     f"Held-out R² {mv('r2', 0):.3f}, RMSE {mv('rmse', 0):.3f}, MAE {mv('mae', 0):.3f}. Baseline RMSE (predicting the mean) {mv('baseline_rmse', 0):.3f}. "
                     f"5-fold CV R² {mv('cv_r2', 0):.3f}.", ["test_r2", "test_rmse", "test_mae"], "observation", "high")]
        top = result.get("artifacts", {}).get("top_features", [])
        if top:
            F.append(Finding("Most predictive features", ", ".join(top) + " contribute most to predictive accuracy.", ["feature_importance"], "inference", "medium"))
        R = [Recommendation("Validate the strongest drivers with a controlled change before acting on them.", "Model associations are not causal effects.", ["test_r2"])]
        L = ["Coefficients and importances show association, not causation.", "Predictions are estimates with error roughly the size of the RMSE."]
        return F, R, L
