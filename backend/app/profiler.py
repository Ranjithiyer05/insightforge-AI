"""Data profiler: types, quality issues, semantic roles, candidate targets and leakage hints.

Everything reported here is computed from the dataframe; nothing is guessed by a
language model. Heuristic judgements (e.g. "this looks like a date column") are
labelled as heuristics in the output.
"""
from __future__ import annotations

import math
import re
import warnings
from typing import Any

import numpy as np
import pandas as pd

ROLE_PATTERNS: dict[str, list[str]] = {
    "date": [r"date", r"^day$", r"month", r"period", r"timestamp", r"^time$", r"order_?dt", r"week", r"^year$"],
    "revenue": [r"revenue", r"sales", r"turnover", r"gross", r"amount", r"income"],
    "cost": [r"cost", r"cogs", r"expense", r"spend"],
    "profit": [r"profit", r"margin", r"earnings"],
    "product": [r"product", r"sku", r"item", r"category", r"brand"],
    "quantity": [r"qty", r"quantity", r"units", r"volume", r"(^|_)count$"],
    "discount": [r"discount", r"promo", r"markdown", r"coupon"],
    "price": [r"price", r"unit_?price", r"rate"],
    "region": [r"region", r"store", r"country", r"city", r"state", r"location", r"channel"],
    "id": [r"(^|_)id$", r"^id_", r"uuid", r"identifier", r"_key$", r"^order_?no", r"number$"],
}

TARGET_HINTS = [
    "churn", "default", "attrition", "left", "turnover", "target", "label", "outcome", "converted",
    "conversion", "fraud", "passed", "pass", "response", "clicked", "purchased", "y",
]


def _is_datetime_like(s: pd.Series) -> tuple[bool, float]:
    if pd.api.types.is_datetime64_any_dtype(s):
        return True, 1.0
    if not (pd.api.types.is_object_dtype(s) or pd.api.types.is_string_dtype(s)):
        return False, 0.0
    sample = s.dropna().astype(str).head(200)
    if sample.empty:
        return False, 0.0
    # Require something date-shaped to avoid treating "12" as a date.
    if not sample.str.contains(r"\d{1,4}[-/.]\d{1,2}|\d{4}", regex=True).mean() > 0.8:
        return False, 0.0
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        parsed = pd.to_datetime(sample, errors="coerce", format="mixed")
    ok = float(parsed.notna().mean())
    return ok >= 0.9, ok


def infer_semantic_type(s: pd.Series, n_rows: int) -> str:
    nn = s.dropna()
    nunique = nn.nunique()
    if nn.empty:
        return "empty"
    if pd.api.types.is_bool_dtype(s) or (nunique == 2 and set(map(str, nn.unique())) <= {"0", "1", "True", "False", "true", "false", "yes", "no", "Yes", "No", "Y", "N", "0.0", "1.0"}):
        return "boolean"
    if pd.api.types.is_numeric_dtype(s):
        if pd.api.types.is_integer_dtype(s) or (nn % 1 == 0).all():
            if nunique <= 12 and n_rows > 50:
                return "categorical_numeric"
            return "integer"
        return "numeric"
    is_dt, _ = _is_datetime_like(s)
    if is_dt:
        return "datetime"
    avg_len = nn.astype(str).str.len().mean()
    if nunique == len(nn) and len(nn) > 20:
        return "identifier" if avg_len < 40 else "text"
    if nunique <= max(50, 0.05 * n_rows) and avg_len < 60:
        return "categorical"
    return "text"


def _roles_for(name: str) -> list[str]:
    low = name.lower().replace(" ", "_")
    return [role for role, pats in ROLE_PATTERNS.items() if any(re.search(p, low) for p in pats)]


def _inconsistent_categories(s: pd.Series) -> list[list[str]]:
    vals = s.dropna().astype(str)
    if vals.nunique() > 500:
        return []
    groups: dict[str, set[str]] = {}
    for v in vals.unique():
        key = re.sub(r"[\s_\-]+", " ", v.strip().lower())
        groups.setdefault(key, set()).add(v)
    return [sorted(g) for g in groups.values() if len(g) > 1][:10]


