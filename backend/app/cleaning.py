"""Transparent, user-confirmed data cleaning.

Each operation is a small pure function on a dataframe. `run_operations`
applies them in order and records, for every step, what was asked, why, how
many rows and cells changed and before/after statistics for the touched
columns. The original dataset is never modified: callers store the result as a
new dataset version that points back to its parent.
"""
from __future__ import annotations

import re
import warnings
from typing import Any, Callable

import numpy as np
import pandas as pd

from .profiler import _finite

OPS: dict[str, dict[str, Any]] = {
    "drop_duplicates": {"label": "Remove duplicate rows", "needs_column": False},
    "drop_column": {"label": "Remove column", "needs_column": True},
    "rename_column": {"label": "Rename column", "needs_column": True},
    "drop_missing_rows": {"label": "Drop rows missing a value", "needs_column": True},
    "fill_missing": {"label": "Fill missing values", "needs_column": True},
    "convert_type": {"label": "Convert data type", "needs_column": True},
    "parse_dates": {"label": "Parse and standardise dates", "needs_column": True},
    "normalize_categories": {"label": "Standardise category spellings", "needs_column": True},
    "normalize_text": {"label": "Normalise text", "needs_column": True},
    "cap_outliers": {"label": "Cap outliers (IQR)", "needs_column": True},
    "remove_outliers": {"label": "Remove outlier rows (IQR)", "needs_column": True},
    "replace_value": {"label": "Replace a value", "needs_column": True},
}


class CleaningError(ValueError):
    pass


def col_stats(s: pd.Series) -> dict[str, Any]:
    out: dict[str, Any] = {"dtype": str(s.dtype), "missing": int(s.isna().sum()), "unique": int(s.nunique(dropna=True))}
    if pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s):
        x = s.dropna()
        if len(x):
            out.update({k: _finite(v) for k, v in {"mean": x.mean(), "median": x.median(), "std": x.std(), "min": x.min(), "max": x.max()}.items()})
    return out


def _col(df: pd.DataFrame, op: dict[str, Any]) -> str:
    c = op.get("column")
    if not c or c not in df.columns:
        raise CleaningError(f"Column '{c}' does not exist.")
    return c


def _iqr_bounds(x: pd.Series, k: float) -> tuple[float, float]:
    q1, q3 = x.quantile(0.25), x.quantile(0.75)
    iqr = q3 - q1
    return float(q1 - k * iqr), float(q3 + k * iqr)


def _op_drop_duplicates(df, op):
    subset = op.get("columns") or None
    out = df.drop_duplicates(subset=subset, keep="first")
    return out, {"rows_removed": len(df) - len(out), "columns": subset or "all"}, []


def _op_drop_column(df, op):
    c = _col(df, op)
    return df.drop(columns=[c]), {"cells_removed": int(df[c].notna().sum())}, []


def _op_rename_column(df, op):
    c = _col(df, op)
    new = str(op.get("new_name", "")).strip()[:120]
    if not new:
        raise CleaningError("A new column name is required.")
    if new in df.columns and new != c:
        raise CleaningError(f"A column named '{new}' already exists.")
    return df.rename(columns={c: new}), {"from": c, "to": new}, [new]


def _op_drop_missing_rows(df, op):
    c = _col(df, op)
    out = df[df[c].notna()]
    return out, {"rows_removed": len(df) - len(out)}, [c]


def _op_fill_missing(df, op):
    c = _col(df, op)
    method = op.get("method", "median")
    out = df.copy()
    n = int(out[c].isna().sum())
    if method in ("median", "mean"):
        num = pd.to_numeric(out[c], errors="coerce")
        if num.notna().sum() == 0:
            raise CleaningError(f"'{c}' is not numeric; use the most common value or a constant.")
        fill: Any = float(num.median() if method == "median" else num.mean())
        out[c] = out[c].where(out[c].notna(), fill)
        if pd.api.types.is_numeric_dtype(df[c]):
            out[c] = pd.to_numeric(out[c])
    elif method == "mode":
        m = out[c].mode(dropna=True)
        if m.empty:
            raise CleaningError(f"'{c}' has no values to take the most common value from.")
        fill = m.iloc[0]
        out[c] = out[c].fillna(fill)
    elif method == "constant":
        fill = op.get("value")
        if fill is None or str(fill) == "":
            raise CleaningError("A constant value is required.")
        if pd.api.types.is_numeric_dtype(out[c]):
            try:
                fill = float(fill)
            except ValueError:
                raise CleaningError(f"'{c}' is numeric, so the fill value must be a number.") from None
        out[c] = out[c].fillna(fill)
    elif method in ("ffill", "bfill"):
        out[c] = out[c].ffill() if method == "ffill" else out[c].bfill()
        fill = method
    else:
        raise CleaningError(f"Unknown fill method '{method}'.")
    return out, {"cells_filled": n - int(out[c].isna().sum()), "method": method, "value": _finite(fill) if not isinstance(fill, str) else fill}, [c]


