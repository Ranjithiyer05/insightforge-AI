"""Automated exploratory data analysis and evidence-backed insight discovery.

Everything here is computed from the stored dataset with pandas/SciPy. Each
insight carries the method, sample size, statistic and p-value (adjusted for
multiple comparisons with Benjamini-Hochberg where several tests are run) and
a plain-language caveat. Associations are never described as causes.
"""
from __future__ import annotations

import math
import warnings
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from .profiler import _finite

MAX_ROWS_FOR_TESTS = 200_000
NUMERIC = ("numeric", "integer")
CATEG = ("categorical", "boolean", "categorical_numeric")


def _f(x: Any, nd: int = 6) -> Any:
    v = _finite(x)
    return round(v, nd) if isinstance(v, float) else v


def _types(profile: dict[str, Any]) -> dict[str, str]:
    return {c["name"]: c["semantic_type"] for c in profile.get("columns", [])}


def _roles(profile: dict[str, Any]) -> dict[str, list[str]]:
    return profile.get("roles", {}) or {}


def pick_measure(profile: dict[str, Any]) -> str | None:
    r = _roles(profile)
    ids = set(profile.get("identifier_columns", []) or r.get("id", []))
    for role in ("revenue", "profit", "quantity", "cost"):
        for c in r.get(role, []):
            if c in profile.get("numeric_columns", []) and c not in ids:
                return c
    nums = [c for c in profile.get("numeric_columns", []) if c not in ids]
    return nums[0] if nums else None


def pick_date(profile: dict[str, Any]) -> str | None:
    d = profile.get("datetime_columns") or []
    return d[0] if d else None


def bh_adjust(p: list[float]) -> list[float]:
    """Benjamini-Hochberg false-discovery-rate adjusted p-values (q-values)."""
    n = len(p)
    if not n:
        return []
    order = np.argsort(p)
    ranked = np.array(p)[order] * n / (np.arange(n) + 1)
    q = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(n)
    out[order] = np.minimum(q, 1.0)
    return out.tolist()


def summary_stats(df: pd.DataFrame, cols: list[str]) -> list[dict[str, Any]]:
    rows = []
    for c in cols:
        x = pd.to_numeric(df[c], errors="coerce")
        nn = x.dropna()
        if nn.empty:
            continue
        mode = nn.mode()
        q1, q3 = nn.quantile(0.25), nn.quantile(0.75)
        iqr = q3 - q1
        rows.append({"column": c, "count": int(nn.size), "missing": int(x.isna().sum()), "mean": _f(nn.mean()), "median": _f(nn.median()),
                     "mode": _f(mode.iloc[0]) if len(mode) else None, "variance": _f(nn.var()), "std": _f(nn.std()), "min": _f(nn.min()),
                     "q1": _f(q1), "q3": _f(q3), "max": _f(nn.max()), "skew": _f(nn.skew()) if nn.size > 2 else None,
                     "kurtosis": _f(nn.kurt()) if nn.size > 3 else None,
                     "outliers_iqr": int(((nn < q1 - 1.5 * iqr) | (nn > q3 + 1.5 * iqr)).sum()) if iqr > 0 else 0, "sum": _f(nn.sum())})
    return rows


def histogram(x: pd.Series, bins: int | None = None) -> list[dict[str, Any]]:
    x = pd.to_numeric(x, errors="coerce").dropna()
    if x.empty:
        return []
    b = bins or min(30, max(6, int(math.sqrt(len(x)))))
    counts, edges = np.histogram(x, bins=b)
    return [{"bin": f"{edges[i]:.4g}–{edges[i + 1]:.4g}", "start": float(edges[i]), "end": float(edges[i + 1]), "count": int(counts[i])} for i in range(len(counts))]


def categorical_summary(df: pd.DataFrame, col: str, measure: str | None, top: int = 15) -> dict[str, Any]:
    s = df[col].astype("string").fillna("(missing)")
    vc = s.value_counts()
    out: dict[str, Any] = {"column": col, "unique": int(df[col].nunique(dropna=True)), "missing": int(df[col].isna().sum()),
                           "top": [{"value": str(k)[:80], "count": int(v), "share": _f(v / len(s), 4)} for k, v in vc.head(top).items()],
                           "other_count": int(vc.iloc[top:].sum())}
    if measure and measure != col:
        m = pd.to_numeric(df[measure], errors="coerce")
        g = pd.DataFrame({"k": s, "m": m}).dropna().groupby("k")["m"].agg(["sum", "mean", "median", "count"]).sort_values("sum", ascending=False)
        g["share_of_total"] = g["sum"] / g["sum"].sum() if g["sum"].sum() else np.nan
        g["rank"] = np.arange(1, len(g) + 1)
        out["by_measure"] = {"measure": measure, "rows": [{"value": str(k)[:80], **{c: _f(v) for c, v in r.items()}} for k, r in g.head(top).iterrows()]}
    return out


