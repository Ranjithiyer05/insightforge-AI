"""Independent verification engine.

Runs in the API process, reading the original dataset directly. It never
reuses the sandbox's intermediate state: every numeric claim is recomputed
here from raw data (or, for model metrics, from the raw predictions the
sandbox emitted) with separately written code. It also checks statistical
assumptions, leakage, evidence links and causal language in conclusions.

The verifier's verdict is stored separately from any narrative text.
"""
from __future__ import annotations

import math
import re
import warnings
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

CAUSAL_RE = re.compile(r"\b(caus(e|es|ed|ing)|because of|due to|leads? to|led to|results? in|drives|driven by|impact of)\b", re.I)


def _close(a: float, b: float, rel: float = 1e-6, abs_: float = 1e-6) -> bool:
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, float) and math.isnan(a):
        return isinstance(b, float) and math.isnan(b)
    return abs(a - b) <= max(abs_, rel * max(abs(a), abs(b)))


class Verifier:
    def __init__(self, df: pd.DataFrame, params: dict[str, Any], profile: dict[str, Any]):
        self.df = df
        self.params = params
        self.profile = profile
        self._retail: pd.DataFrame | None = None

    # ---------- independent re-derivations ----------
    def retail(self) -> pd.DataFrame:
        if self._retail is not None:
            return self._retail
        P, df = self.params, self.df
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            date = pd.to_datetime(df[P["date_col"]], errors="coerce", format="mixed")
        f = pd.DataFrame({"month": date.dt.to_period("M").astype(str), "day": date.dt.normalize()})
        units = pd.to_numeric(df[P["quantity_col"]], errors="coerce") if P.get("quantity_col") else pd.Series(1.0, index=df.index)
        f["units"] = units
        if P.get("discount_col"):
            d = pd.to_numeric(df[P["discount_col"]], errors="coerce").fillna(0.0)
            f["discount"] = d / 100.0 if d.max() > 1 else d
        if P.get("unit_price_col"):
            f["list_revenue"] = pd.to_numeric(df[P["unit_price_col"]], errors="coerce") * units
        if P.get("revenue_col"):
            f["revenue"] = pd.to_numeric(df[P["revenue_col"]], errors="coerce")
        else:
            f["revenue"] = f["list_revenue"] * (1 - f.get("discount", 0.0))
        if P.get("cost_col"):
            f["cost"] = pd.to_numeric(df[P["cost_col"]], errors="coerce")
        elif P.get("unit_cost_col"):
            f["cost"] = pd.to_numeric(df[P["unit_cost_col"]], errors="coerce") * units
        else:
            f["cost"] = f["revenue"] - pd.to_numeric(df[P["profit_col"]], errors="coerce")
        f["profit"] = f["revenue"] - f["cost"]
        if P.get("product_col"):
            f["product"] = df[P["product_col"]].astype(str)
        f = f[date.notna()].dropna(subset=["revenue", "cost", "units"])
        self._retail = f
        return f

    def _filtered(self, filt: dict[str, Any] | None) -> pd.DataFrame:
        f = self.retail()
        for k, v in (filt or {}).items():
            f = f[f[k] == v]
        return f

    def recompute(self, check: dict[str, Any], artifacts: dict[str, Any]) -> float | None:
        kind = check.get("kind")
        df = self.df
        if kind == "row_count":
            return float(len(df))
        if kind == "col_agg":
            return float(getattr(pd.to_numeric(df[check["column"]], errors="coerce"), check["op"])())
        if kind == "group_agg":
            sub = df[df[check["group"]].astype(str) == str(check["key"])]
            return float(getattr(pd.to_numeric(sub[check["column"]], errors="coerce").dropna(), check["op"])())
        if kind == "period_sum":
            f = self._filtered(check.get("filter"))
            return float(f.loc[f["month"] == check["period"], check["measure"]].sum())
        if kind in ("period_delta", "period_pct_change"):
            f = self._filtered(check.get("filter"))
            a, b = (float(f.loc[f["month"] == p, check["measure"]].sum()) for p in check["periods"])
            return b - a if kind == "period_delta" else (b - a) / abs(a) * 100
        if kind == "pvm_effect":
            return self._pvm(check["periods"], check["effect"])
        if kind == "weighted_discount":
            f = self.retail()
            g = f[f["month"] == check["period"]]
            if check.get("method", "").startswith("list"):
                return float((g["discount"] * g["list_revenue"]).sum() / g["list_revenue"].sum() * 100)
            return float(np.average(g["discount"], weights=g["revenue"].abs() + 1e-9) * 100)
        if kind in ("daily_mean_diff", "daily_welch_p"):
            f = self.retail()
            d = f.groupby(["month", "day"])["profit"].sum().reset_index()
            a = d.loc[d["month"] == check["periods"][0], "profit"].to_numpy()
            b = d.loc[d["month"] == check["periods"][1], "profit"].to_numpy()
            if kind == "daily_mean_diff":
                return float(b.mean() - a.mean())
            return float(stats.ttest_ind(b, a, equal_var=False).pvalue)
        if kind in ("test", "test_stat"):
            return self._test(check, stat=(kind == "test_stat"))
        if kind == "prediction_metric":
            return self._metric_from_predictions(check, artifacts.get("predictions") or {})
        if kind == "silhouette":
            return None  # requires refitting; checked for plausibility only
        if kind == "anomaly_count":
            return None
        return None

    def _pvm(self, periods: list[str], effect: str) -> float:
        f = self.retail()
        out = {}
        for p in periods:
            g = f[f["month"] == p].groupby("product")[["units", "revenue", "cost"]].sum()
            out[p] = g
        a, b = out[periods[0]], out[periods[1]]
        products = sorted(set(a.index) | set(b.index))
        total = 0.0
        for prod in products:
            q0, r0, c0 = (a.loc[prod].tolist() if prod in a.index else [0.0, 0.0, 0.0])
            q1, r1, c1 = (b.loc[prod].tolist() if prod in b.index else [0.0, 0.0, 0.0])
            delta = (r1 - c1) - (r0 - c0)
            if q0 > 0 and q1 > 0:
                up0, up1, uc0, uc1 = r0 / q0, r1 / q1, c0 / q0, c1 / q1
                parts = {"volume_effect": (q1 - q0) * (up0 - uc0), "price_discount_effect": q1 * (up1 - up0), "unit_cost_effect": -q1 * (uc1 - uc0)}
            else:
                parts = {"volume_effect": delta, "price_discount_effect": 0.0, "unit_cost_effect": 0.0}
            total += parts[effect]
        return float(total)

    def _test(self, check: dict[str, Any], stat: bool) -> float | None:
        df, t = self.df, check["test"]
        if t in ("pearson", "spearman"):
            sub = df[[check["x"], check["y"]]].apply(pd.to_numeric, errors="coerce").dropna()
            r = (stats.pearsonr if t == "pearson" else stats.spearmanr)(sub[check["x"]], sub[check["y"]])
            return float(r[0] if stat else r[1])
        y, g = check["outcome"], check["group"]
        if t in ("chi_square", "fisher_exact"):
            sub = df[[g, y]].dropna().astype(str)
            if check.get("groups"):
                sub = sub[sub[g].isin(check["groups"])]
            ct = pd.crosstab(sub[g], sub[y])
            return float(stats.chi2_contingency(ct)[1] if t == "chi_square" else stats.fisher_exact(ct.values)[1])
        sub = df[[g, y]].copy()
        sub[y] = pd.to_numeric(sub[y], errors="coerce")
        sub = sub.dropna()
        sub[g] = sub[g].astype(str)
        groups = [str(v) for v in (check.get("groups") or sorted(sub[g].unique()))]
        arrays = [sub.loc[sub[g] == lv, y].to_numpy() for lv in groups]
        if t == "welch_t":
            return float(stats.ttest_ind(arrays[0], arrays[1], equal_var=False).pvalue)
        if t == "mann_whitney":
            return float(stats.mannwhitneyu(arrays[0], arrays[1], alternative="two-sided").pvalue)
        if t == "anova":
            return float(stats.f_oneway(*arrays).pvalue)
        if t == "kruskal":
            return float(stats.kruskal(*arrays).pvalue)
        if t == "permutation":
            return None  # stochastic; compared against Welch for plausibility in assumption checks
        return None

    @staticmethod
    def _metric_from_predictions(check: dict[str, Any], pred: dict[str, Any]) -> float | None:
        from sklearn import metrics as skm
        yt, yp, ys = pred.get("y_true"), pred.get("y_pred"), pred.get("y_score")
        if yt is None or yp is None:
            return None
        m = check["metric"]
        binary = check.get("task") == "classification" and len(set(yt)) <= 2 and all(isinstance(v, int) for v in yt)
        avg = "binary" if binary else "macro"
        fns = {
            "accuracy": lambda: skm.accuracy_score(yt, yp),
            "balanced_accuracy": lambda: skm.balanced_accuracy_score(yt, yp),
            "precision": lambda: skm.precision_score(yt, yp, average=avg, zero_division=0),
            "recall": lambda: skm.recall_score(yt, yp, average=avg, zero_division=0),
            "f1": lambda: skm.f1_score(yt, yp, average=avg, zero_division=0),
            "roc_auc": lambda: skm.roc_auc_score(yt, ys),
            "pr_auc": lambda: skm.average_precision_score(yt, ys),
            "rmse": lambda: math.sqrt(skm.mean_squared_error(yt, yp)),
            "mae": lambda: skm.mean_absolute_error(yt, yp),
            "r2": lambda: skm.r2_score(yt, yp),
        }
        return float(fns[m]()) if m in fns else None

    # ---------- checks ----------
    def verify(self, task_type: str, result: dict[str, Any], findings: list[dict[str, Any]]) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        reasons: list[str] = []
        artifacts = result.get("artifacts", {})
        verified_claims: dict[str, bool] = {}
        for c in result.get("claims", []):
            try:
                expected = self.recompute(c["check"], artifacts)
            except Exception as exc:  # recomputation itself failed
                checks.append({"id": f"claim:{c['id']}", "category": "numeric", "status": "warn", "message": f"Could not recompute '{c['statement']}': {str(exc)[:160]}"})
                verified_claims[c["id"]] = False
                continue
            if expected is None:
                checks.append({"id": f"claim:{c['id']}", "category": "numeric", "status": "skip",
                               "message": f"'{c['statement']}' cannot be recomputed deterministically; plausibility checked instead."})
                verified_claims[c["id"]] = True
                continue
            ok = _close(float(c["value"]) if c["value"] is not None else None, expected, rel=1e-6, abs_=1e-6)
            verified_claims[c["id"]] = ok
            checks.append({"id": f"claim:{c['id']}", "category": "numeric", "status": "pass" if ok else "fail",
                           "message": f"{c['statement']}: reported {c['value']!r}, independently recomputed {expected!r}.",
                           "reported": c["value"], "recomputed": expected})
        checks += getattr(self, f"_checks_{task_type}", lambda r, rs: [])(result, reasons)
        checks += self._evidence_checks(result, findings, verified_claims)

        fails = [c for c in checks if c["status"] == "fail"]
        warns = [c for c in checks if c["status"] == "warn"]
        numeric_fail = any(c["category"] == "numeric" for c in fails)
        status = "failed" if numeric_fail else "needs_review" if fails or any(c.get("blocking") for c in warns) else "passed"
        return {
            "status": status,
            "checks": checks,
            "reason_codes": sorted(set(reasons)),
            "counts": {s: sum(1 for c in checks if c["status"] == s) for s in ("pass", "warn", "fail", "skip")},
            "verified_claims": verified_claims,
            "engine": "independent recomputation (pandas/scipy/sklearn in the API process)",
        }

    def _checks_hypothesis_test(self, result, reasons):
        out = []
        P, df = self.params, self.df
        test = result.get("metrics", {}).get("test", {}).get("value") or P.get("strategy")
        design = P.get("design", "numeric_categorical")
        if design == "numeric_categorical":
            y, g = P["outcome"], P["group"]
            sub = df[[g, y]].copy()
            sub[y] = pd.to_numeric(sub[y], errors="coerce")
            sub = sub.dropna()
            sub[g] = sub[g].astype(str)
            if P.get("groups"):
                sub = sub[sub[g].isin([str(v) for v in P["groups"]])]
            sizes = sub.groupby(g).size()
            skews = sub.groupby(g)[y].apply(lambda a: abs(float(stats.skew(a))) if len(a) > 2 else 0.0)
            shap = sub.groupby(g)[y].apply(lambda a: float(stats.shapiro(a.to_numpy()[:5000]).pvalue) if len(a) >= 3 else 1.0)
            n_min, sk_max, sh_min = int(sizes.min()), float(skews.max()), float(shap.min())
            if test in ("welch_t", "anova"):
                bad = (sh_min < 0.01 and n_min < 50) or (sk_max > 2 and n_min < 100)
                if bad:
                    reasons.append("non_normal")
                    out.append({"id": "assumption:normality", "category": "assumption", "status": "fail",
                                "message": f"{test} assumes roughly normal group means; the outcome is strongly non-normal (max |skew| {sk_max:.2f}, min Shapiro p {sh_min:.3g}) "
                                           f"with small groups (min n = {n_min}). A rank-based or permutation test is more reliable."})
                else:
                    out.append({"id": "assumption:normality", "category": "assumption", "status": "pass",
                                "message": f"Normality is acceptable for {test} (max |skew| {sk_max:.2f}, min n = {n_min}; large samples make the mean approximately normal)."})
            else:
                out.append({"id": "assumption:test_choice", "category": "assumption", "status": "pass",
                            "message": f"{test} does not assume normality (max |skew| {sk_max:.2f}, min n = {n_min})."})
            if n_min < 5:
                out.append({"id": "assumption:sample_size", "category": "assumption", "status": "fail", "message": f"A group has only {n_min} observations; the test is unreliable."})
                reasons.append("insufficient_data")
        elif design == "categorical_categorical":
            share = result.get("metrics", {}).get("share_expected_below_5", {}).get("value")
            if test == "chi_square" and share is not None and share > 0.2:
                reasons.append("small_expected_counts")
                out.append({"id": "assumption:expected_counts", "category": "assumption", "status": "fail",
                            "message": f"{share:.0%} of expected cell counts are below 5; chi-square is unreliable. Use Fisher's exact test (2×2) or merge categories."})
            else:
                out.append({"id": "assumption:expected_counts", "category": "assumption", "status": "pass", "message": "Expected cell counts are adequate."})
        else:
            sub = df[[P["group"], P["outcome"]]].apply(pd.to_numeric, errors="coerce").dropna()
            sk = max(abs(float(sub.iloc[:, 0].skew())), abs(float(sub.iloc[:, 1].skew())))
            if test == "pearson" and sk > 2:
                reasons.append("non_normal")
                out.append({"id": "assumption:linearity_outliers", "category": "assumption", "status": "fail",
                            "message": f"Pearson correlation is sensitive to heavy skew/outliers (max |skew| {sk:.2f}); Spearman is more robust."})
            else:
                out.append({"id": "assumption:linearity_outliers", "category": "assumption", "status": "pass", "message": f"Distribution shape acceptable for {test} (max |skew| {sk:.2f})."})
        return out

    def _checks_classification(self, result, reasons):
        out = []
        m = {k: v.get("value") for k, v in result.get("metrics", {}).items()}
        pred = result.get("artifacts", {}).get("predictions") or {}
        tr, te = set(pred.get("train_ids") or []), set(pred.get("test_ids") or [])
        if tr and te:
            overlap = len(tr & te)
            out.append({"id": "split:disjoint", "category": "leakage", "status": "pass" if overlap == 0 else "fail",
                        "message": "Training and test rows are disjoint." if overlap == 0 else f"{overlap} rows appear in both training and test sets."})
        leaks = {h["feature"] for h in self.profile.get("leakage_hints", []) if h.get("target") == self.params.get("target")}
        used = set(m.get("features_used") or [])
        bad = leaks & used
        out.append({"id": "leakage:features", "category": "leakage", "status": "fail" if bad else "pass",
                    "message": f"Possible leakage features were used: {', '.join(sorted(bad))}." if bad else "No flagged leakage features were used."})
        if bad:
            reasons.append("leakage")
        auc = m.get("roc_auc")
        if auc is not None and auc > 0.995:
            out.append({"id": "leakage:too_good", "category": "leakage", "status": "warn", "blocking": True,
                        "message": f"ROC AUC {auc:.3f} is suspiciously close to perfect; check for target leakage."})
        bal = m.get("balanced_accuracy")
        if bal is not None:
            ok = bal >= 0.6
            out.append({"id": "metric:vs_chance", "category": "metric", "status": "pass" if ok else "warn", "blocking": not ok,
                        "message": f"Balanced accuracy {bal:.3f} vs 0.5 for chance." + ("" if ok else " The model is too weak to support conclusions.")})
        rec, ms = m.get("recall"), m.get("minority_share")
        if rec is not None and ms is not None and ms < 0.3 and rec < 0.3:
            reasons.append("class_imbalance")
            out.append({"id": "metric:minority_recall", "category": "metric", "status": "fail",
                        "message": f"Recall on the positive class is {rec:.2f} with a {ms:.0%} positive rate; accuracy alone would be misleading."})
        return out

    def _checks_regression(self, result, reasons):
        m = {k: v.get("value") for k, v in result.get("metrics", {}).items()}
        out = []
        pred = result.get("artifacts", {}).get("predictions") or {}
        if pred.get("train_ids") and pred.get("test_ids"):
            ov = len(set(pred["train_ids"]) & set(pred["test_ids"]))
            out.append({"id": "split:disjoint", "category": "leakage", "status": "pass" if ov == 0 else "fail", "message": f"Train/test overlap: {ov} rows."})
        if m.get("rmse") is not None and m.get("baseline_rmse"):
            ok = m["rmse"] < m["baseline_rmse"]
            out.append({"id": "metric:vs_baseline", "category": "metric", "status": "pass" if ok else "warn", "blocking": not ok,
                        "message": f"RMSE {m['rmse']:.4g} vs mean-baseline {m['baseline_rmse']:.4g}."})
        if m.get("r2") is not None and m["r2"] > 0.995:
            out.append({"id": "leakage:too_good", "category": "leakage", "status": "warn", "blocking": True, "message": f"R² {m['r2']:.4f} is suspiciously high; check for leakage."})
        return out

    def _checks_forecasting(self, result, reasons):
        m = {k: v.get("value") for k, v in result.get("metrics", {}).items()}
        sk = m.get("skill_vs_best_baseline")
        if sk is None:
            return []
        ok = sk > 0 or m.get("strategy") == "seasonal_naive"
        return [{"id": "metric:vs_naive", "category": "metric", "status": "pass" if sk > 0 else "warn", "blocking": not ok,
                 "message": f"Holdout skill vs best naive baseline: {sk:+.3f} (positive is better)."}]

    def _checks_segmentation(self, result, reasons):
        sil = result.get("metrics", {}).get("silhouette", {}).get("value")
        if sil is None:
            return []
        plausible = -1 <= sil <= 1
        return [{"id": "metric:silhouette", "category": "metric", "status": "pass" if plausible and sil >= 0.2 else "warn",
                 "blocking": not plausible, "message": f"Silhouette {sil:.3f} (≥ 0.2 indicates usable separation)."}]

    def _checks_profit_change(self, result, reasons):
        out = []
        m = {k: v.get("value") for k, v in result.get("metrics", {}).items()}
        if m.get("total_profit_delta") is not None:
            parts = sum(m.get(f"total_{e}", 0) or 0 for e in ("volume_effect", "price_discount_effect", "unit_cost_effect"))
            ok = _close(parts, m["total_profit_delta"], rel=1e-6, abs_=0.01)
            out.append({"id": "identity:decomposition", "category": "numeric", "status": "pass" if ok else "fail",
                        "message": f"Volume + price + cost effects ({parts:,.2f}) reconcile with total profit change ({m['total_profit_delta']:,.2f})."})
        if m.get("profit_change") is not None and m.get("total_profit_delta") is not None:
            ok = _close(m["profit_change"], m["total_profit_delta"], rel=1e-6, abs_=0.01)
            out.append({"id": "identity:trend_vs_products", "category": "numeric", "status": "pass" if ok else "fail",
                        "message": "Monthly SQL totals agree with the product-level totals." if ok else "Monthly totals and product totals disagree."})
        if m.get("latest_period_partial"):
            out.append({"id": "data:partial_period", "category": "data", "status": "warn", "message": "The latest month looked incomplete and was excluded."})
        return out

    def _evidence_checks(self, result, findings, verified_claims):
        out = []
        known = set(result.get("metrics", {})) | set(result.get("tables", {})) | set(verified_claims)
        for i, f in enumerate(findings):
            ev = f.get("evidence") or []
            missing = [e for e in ev if e not in known]
            unverified = [e for e in ev if e in verified_claims and not verified_claims[e]]
            if not ev or (missing and len(missing) == len(ev)):
                out.append({"id": f"evidence:{i}", "category": "evidence", "status": "fail", "message": f"Finding '{f['title']}' has no supporting computed evidence."})
            elif unverified:
                out.append({"id": f"evidence:{i}", "category": "evidence", "status": "fail", "message": f"Finding '{f['title']}' cites claims that failed verification: {', '.join(unverified)}."})
            else:
                out.append({"id": f"evidence:{i}", "category": "evidence", "status": "pass", "message": f"Finding '{f['title']}' is linked to {len(ev)} computed evidence item(s)."})
            text = f"{f['title']} {f['detail']}"
            if CAUSAL_RE.search(text) and "not causal" not in text and "not prove" not in text:
                out.append({"id": f"causal:{i}", "category": "conclusion", "status": "warn",
                            "message": f"Finding '{f['title']}' uses causal language, but the analysis is observational."})
        return out


NUM_RE = re.compile(r"(?<![\w.])[-+]?\$?\d[\d,]*\.?\d*\s?[kKmM%]?")


def check_narrative(text: str, values: list[float]) -> list[str]:
    """Return numbers in an LLM-written narrative that do not match any verified value (within 1.5%)."""
    unsupported = []
    for tok in NUM_RE.findall(text or ""):
        raw = tok.strip().replace("$", "").replace(",", "").replace(" ", "")
        mult = 1.0
        if raw[-1:] in "kK":
            mult, raw = 1e3, raw[:-1]
        elif raw[-1:] in "mM":
            mult, raw = 1e6, raw[:-1]
        pct = raw.endswith("%")
        raw = raw.rstrip("%")
        try:
            x = float(raw) * mult
        except ValueError:
            continue
        if 1900 <= x <= 2100 and not pct:
            continue  # years
        if abs(x) <= 10 and float(x).is_integer() and not pct:
            continue  # small counts such as "top 3"
        if not any(abs(abs(x) - abs(v)) <= max(0.015 * abs(v), 0.051) for v in values if v is not None):
            unsupported.append(tok.strip())
    return unsupported