def _op_convert_type(df, op):
    c = _col(df, op)
    to = op.get("to")
    out = df.copy()
    before_missing = int(out[c].isna().sum())
    s = out[c]
    if to in ("numeric", "integer"):
        cleaned = s.astype("string").str.replace(r"[,\s$€£%]", "", regex=True) if not pd.api.types.is_numeric_dtype(s) else s
        conv = pd.to_numeric(cleaned, errors="coerce")
        if to == "integer":
            if (conv.dropna() % 1 != 0).any():
                raise CleaningError(f"'{c}' has decimal values; convert to numeric instead, or round first.")
            conv = conv.astype("Int64")
        out[c] = conv
    elif to == "string":
        out[c] = s.astype("string")
    elif to == "boolean":
        m = s.astype("string").str.strip().str.lower().map({"1": True, "0": False, "true": True, "false": False, "yes": True, "no": False,
                                                           "y": True, "n": False, "t": True, "f": False, "1.0": True, "0.0": False})
        out[c] = m.astype("boolean")
    elif to == "datetime":
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            out[c] = pd.to_datetime(s, errors="coerce", format="mixed", dayfirst=bool(op.get("dayfirst")))
    else:
        raise CleaningError("Choose a target type: numeric, integer, string, boolean or datetime.")
    failed = int(out[c].isna().sum()) - before_missing
    warn = [f"{failed:,} values in '{c}' could not be converted to {to} and became missing."] if failed > 0 else []
    return out, {"to": to, "values_not_convertible": max(failed, 0), "warnings": warn}, [c]


def _op_parse_dates(df, op):
    c = _col(df, op)
    fmt = op.get("output_format", "%Y-%m-%d")
    if fmt not in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m"):
        raise CleaningError("Output format must be YYYY-MM-DD, YYYY-MM-DD HH:MM:SS or YYYY-MM.")
    out = df.copy()
    before_missing = int(out[c].isna().sum())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        d = pd.to_datetime(out[c], errors="coerce", format="mixed", dayfirst=bool(op.get("dayfirst")))
    unparsed = int(d.isna().sum()) - before_missing
    if op.get("keep_unparsed", True) and unparsed > 0:
        # never silently discard: values that could not be parsed are kept as they were
        out[c] = d.dt.strftime(fmt).where(d.notna(), out[c].astype("string"))
    else:
        out[c] = d.dt.strftime(fmt)
    changed = int((out[c].astype("string") != df[c].astype("string")).fillna(False).sum())
    warn = [f"{unparsed:,} values in '{c}' could not be read as dates and were left unchanged."] if unparsed > 0 else []
    return out, {"values_changed": changed, "unparsed": max(unparsed, 0), "format": fmt, "warnings": warn}, [c]


def _op_normalize_categories(df, op):
    c = _col(df, op)
    out = df.copy()
    original = out[c].copy()
    norm = out[c].astype("string").str.strip()
    key = norm.str.lower().str.replace(r"[\s_\-]+", " ", regex=True)
    canonical = norm.groupby(key).agg(lambda v: v.value_counts().index[0])
    out[c] = key.map(canonical).where(original.notna(), None)
    changed = int((original.astype("string") != out[c].astype("string")).fillna(False).sum())
    mapping = {str(k): str(v) for k, v in pd.DataFrame({"from": original, "to": out[c]}).dropna().drop_duplicates().query("`from` != `to`").values[:50]}
    return out, {"values_changed": changed, "mapping": mapping}, [c]


def _op_normalize_text(df, op):
    c = _col(df, op)
    case = op.get("case", "none")
    out = df.copy()
    s = out[c].astype("string")
    s2 = s.str.strip().str.replace(r"\s+", " ", regex=True)
    if case == "lower":
        s2 = s2.str.lower()
    elif case == "upper":
        s2 = s2.str.upper()
    elif case == "title":
        s2 = s2.str.title()
    out[c] = s2.where(df[c].notna(), None)
    changed = int((s != s2).fillna(False).sum())
    return out, {"values_changed": changed, "case": case}, [c]


def _op_cap_outliers(df, op):
    c = _col(df, op)
    if not pd.api.types.is_numeric_dtype(df[c]):
        raise CleaningError(f"'{c}' is not numeric.")
    k = float(op.get("k", 1.5))
    lo, hi = _iqr_bounds(df[c].dropna(), k)
    out = df.copy()
    n = int(((df[c] < lo) | (df[c] > hi)).sum())
    out[c] = df[c].clip(lo, hi)
    return out, {"values_capped": n, "lower": round(lo, 6), "upper": round(hi, 6), "k": k}, [c]


def _op_remove_outliers(df, op):
    c = _col(df, op)
    if not pd.api.types.is_numeric_dtype(df[c]):
        raise CleaningError(f"'{c}' is not numeric.")
    k = float(op.get("k", 3.0))
    lo, hi = _iqr_bounds(df[c].dropna(), k)
    out = df[~((df[c] < lo) | (df[c] > hi))]
    return out, {"rows_removed": len(df) - len(out), "lower": round(lo, 6), "upper": round(hi, 6), "k": k}, [c]