def _finite(x: Any) -> Any:
    if isinstance(x, (float, np.floating)):
        return None if (math.isnan(x) or math.isinf(x)) else float(x)
    if isinstance(x, np.integer):
        return int(x)
    return x


def profile_dataframe(df: pd.DataFrame) -> dict[str, Any]:
    n_rows, n_cols = df.shape
    columns: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    roles: dict[str, list[str]] = {}

    dup_count = int(df.duplicated().sum())
    if dup_count:
        issues.append({
            "severity": "warning", "kind": "duplicates", "column": None,
            "message": f"{dup_count:,} fully duplicated rows ({dup_count / n_rows:.1%}).",
            "suggested_fix": "drop_duplicates", "destructive": True,
        })

    for col in df.columns:
        s = df[col]
        stype = infer_semantic_type(s, n_rows)
        missing = int(s.isna().sum())
        info: dict[str, Any] = {
            "name": col,
            "dtype": str(s.dtype),
            "semantic_type": stype,
            "missing": missing,
            "missing_pct": round(missing / n_rows, 4) if n_rows else 0,
            "unique": int(s.nunique(dropna=True)),
            "examples": [_finite(v) if not isinstance(v, str) else v[:60] for v in s.dropna().head(3).tolist()],
            "roles": [],
        }
        if missing / max(n_rows, 1) > 0.3:
            issues.append({"severity": "warning", "kind": "missing", "column": col,
                           "message": f"'{col}' is {missing / n_rows:.0%} missing.", "suggested_fix": "review_missing", "destructive": False})
        elif missing:
            issues.append({"severity": "info", "kind": "missing", "column": col,
                           "message": f"'{col}' has {missing:,} missing values ({missing / n_rows:.1%}).", "suggested_fix": None, "destructive": False})

        if stype in ("numeric", "integer"):
            x = pd.to_numeric(s, errors="coerce").dropna()
            q1, q3 = x.quantile(0.25), x.quantile(0.75)
            iqr = q3 - q1
            n_out = int(((x < q1 - 1.5 * iqr) | (x > q3 + 1.5 * iqr)).sum()) if iqr > 0 else 0
            info["stats"] = {k: _finite(v) for k, v in {
                "mean": x.mean(), "std": x.std(), "min": x.min(), "p25": q1, "median": x.median(),
                "p75": q3, "max": x.max(), "skew": x.skew() if len(x) > 2 else None,
            }.items()}
            info["outliers_iqr"] = n_out
            if n_out and n_out / max(len(x), 1) > 0.01:
                issues.append({"severity": "info", "kind": "outliers", "column": col,
                               "message": f"'{col}' has {n_out:,} values outside 1.5×IQR ({n_out / len(x):.1%}).",
                               "suggested_fix": None, "destructive": False})
            if (x < 0).any() and any(r in _roles_for(col) for r in ("quantity", "price")):
                issues.append({"severity": "warning", "kind": "invalid_values", "column": col,
                               "message": f"'{col}' contains {int((x < 0).sum())} negative values (returns or data errors?).",
                               "suggested_fix": None, "destructive": False})
        elif stype in ("categorical", "boolean", "categorical_numeric"):
            vc = s.astype(str).where(s.notna()).value_counts().head(8)
            info["top_values"] = [{"value": str(k), "count": int(v)} for k, v in vc.items()]
            inc = _inconsistent_categories(s) if stype == "categorical" else []
            if inc:
                info["inconsistent_groups"] = inc
                issues.append({"severity": "warning", "kind": "inconsistent_categories", "column": col,
                               "message": f"'{col}' has inconsistent spellings: " + "; ".join(" / ".join(g) for g in inc[:3]),
                               "suggested_fix": "normalize_categories", "destructive": True})
        elif stype == "datetime":
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                d = pd.to_datetime(s, errors="coerce", format="mixed")
            info["stats"] = {"min": str(d.min().date()) if d.notna().any() else None,
                             "max": str(d.max().date()) if d.notna().any() else None}
            unparsed = int(d.isna().sum() - missing)
            if unparsed > 0:
                issues.append({"severity": "warning", "kind": "unparseable_dates", "column": col,
                               "message": f"{unparsed} values in '{col}' could not be parsed as dates.",
                               "suggested_fix": None, "destructive": False})
        if stype == "empty":
            issues.append({"severity": "warning", "kind": "empty_column", "column": col,
                           "message": f"'{col}' is entirely empty.", "suggested_fix": "drop_column", "destructive": True})

        r = _roles_for(col)
        if stype == "datetime" and "date" not in r:
            r.append("date")
        if "date" in r and stype not in ("datetime",) and not (stype in ("integer", "categorical_numeric") and re.search("year|month|week", col.lower())):
            r.remove("date")
        if stype == "identifier" and "id" not in r:
            r.append("id")
        if stype not in ("numeric", "integer", "categorical_numeric"):
            for numeric_role in ("revenue", "cost", "profit", "quantity", "discount", "price"):
                if numeric_role in r:
                    r.remove(numeric_role)
        info["roles"] = r
        for role in r:
            roles.setdefault(role, []).append(col)
        columns.append(info)

    candidate_targets = _candidate_targets(df, columns)
    leakage = _leakage_hints(df, columns, candidate_targets)
    for lk in leakage:
        issues.append({"severity": "warning", "kind": "possible_leakage", "column": lk["feature"],
                       "message": lk["message"], "suggested_fix": "exclude_feature", "destructive": False})

    numeric_cols = [c["name"] for c in columns if c["semantic_type"] in ("numeric", "integer")]
    categorical_cols = [c["name"] for c in columns if c["semantic_type"] in ("categorical", "boolean", "categorical_numeric")]
    datetime_cols = [c["name"] for c in columns if c["semantic_type"] == "datetime"]
    total_missing = int(df.isna().sum().sum())
    quality_score = max(0.0, 1.0 - (total_missing / max(df.size, 1)) - 0.5 * dup_count / max(n_rows, 1)
                        - 0.03 * sum(1 for i in issues if i["severity"] == "warning"))

    return {
        "n_rows": int(n_rows),
        "n_cols": int(n_cols),
        "duplicates": dup_count,
        "missing_cells": total_missing,
        "missing_pct": round(total_missing / max(df.size, 1), 4),
        "memory_kb": round(df.memory_usage(deep=True).sum() / 1024, 1),
        "columns": columns,
        "roles": roles,
        "numeric_columns": numeric_cols,
        "categorical_columns": categorical_cols,
        "datetime_columns": datetime_cols,
        "candidate_targets": candidate_targets,
        "leakage_hints": leakage,
        "issues": issues,
        "quality_score": round(quality_score, 3),
        "notes": ["Semantic types and roles are heuristics based on column names and values; review them before relying on them."],
    }