def correlations(df: pd.DataFrame, cols: list[str]) -> dict[str, Any] | None:
    use = cols[:15]
    if len(use) < 2:
        return None
    X = df[use].apply(pd.to_numeric, errors="coerce")
    method = "spearman"
    m = X.corr(method=method, min_periods=10)
    pairs = []
    for i, a in enumerate(use):
        for b in use[i + 1:]:
            sub = X[[a, b]].dropna()
            if len(sub) < 10 or sub[a].nunique() < 3 or sub[b].nunique() < 3:
                continue
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                rho, p = stats.spearmanr(sub[a], sub[b])
            if np.isfinite(rho):
                pairs.append({"a": a, "b": b, "rho": float(rho), "p": float(p), "n": int(len(sub))})
    q = bh_adjust([x["p"] for x in pairs])
    for x, qq in zip(pairs, q):
        x["q"] = qq
    pairs.sort(key=lambda r: -abs(r["rho"]))
    return {"method": "Spearman rank correlation (robust to outliers and non-linear monotonic relationships)", "columns": use,
            "matrix": [[None if pd.isna(v) else round(float(v), 3) for v in row] for row in m.to_numpy()],
            "pairs": [{k: (round(v, 6) if isinstance(v, float) else v) for k, v in r.items()} for r in pairs[:25]],
            "note": "p-values are adjusted for the number of pairs tested (Benjamini-Hochberg q). Correlation does not imply causation."
            + (" Showing the first 15 numeric columns." if len(cols) > 15 else "")}


def time_trend(df: pd.DataFrame, date_col: str, measure: str | None) -> dict[str, Any] | None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        d = pd.to_datetime(df[date_col], errors="coerce", format="mixed")
    if d.notna().sum() < 10:
        return None
    span_days = (d.max() - d.min()).days
    freq, label = ("D", "day") if span_days <= 92 else ("W", "week") if span_days <= 400 else ("M", "month")
    per = d.dt.to_period(freq)
    if measure:
        v = pd.to_numeric(df[measure], errors="coerce")
        g = pd.DataFrame({"p": per, "v": v}).dropna().groupby("p")["v"].agg(["sum", "count"])
    else:
        g = pd.DataFrame({"p": per}).dropna().groupby("p").size().to_frame("count")
        g["sum"] = g["count"]
    g = g.sort_index()
    if len(g) < 3:
        return None
    # A final period with clearly fewer observations is probably incomplete.
    partial = bool(len(g) >= 3 and g["count"].iloc[-1] < 0.6 * g["count"].iloc[-4:-1].median())
    series = [{"period": str(k), "value": _f(r["sum"]), "rows": int(r["count"])} for k, r in g.iterrows()]
    vals = g["sum"].iloc[:-1] if partial else g["sum"]
    idx = np.arange(len(vals))
    out: dict[str, Any] = {"date_column": date_col, "measure": measure or "row count", "aggregation": "sum" if measure else "count", "granularity": label,
                           "series": series, "last_period_partial": partial, "start": str(d.min().date()), "end": str(d.max().date())}
    if len(vals) >= 4:
        rho, p = stats.spearmanr(idx, vals.to_numpy())
        slope = np.polyfit(idx, vals.to_numpy(dtype=float), 1)[0]
        out["trend"] = {"method": "Spearman correlation between period order and value (monotonic trend test)", "rho": _f(rho), "p_value": _f(p),
                        "slope_per_period": _f(slope), "n_periods": int(len(vals))}
    if len(vals) >= 2:
        last, prev = float(vals.iloc[-1]), float(vals.iloc[-2])
        out["last_change"] = {"last_period": str(vals.index[-1]), "previous_period": str(vals.index[-2]), "last": _f(last), "previous": _f(prev),
                              "change": _f(last - prev), "pct_change": _f((last - prev) / abs(prev)) if prev else None}
    out["peak"] = {"period": str(vals.idxmax()), "value": _f(vals.max())}
    out["trough"] = {"period": str(vals.idxmin()), "value": _f(vals.min())}
    return out