def _op_replace_value(df, op):
    c = _col(df, op)
    old, new = op.get("old"), op.get("new")
    if old is None:
        raise CleaningError("Say which value to replace.")
    out = df.copy()
    s = out[c].astype("string")
    hits = s == str(old)
    new_val: Any = None if new in (None, "") else new
    if new_val is not None and pd.api.types.is_numeric_dtype(df[c]):
        try:
            new_val = float(new_val)
        except ValueError:
            raise CleaningError(f"'{c}' is numeric, so the replacement must be a number or empty.") from None
    if pd.api.types.is_numeric_dtype(df[c]):
        try:
            hits = df[c] == float(old)
        except ValueError:
            hits = pd.Series(False, index=df.index)
    out.loc[hits.fillna(False), c] = new_val
    return out, {"values_changed": int(hits.fillna(False).sum()), "old": old, "new": new_val}, [c]


_FUNCS: dict[str, Callable] = {k: globals()[f"_op_{k}"] for k in OPS}


def run_operations(df: pd.DataFrame, ops: list[dict[str, Any]]) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Apply operations in order. Returns the cleaned frame and a per-step audit log."""
    if not ops:
        raise CleaningError("Add at least one cleaning step.")
    if len(ops) > 50:
        raise CleaningError("At most 50 steps can be applied at once.")
    out = df
    log: list[dict[str, Any]] = []
    for i, op in enumerate(ops):
        kind = op.get("op")
        if kind not in _FUNCS:
            raise CleaningError(f"Unsupported cleaning operation '{kind}'.")
        col = op.get("column")
        before = col_stats(out[col]) if col in out.columns else None
        rows_before = len(out)
        try:
            out, detail, touched = _FUNCS[kind](out, op)
        except CleaningError as exc:
            raise CleaningError(f"Step {i + 1} ({OPS[kind]['label']}): {exc}") from None
        after_col = touched[0] if touched else None
        entry = {"step": i + 1, "op": kind, "label": OPS[kind]["label"], "column": col, "reason": str(op.get("reason") or "")[:300],
                 "params": {k: v for k, v in op.items() if k not in ("op", "column", "reason")},
                 "rows_before": rows_before, "rows_after": len(out), **{k: v for k, v in detail.items() if k != "warnings"},
                 "warnings": detail.get("warnings", []),
                 "before": before, "after": col_stats(out[after_col]) if after_col and after_col in out.columns else None}
        # legacy keys used by older UI code
        if "rows_removed" not in entry and entry["rows_before"] != entry["rows_after"]:
            entry["rows_removed"] = entry["rows_before"] - entry["rows_after"]
        log.append(entry)
    return out.reset_index(drop=True), log


def side_by_side(df: pd.DataFrame, cleaned: pd.DataFrame, log: list[dict[str, Any]], n: int = 20) -> dict[str, Any]:
    """Rows that changed, original next to cleaned, aligned on row position where rows were not removed."""
    from .profiler import preview_rows
    removed_rows = any(e["rows_after"] != e["rows_before"] for e in log)
    renamed = {e["from"]: e["to"] for e in log if e["op"] == "rename_column"}
    cols = [c for c in df.columns]
    if removed_rows or len(df) != len(cleaned):
        return {"aligned": False, "original": preview_rows(df, n), "cleaned": preview_rows(cleaned, n),
                "note": "Rows were removed, so the two previews show the first rows of each version rather than matched rows."}
    changed_idx: list[int] = []
    for c in cols:
        c2 = renamed.get(c, c)
        if c2 not in cleaned.columns:
            continue
        a, b = df[c].astype("string"), cleaned[c2].astype("string")
        diff = ~((a == b).fillna(False) | (a.isna() & b.isna()))
        changed_idx.extend(np.flatnonzero(diff.to_numpy()).tolist())
    idx = sorted(set(changed_idx))[:n]
    return {"aligned": True, "changed_rows": len(set(changed_idx)), "row_index": idx,
            "original": preview_rows(df.iloc[idx], n), "cleaned": preview_rows(cleaned.iloc[idx], n)}


def suggest(profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Suggested steps derived from profile issues. Nothing is applied until the user confirms."""
    out: list[dict[str, Any]] = []
    for i in profile.get("issues", []):
        c = i.get("column")
        k = i["kind"]
        if k == "duplicates":
            out.append({"op": "drop_duplicates", "reason": i["message"]})
        elif k == "inconsistent_categories":
            out.append({"op": "normalize_categories", "column": c, "reason": i["message"]})
        elif k == "empty_column" or k == "constant_column":
            out.append({"op": "drop_column", "column": c, "reason": i["message"]})
        elif k == "numeric_as_text":
            out.append({"op": "convert_type", "column": c, "to": "numeric", "reason": i["message"]})
        elif k == "dates_as_text":
            out.append({"op": "parse_dates", "column": c, "reason": i["message"]})
        elif k == "whitespace":
            out.append({"op": "normalize_text", "column": c, "case": "none", "reason": i["message"]})
    return out
