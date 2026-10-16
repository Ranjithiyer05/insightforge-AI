"""Helper module made available to analysis scripts inside the sandbox as `ifrt`.

It is copied verbatim into each run directory, so downloaded analysis code can
be re-run outside InsightForge with `python analysis.py` next to `data.csv`.
"""
import json
import math
import warnings

import numpy as np
import pandas as pd

_RESULT = {"tables": {}, "charts": [], "metrics": {}, "claims": [], "notes": [], "warnings": [], "artifacts": {}}


def load_df(path="data.csv", parse_dates=None):
    df = pd.read_csv(path)
    for col in parse_dates or []:
        if col in df.columns:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                df[col] = pd.to_datetime(df[col], errors="coerce", format="mixed")
    return df


def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (pd.Timestamp,)):
        return o.isoformat()
    if isinstance(o, pd.Period):
        return str(o)
    if o is pd.NaT:
        return None
    return o


def table(name, df, max_rows=500):
    df = df.reset_index() if not isinstance(df.index, pd.RangeIndex) else df
    df = df.head(max_rows)
    _RESULT["tables"][name] = {
        "columns": [str(c) for c in df.columns],
        "rows": _clean(df.astype(object).where(df.notna(), None).values.tolist()),
    }


def chart(chart_id, kind, title, data, x, series, **extra):
    """Register a chart spec. `data` must be computed rows; nothing is invented."""
    _RESULT["charts"].append(_clean({"id": chart_id, "kind": kind, "title": title, "data": data, "x": x, "series": series, **extra}))


def metric(key, value, **meta):
    _RESULT["metrics"][key] = _clean({"value": value, **meta})


def claim(claim_id, statement, value, check):
    """A numeric claim the independent verifier will recompute. `check` describes how."""
    _RESULT["claims"].append(_clean({"id": claim_id, "statement": statement, "value": value, "check": check}))


def note(text):
    _RESULT["notes"].append(text)


def warn(text):
    _RESULT["warnings"].append(text)


def artifact(name, value):
    _RESULT["artifacts"][name] = _clean(value)


def emit(path="result.json"):
    with open(path, "w") as fh:
        json.dump(_clean(_RESULT), fh)