def group_tests(df: pd.DataFrame, measure: str, cats: list[str]) -> list[dict[str, Any]]:
    out = []
    y = pd.to_numeric(df[measure], errors="coerce")
    for c in cats:
        sub = pd.DataFrame({"g": df[c].astype("string"), "y": y}).dropna()
        groups = [grp["y"].to_numpy() for _, grp in sub.groupby("g") if len(grp) >= 5]
        if len(groups) < 2 or len(sub) < 20:
            continue
        h, p = stats.kruskal(*groups)
        k, n = len(groups), sum(len(g) for g in groups)
        eps2 = max(0.0, (h - k + 1) / (n - k)) if n > k else None  # epsilon-squared effect size for Kruskal-Wallis
        means = sub.groupby("g")["y"].agg(["mean", "median", "count"]).query("count >= 5").sort_values("mean", ascending=False)
        out.append({"group": c, "measure": measure, "test": "Kruskal-Wallis H", "statistic": _f(h), "p": float(p), "n": int(n), "groups": int(k),
                    "effect_size_epsilon2": _f(eps2), "highest": {"group": str(means.index[0]), "mean": _f(means["mean"].iloc[0]), "n": int(means["count"].iloc[0])},
                    "lowest": {"group": str(means.index[-1]), "mean": _f(means["mean"].iloc[-1]), "n": int(means["count"].iloc[-1])}})
    q = bh_adjust([g["p"] for g in out])
    for g, qq in zip(out, q):
        g["q"] = qq
    return out


def _fmt_q(q: float) -> str:
    return "< 0.001" if q < 0.001 else f"= {q:.3g}"


def _effect_words(eps2: float | None) -> str:
    if eps2 is None:
        return "unknown"
    return "large" if eps2 >= 0.26 else "moderate" if eps2 >= 0.08 else "small" if eps2 >= 0.01 else "negligible"


