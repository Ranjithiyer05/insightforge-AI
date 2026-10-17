"""Compare two datasets: schema differences and per-column distribution shifts.

Numeric columns: means, medians, Kolmogorov-Smirnov test. Categorical columns:
category shares, new and vanished categories, chi-square test and the
population stability index (PSI). p-values are adjusted with
Benjamini-Hochberg across all tested columns. With large samples tiny shifts
become "significant", so each column also gets an effect size and a plain
verdict based on it.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from .eda import _f, bh_adjust


def _is_num(s: pd.Series) -> bool:
    x = pd.to_numeric(s, errors="coerce")
    return x.notna().sum() > 0 and x.notna().mean() > 0.95 * s.notna().mean() and s.nunique() > 10


def _psi(pa: pd.Series, pb: pd.Series) -> float:
    keys = pa.index.union(pb.index)
    a = pa.reindex(keys, fill_value=0) + 1e-4
    b = pb.reindex(keys, fill_value=0) + 1e-4
    return float(((b - a) * np.log(b / a)).sum())


def _verdict(effect: float, kind: str) -> str:
    # numeric: |standardised mean difference| or KS D; categorical: PSI (0.1 / 0.25 are the usual thresholds)
    if kind == "categorical":
        return "large shift" if effect >= 0.25 else "moderate shift" if effect >= 0.1 else "stable"
    return "large shift" if effect >= 0.3 else "moderate shift" if effect >= 0.1 else "stable"


def compare(a: pd.DataFrame, b: pd.DataFrame, name_a: str = "A", name_b: str = "B") -> dict[str, Any]:
    ca, cb = [str(c) for c in a.columns], [str(c) for c in b.columns]
    shared = [c for c in ca if c in cb]
    cols: list[dict[str, Any]] = []
    pvals: list[float] = []
    for c in shared:
        sa, sb = a[c], b[c]
        row: dict[str, Any] = {"column": c, "missing_a": _f(sa.isna().mean(), 4), "missing_b": _f(sb.isna().mean(), 4)}
        if _is_num(sa) and _is_num(sb):
            xa, xb = pd.to_numeric(sa, errors="coerce").dropna(), pd.to_numeric(sb, errors="coerce").dropna()
            if len(xa) < 5 or len(xb) < 5:
                continue
            ks = stats.ks_2samp(xa, xb)
            pooled = np.sqrt((xa.var() + xb.var()) / 2) or 1.0
            smd = float((xb.mean() - xa.mean()) / pooled)
            row.update(kind="numeric", mean_a=_f(xa.mean()), mean_b=_f(xb.mean()), median_a=_f(xa.median()), median_b=_f(xb.median()),
                       std_a=_f(xa.std()), std_b=_f(xb.std()), change_pct=_f((xb.mean() - xa.mean()) / abs(xa.mean()) * 100 if xa.mean() else None, 3),
                       test="Kolmogorov-Smirnov", statistic=_f(ks.statistic), p_value=float(ks.pvalue), effect=_f(max(abs(smd), ks.statistic), 4),
                       effect_label="max(|standardised mean difference|, KS D)")
            qs = np.linspace(0, 1, 21)
            edges = np.unique(np.quantile(pd.concat([xa, xb]), qs))
            if len(edges) > 2:
                ha, _ = np.histogram(xa, edges)
                hb, _ = np.histogram(xb, edges)
                row["histogram"] = [{"bin": f"{edges[i]:.4g}", name_a: _f(ha[i] / len(xa), 4), name_b: _f(hb[i] / len(xb), 4)} for i in range(len(ha))]
        else:
            va = sa.astype(str).where(sa.notna(), "(missing)").value_counts(normalize=True)
            vb = sb.astype(str).where(sb.notna(), "(missing)").value_counts(normalize=True)
            if len(va) > 200 or len(vb) > 200:
                row.update(kind="high_cardinality", note="Too many distinct values to compare category shares.")
                cols.append(row)
                continue
            keys = va.index.union(vb.index)
            ta = sa.astype(str).where(sa.notna(), "(missing)").value_counts().reindex(keys, fill_value=0)
            tb = sb.astype(str).where(sb.notna(), "(missing)").value_counts().reindex(keys, fill_value=0)
            table = np.vstack([ta.to_numpy(), tb.to_numpy()])
            table = table[:, table.sum(axis=0) > 0]
            p = float(stats.chi2_contingency(table)[1]) if table.shape[1] > 1 else 1.0
            psi = _psi(va, vb)
            top = (vb.reindex(keys, fill_value=0) - va.reindex(keys, fill_value=0)).sort_values(key=abs, ascending=False).head(12)
            row.update(kind="categorical", test="Chi-square", p_value=p, effect=_f(psi, 4), effect_label="PSI",
                       new_categories=[str(k) for k in vb.index.difference(va.index)][:20], missing_categories=[str(k) for k in va.index.difference(vb.index)][:20],
                       shares=[{"value": str(k)[:40], name_a: _f(va.get(k, 0.0), 4), name_b: _f(vb.get(k, 0.0), 4), "change": _f(float(v), 4)} for k, v in top.items()])
        pvals.append(row["p_value"])
        cols.append(row)
    tested = [r for r in cols if "p_value" in r]
    for r, q in zip(tested, bh_adjust([r["p_value"] for r in tested])):
        r["q_value"] = _f(q, 6)
        r["p_value"] = _f(r["p_value"], 6)
        r["verdict"] = _verdict(r["effect"] or 0, r["kind"]) if q < 0.05 else "stable"
    order = {"large shift": 0, "moderate shift": 1, "stable": 2}
    cols.sort(key=lambda r: (order.get(r.get("verdict"), 3), -(r.get("effect") or 0)))
    ta = {c: str(a[c].dtype) for c in shared}
    tb = {c: str(b[c].dtype) for c in shared}
    shifts = [r for r in cols if r.get("verdict") in ("large shift", "moderate shift")]
    summary = [f"{name_b} has {len(b):,} rows vs {len(a):,} in {name_a} ({(len(b) - len(a)) / max(len(a), 1) * 100:+.1f}%)."]
    if set(ca) != set(cb):
        summary.append(f"{len([c for c in cb if c not in ca])} column(s) added and {len([c for c in ca if c not in cb])} removed.")
    summary.append(f"{len(shifts)} of {len(tested)} shared columns shifted meaningfully" + (f": {', '.join(r['column'] for r in shifts[:5])}." if shifts else "."))
    return {
        "a": {"name": name_a, "rows": int(len(a)), "columns": len(ca)}, "b": {"name": name_b, "rows": int(len(b)), "columns": len(cb)},
        "added_columns": [c for c in cb if c not in ca], "removed_columns": [c for c in ca if c not in cb],
        "type_changes": [{"column": c, "a": ta[c], "b": tb[c]} for c in shared if ta[c] != tb[c]],
        "columns": cols, "summary": summary,
        "method": "Numeric: Kolmogorov-Smirnov test with standardised mean difference. Categorical: chi-square test with PSI. "
                  "p-values adjusted by Benjamini-Hochberg; a column is called shifted only if q < 0.05 and the effect size is at least moderate.",
    }