def _candidate_targets(df: pd.DataFrame, columns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for c in columns:
        name = c["name"].lower()
        hint = any(re.search(rf"(^|_|\b){h}(_|\b|$)", name) for h in TARGET_HINTS)
        st = c["semantic_type"]
        if st == "boolean" or (st in ("categorical", "categorical_numeric") and 2 <= c["unique"] <= 10):
            score = 0.4 + (0.5 if hint else 0)
            out.append({"column": c["name"], "task": "classification", "score": round(score, 2),
                        "reason": "binary/low-cardinality column" + (" with a target-like name" if hint else "")})
        elif st in ("numeric", "integer") and "id" not in c["roles"]:
            score = 0.2 + (0.4 if hint else 0) + (0.3 if set(c["roles"]) & {"revenue", "profit"} else 0)
            out.append({"column": c["name"], "task": "regression", "score": round(score, 2),
                        "reason": "continuous numeric column" + (" with a target-like name" if hint else "")})
    return sorted(out, key=lambda x: -x["score"])[:6]


def _leakage_hints(df: pd.DataFrame, columns: list[dict[str, Any]], targets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    by_name = {c["name"]: c for c in columns}
    for t in targets[:3]:
        tcol = t["column"]
        if t["task"] != "classification" or t["score"] < 0.8:
            continue
        y = df[tcol]
        for c in columns:
            f = c["name"]
            if f == tcol or c["semantic_type"] in ("identifier", "text", "empty"):
                continue
            low = f.lower()
            if tcol.lower() in low or re.search(r"(cancel|termination|exit|closed|resolution)_?(date|reason)?", low):
                hints.append({"target": tcol, "feature": f,
                              "message": f"'{f}' may be recorded after the outcome '{tcol}' (name suggests post-outcome information)."})
                continue
            try:
                sub = pd.DataFrame({"x": df[f], "y": y}).dropna()
                if len(sub) < 30:
                    continue
                if by_name[f]["semantic_type"] in ("numeric", "integer"):
                    yy = pd.factorize(sub["y"])[0]
                    if len(set(yy)) == 2:
                        r = abs(np.corrcoef(sub["x"].astype(float), yy)[0, 1])
                        if r > 0.9:
                            hints.append({"target": tcol, "feature": f, "message": f"'{f}' correlates almost perfectly with '{tcol}' (|r|={r:.2f}); possible leakage."})
                else:
                    purity = sub.groupby("x")["y"].agg(lambda v: v.value_counts(normalize=True).iloc[0])
                    weights = sub["x"].value_counts(normalize=True)
                    wp = float((purity * weights.reindex(purity.index)).sum())
                    if wp > 0.98 and sub["x"].nunique() < len(sub) * 0.5:
                        hints.append({"target": tcol, "feature": f, "message": f"'{f}' determines '{tcol}' almost perfectly ({wp:.0%} purity); possible leakage."})
            except Exception:
                continue
    return hints[:10]


def dataset_signature(profile: dict[str, Any], target: str | None = None, df: pd.DataFrame | None = None) -> dict[str, Any]:
    """Compact, numeric description of a dataset used for memory retrieval."""
    n = profile.get("n_rows", 0)
    sig: dict[str, Any] = {
        "log_rows": round(math.log10(max(n, 1)), 2),
        "n_cols": profile.get("n_cols", 0),
        "frac_numeric": round(len(profile.get("numeric_columns", [])) / max(profile.get("n_cols", 1), 1), 2),
        "frac_categorical": round(len(profile.get("categorical_columns", [])) / max(profile.get("n_cols", 1), 1), 2),
        "missing_pct": profile.get("missing_pct", 0),
        "has_datetime": bool(profile.get("datetime_columns")),
        "target_type": None,
        "minority_share": None,
        "target_skew": None,
    }
    if target and df is not None and target in df.columns:
        y = df[target].dropna()
        if y.nunique() <= 10:
            sig["target_type"] = "binary" if y.nunique() == 2 else "multiclass"
            sig["minority_share"] = round(float(y.value_counts(normalize=True).min()), 3)
        else:
            sig["target_type"] = "continuous"
            try:
                sig["target_skew"] = round(float(pd.to_numeric(y, errors="coerce").skew()), 2)
            except Exception:
                pass
    return sig


def preview_rows(df: pd.DataFrame, n: int = 50) -> list[dict[str, Any]]:
    head = df.head(n).astype(object).where(df.head(n).notna(), None)
    return [{k: _finite(v) for k, v in row.items()} for row in head.to_dict(orient="records")]


def apply_cleaning(df: pd.DataFrame, ops: list[dict[str, Any]]) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Apply user-approved cleaning operations; returns new frame and an audit log."""
    out = df.copy()
    log = []
    for op in ops:
        kind = op.get("op")
        before = len(out)
        if kind == "drop_duplicates":
            out = out.drop_duplicates()
            log.append({"op": kind, "rows_removed": before - len(out)})
        elif kind == "normalize_categories":
            col = op["column"]
            if col not in out.columns:
                raise ValueError(f"unknown column {col}")
            original = out[col].copy()
            norm = out[col].astype(str).str.strip()
            key = norm.str.lower().str.replace(r"[\s_\-]+", " ", regex=True)
            canonical = norm.groupby(key).agg(lambda v: v.value_counts().index[0])
            out[col] = key.map(canonical).where(original.notna(), None)
            log.append({"op": kind, "column": col, "values_changed": int((original.astype(str) != out[col].astype(str)).sum())})
        elif kind == "drop_column":
            col = op["column"]
            out = out.drop(columns=[col])
            log.append({"op": kind, "column": col})
        elif kind == "drop_missing_rows":
            col = op["column"]
            out = out[out[col].notna()]
            log.append({"op": kind, "column": col, "rows_removed": before - len(out)})
        elif kind == "fill_missing":
            col, method = op["column"], op.get("method", "median")
            if col not in out.columns:
                raise ValueError(f"unknown column {col}")
            n = int(out[col].isna().sum())
            if method in ("median", "mean"):
                num = pd.to_numeric(out[col], errors="coerce")
                if num.notna().sum() == 0:
                    raise ValueError(f"'{col}' is not numeric; use mode or constant")
                fill = float(num.median() if method == "median" else num.mean())
                out[col] = num.fillna(fill)
            elif method == "mode":
                m = out[col].mode(dropna=True)
                if m.empty:
                    raise ValueError(f"'{col}' has no values to take a mode from")
                fill = m.iloc[0]
                out[col] = out[col].fillna(fill)
            elif method == "constant":
                fill = op.get("value")
                if fill is None or str(fill) == "":
                    raise ValueError("a constant value is required")
                if pd.api.types.is_numeric_dtype(out[col]):
                    fill = float(fill)
                out[col] = out[col].fillna(fill)
            else:
                raise ValueError(f"unknown fill method '{method}'")
            log.append({"op": kind, "column": col, "method": method, "value": _finite(fill) if not isinstance(fill, str) else fill, "cells_filled": n})
        else:
            raise ValueError(f"unsupported cleaning operation '{kind}'")
    return out, log


HANDLING = {
    "hypothesis_test": "Rows with a missing value in the tested columns are excluded (no values are invented).",
    "comparison": "Rows with a missing value in the compared columns are excluded.",
    "descriptive": "Statistics are computed on the non-missing values of each column.",
    "classification": "Inside the model only, numeric gaps are filled with the training median and categorical gaps with the most frequent value. Rows with a missing target are excluded.",
    "regression": "Inside the model only, numeric gaps are filled with the training median and categorical gaps with the most frequent value. Rows with a missing target are excluded.",
    "segmentation": "Numeric gaps are filled with the column median before clustering.",
    "anomaly_detection": "Numeric gaps are filled with the column median before scoring.",
    "forecasting": "Rows with a missing date or value are skipped when totals per period are computed.",
    "profit_change": "Rows missing revenue, cost or quantity are excluded; a missing discount is treated as 0.",
}


def used_columns(params: dict[str, Any], columns: list[str]) -> list[str]:
    cols: list[str] = []
    for k, v in (params or {}).items():
        if k == "excluded_features":
            continue
        for x in (v if isinstance(v, list) else [v]):
            if isinstance(x, str) and x in columns and x not in cols:
                cols.append(x)
    return cols


def data_handling(df: pd.DataFrame, task: str, params: dict[str, Any]) -> dict[str, Any]:
    """Factual summary of missing values in the columns an analysis used, computed from the raw file."""
    cols = used_columns(params, list(df.columns))
    sub = df[cols] if cols else df.iloc[:, :0]
    per_col = {c: int(sub[c].isna().sum()) for c in cols if int(sub[c].isna().sum())}
    rows_affected = int(sub.isna().any(axis=1).sum()) if cols else 0
    return {"rows_total": int(len(df)), "columns_used": cols, "missing_by_column": per_col, "rows_with_missing": rows_affected,
            "policy": HANDLING.get(task, "Missing values are excluded from calculations.")}