def discover_insights(df: pd.DataFrame, profile: dict[str, Any], parts: dict[str, Any]) -> list[dict[str, Any]]:
    ins: list[dict[str, Any]] = []
    n = len(df)

    def add(kind, title, detail, evidence, caveat, score):
        ins.append({"id": f"ins_{len(ins) + 1}", "kind": kind, "title": title, "detail": detail, "evidence": evidence, "caveat": caveat, "score": round(score, 3)})

    t = parts.get("trend")
    if t and t.get("trend"):
        tr = t["trend"]
        if tr["p_value"] is not None and tr["p_value"] < 0.05 and abs(tr["rho"]) >= 0.4:
            direction = "upward" if tr["rho"] > 0 else "downward"
            add("trend", f"{t['measure']} shows a {direction} trend over time",
                f"Across {tr['n_periods']} {t['granularity']}s ({t['start']} to {t['end']}), {t['aggregation']} of {t['measure']} moves {direction} "
                f"by about {abs(tr['slope_per_period']):,.4g} per {t['granularity']} (Spearman ρ = {tr['rho']:.2f}, p = {tr['p_value']:.3g}).",
                {"method": tr["method"], "n": tr["n_periods"], "statistic": tr["rho"], "p_value": tr["p_value"]},
                "A trend in past data does not guarantee it will continue." + (" The last period looks incomplete and was excluded." if t["last_period_partial"] else ""),
                0.6 + abs(tr["rho"]) * 0.4)
        lc = t.get("last_change")
        if lc and lc.get("pct_change") is not None and abs(lc["pct_change"]) >= 0.1:
            add("change", f"{t['measure']} {'rose' if lc['change'] > 0 else 'fell'} {abs(lc['pct_change']):.0%} in {lc['last_period']}",
                f"{lc['last_period']}: {lc['last']:,.4g} versus {lc['previous']:,.4g} in {lc['previous_period']} ({lc['change']:+,.4g}).",
                {"method": f"{t['aggregation']} per {t['granularity']}", "values": {"last": lc["last"], "previous": lc["previous"]}},
                "A single period-to-period change can be ordinary variation; compare it with the usual range in the trend chart.", 0.5 + min(abs(lc["pct_change"]), 1) * 0.3)

    for g in parts.get("group_tests", []):
        if g["q"] < 0.05 and (g["effect_size_epsilon2"] or 0) >= 0.01:
            add("group_difference", f"{g['measure']} differs by {g['group']}",
                f"Highest mean: {g['highest']['group']} ({g['highest']['mean']:,.4g}, n={g['highest']['n']:,}); lowest: {g['lowest']['group']} "
                f"({g['lowest']['mean']:,.4g}, n={g['lowest']['n']:,}). Kruskal-Wallis across {g['groups']} groups: H = {g['statistic']:,.4g}, adjusted q {_fmt_q(g['q'])}, "
                f"{_effect_words(g['effect_size_epsilon2'])} effect (ε² = {g['effect_size_epsilon2']:.3f}).",
                {"method": g["test"], "n": g["n"], "statistic": g["statistic"], "p_value": g["p"], "q_value": g["q"], "effect_size": g["effect_size_epsilon2"]},
                "A difference between groups is an association; other factors that vary by group may explain it.",
                0.4 + min(g["effect_size_epsilon2"] or 0, 0.5))

    corr = parts.get("correlations")
    for pr in (corr or {}).get("pairs", [])[:6]:
        if pr["q"] < 0.01 and abs(pr["rho"]) >= 0.3:
            strength = "strong" if abs(pr["rho"]) >= 0.7 else "moderate" if abs(pr["rho"]) >= 0.5 else "weak-to-moderate"
            add("correlation", f"{pr['a']} and {pr['b']} move {'together' if pr['rho'] > 0 else 'in opposite directions'}",
                f"{strength.capitalize()} {'positive' if pr['rho'] > 0 else 'negative'} rank correlation (ρ = {pr['rho']:.2f}, n = {pr['n']:,}, adjusted q {_fmt_q(pr['q'])}).",
                {"method": "Spearman rank correlation", "n": pr["n"], "statistic": pr["rho"], "p_value": pr["p"], "q_value": pr["q"]},
                "Correlation is not causation, and one column may be computed from the other.", 0.3 + abs(pr["rho"]) * 0.5)

    for cs in parts.get("categorical", []):
        bm = cs.get("by_measure")
        if bm and len(bm["rows"]) >= 5:
            shares = [r.get("share_of_total") or 0 for r in bm["rows"]]
            k = max(1, round(cs["unique"] * 0.2))
            top_share = sum(sorted(shares, reverse=True)[:k])
            if top_share >= 0.5:
                add("concentration", f"{bm['measure']} is concentrated in a few {cs['column']} values",
                    f"The top {k} of {cs['unique']} {cs['column']} values account for {top_share:.0%} of total {bm['measure']}. Largest: {bm['rows'][0]['value']} "
                    f"({(bm['rows'][0].get('share_of_total') or 0):.0%}).",
                    {"method": "share of column total", "values": {r["value"]: r.get("share_of_total") for r in bm["rows"][:k]}},
                    "Concentration describes the current data only.", 0.35 + top_share * 0.3)

    for row in parts.get("summary", []):
        sk = row.get("skew")
        if sk is not None and abs(sk) >= 2 and row["count"] >= 30 and row["mean"] and row["median"] is not None:
            add("distribution", f"{row['column']} is highly skewed",
                f"Skewness {sk:.2f}: the mean ({row['mean']:,.4g}) and median ({row['median']:,.4g}) differ, so a few large values pull the average. "
                f"{row['outliers_iqr']:,} values lie outside 1.5×IQR.",
                {"method": "sample skewness", "n": row["count"], "statistic": sk},
                "Report the median alongside the mean for skewed columns; extreme values are not necessarily errors.", 0.25 + min(abs(sk), 6) / 20)

    for c in profile.get("columns", []):
        if c["missing_pct"] >= 0.05:
            add("missing", f"{c['name']} is {c['missing_pct']:.0%} missing",
                f"{c['missing']:,} of {n:,} rows have no value in {c['name']}.", {"method": "count of missing cells", "n": n, "values": {"missing": c["missing"]}},
                "Analyses that use this column either drop these rows or fill them; check whether values are missing for a reason.", 0.2 + c["missing_pct"] * 0.4)

    for c in profile.get("columns", []):
        if c["semantic_type"] == "boolean" and c.get("top_values"):
            tv = c["top_values"]
            tot = sum(v["count"] for v in tv)
            mn = min(v["count"] for v in tv) / tot if tot else 0
            if mn < 0.2:
                add("imbalance", f"{c['name']} is imbalanced", f"The less common value makes up {mn:.0%} of rows.",
                    {"method": "class shares", "values": {v['value']: v['count'] for v in tv}},
                    "If this is a prediction target, accuracy alone will be misleading; use balanced metrics.", 0.3)

    ins.sort(key=lambda x: -x["score"])
    # keep the list varied: at most three insights of the same kind
    per_kind: dict[str, int] = {}
    varied = []
    for i in ins:
        per_kind[i["kind"]] = per_kind.get(i["kind"], 0) + 1
        if per_kind[i["kind"]] <= 3:
            varied.append(i)
    return varied[:20]


def run_eda(df: pd.DataFrame, profile: dict[str, Any]) -> dict[str, Any]:
    if len(df) > MAX_ROWS_FOR_TESTS:
        df = df.sample(MAX_ROWS_FOR_TESTS, random_state=42)
        sampled = True
    else:
        sampled = False
    types = _types(profile)
    ids = set(profile.get("identifier_columns", []))
    nums = [c for c in profile.get("numeric_columns", []) if c not in ids]
    numeric_roles = {"revenue", "cost", "profit", "quantity", "discount", "price"}
    roles_by_col = {c["name"]: set(c.get("roles", [])) for c in profile.get("columns", [])}
    # numeric-looking columns with few distinct values (prices, discounts) are measures, not groups
    cats = [c for c in profile.get("categorical_columns", []) if c not in ids and 2 <= df[c].nunique(dropna=True) <= 50
            and not (types.get(c) == "categorical_numeric" and roles_by_col.get(c, set()) & numeric_roles)]
    measure = pick_measure(profile)
    date = pick_date(profile)
    parts: dict[str, Any] = {
        "summary": summary_stats(df, nums),
        "histograms": {c: histogram(df[c]) for c in nums[:12]},
        "categorical": [categorical_summary(df, c, measure) for c in cats[:10]],
        "correlations": correlations(df, nums),
        "trend": time_trend(df, date, measure) if date else None,
        "group_tests": group_tests(df, measure, cats[:10]) if measure else [],
        "missing": [{"column": c["name"], "missing": c["missing"], "pct": c["missing_pct"]} for c in profile.get("columns", []) if c["missing"]],
    }
    parts["insights"] = discover_insights(df, profile, parts)
    parts["kpis"] = _kpis(df, profile, measure, date)
    parts["measure"], parts["date_column"] = measure, date
    parts["sampled"] = sampled
    parts["n_rows"] = int(len(df))
    parts["types"] = types
    parts["notes"] = ["All values are computed from the stored dataset.", "Statistical tests report adjusted p-values where several tests were run."] + \
        (["Tests ran on a random sample of 200,000 rows."] if sampled else [])
    return parts


def _kpis(df: pd.DataFrame, profile: dict[str, Any], measure: str | None, date: str | None) -> list[dict[str, Any]]:
    k: list[dict[str, Any]] = [{"key": "rows", "label": "Rows", "value": int(len(df)), "format": "int"},
                               {"key": "columns", "label": "Columns", "value": int(df.shape[1]), "format": "int"}]
    r = _roles(profile)
    for role, label in (("revenue", "Total"), ("profit", "Total"), ("quantity", "Total")):
        for c in r.get(role, [])[:1]:
            if c in profile.get("numeric_columns", []):
                k.append({"key": f"sum_{c}", "label": f"{label} {c}", "value": _f(pd.to_numeric(df[c], errors="coerce").sum()), "format": "num",
                          "formula": f"SUM({c})"})
    if measure and not any(x["key"] == f"sum_{measure}" for x in k):
        k.append({"key": f"mean_{measure}", "label": f"Average {measure}", "value": _f(pd.to_numeric(df[measure], errors="coerce").mean()), "format": "num",
                  "formula": f"AVG({measure})"})
    for c in profile.get("columns", []):
        if c["semantic_type"] == "boolean" and c.get("top_values") and any(t["value"].lower() in ("1", "true", "yes", "1.0") for t in c["top_values"]):
            pos = sum(t["count"] for t in c["top_values"] if t["value"].lower() in ("1", "true", "yes", "1.0"))
            tot = int(df[c["name"]].notna().sum())
            k.append({"key": f"rate_{c['name']}", "label": f"{c['name']} rate", "value": _f(pos / tot if tot else None, 4), "format": "pct",
                      "formula": f"share of rows where {c['name']} is yes/true/1"})
            break
    if date:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            d = pd.to_datetime(df[date], errors="coerce", format="mixed")
        if d.notna().any():
            k.append({"key": "date_range", "label": "Date range", "value": f"{d.min().date()} → {d.max().date()}", "format": "text"})
    return k
