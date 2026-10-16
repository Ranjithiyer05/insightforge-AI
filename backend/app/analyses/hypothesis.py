"""Statistical hypothesis testing with explicit assumption diagnostics.

The sandbox script runs the *requested strategy* (e.g. Welch's t-test) and
records assumption diagnostics alongside it. Whether those assumptions are
acceptable is decided by the independent verifier, not by this script, so the
agent can be evaluated with and without verification.
"""
from __future__ import annotations

from typing import Any

from .base import Assessment, Finding, Method, Recommendation, Stage, fmt_num, fmt_p, header, metric_value

CODE = r'''
ALPHA = P.get("alpha", 0.05)
df = ifrt.load_df()
s = P["strategy"]
y, g = P["outcome"], P.get("group")
ifrt.metric("alpha", ALPHA)
ifrt.metric("test", s)

def interp_d(d):
    a = abs(d)
    return "negligible" if a < 0.2 else "small" if a < 0.5 else "medium" if a < 0.8 else "large"

if s in ("pearson", "spearman"):
    x = P["group"]
    sub = df[[x, y]].apply(pd.to_numeric, errors="coerce").dropna()
    n = len(sub)
    ifrt.metric("n", n)
    ifrt.metric("shapiro_p_x", float(stats.shapiro(sub[x].sample(min(n, 5000), random_state=SEED)).pvalue) if n >= 3 else None)
    ifrt.metric("shapiro_p_y", float(stats.shapiro(sub[y].sample(min(n, 5000), random_state=SEED)).pvalue) if n >= 3 else None)
    ifrt.metric("skew_x", float(sub[x].skew()))
    ifrt.metric("skew_y", float(sub[y].skew()))
    if s == "pearson":
        r, p = stats.pearsonr(sub[x], sub[y])
        zr, se = np.arctanh(r), 1 / np.sqrt(max(n - 3, 1))
        ci = [float(np.tanh(zr - 1.96 * se)), float(np.tanh(zr + 1.96 * se))]
    else:
        r, p = stats.spearmanr(sub[x], sub[y])
        rng = np.random.default_rng(SEED)
        bs = []
        arr = sub.to_numpy()
        for _ in range(1000):
            idx = rng.integers(0, n, n)
            bs.append(stats.spearmanr(arr[idx, 0], arr[idx, 1])[0])
        ci = [float(np.nanpercentile(bs, 2.5)), float(np.nanpercentile(bs, 97.5))]
    ifrt.metric("statistic", float(r), name="r" if s == "pearson" else "rho")
    ifrt.metric("p_value", float(p))
    ifrt.metric("effect_size", float(r), name="correlation", ci95=ci)
    ifrt.metric("significant", bool(p < ALPHA))
    ifrt.claim("p_value", f"{s} correlation p-value", float(p), {"kind": "test", "test": s, "x": x, "y": y})
    ifrt.claim("statistic", f"{s} correlation coefficient", float(r), {"kind": "test_stat", "test": s, "x": x, "y": y})
    samp = sub.sample(min(n, 400), random_state=SEED)
    ifrt.chart("scatter", "scatter", f"{y} vs {x} (random sample of {len(samp)} rows)", samp.rename(columns={x: "x", y: "y"}).round(4).to_dict("records"),
               "x", [{"key": "y", "label": y}], x_label=x, y_label=y)
elif s in ("chi_square", "fisher_exact"):
    sub = df[[g, y]].dropna().astype(str)
    if P.get("groups"):
        sub = sub[sub[g].isin(P["groups"])]
    ct = pd.crosstab(sub[g], sub[y])
    ifrt.table("contingency", ct.reset_index())
    chi2, p_chi, dof, exp = stats.chi2_contingency(ct)
    ifrt.metric("n", int(ct.values.sum()))
    ifrt.metric("min_expected_count", float(exp.min()))
    ifrt.metric("share_expected_below_5", float((exp < 5).mean()))
    k = min(ct.shape) - 1
    v = float(np.sqrt(chi2 / (ct.values.sum() * k))) if k > 0 else None
    if s == "chi_square":
        ifrt.metric("statistic", float(chi2), name="chi2", dof=int(dof))
        ifrt.metric("p_value", float(p_chi))
        p = p_chi
    else:
        if ct.shape != (2, 2):
            raise ValueError("Fisher's exact test needs a 2x2 table; use chi-square for larger tables.")
        orr, p = stats.fisher_exact(ct.values)
        ifrt.metric("statistic", float(orr), name="odds_ratio")
        ifrt.metric("p_value", float(p))
    ifrt.metric("effect_size", v, name="cramers_v")
    ifrt.metric("significant", bool(p < ALPHA))
    ifrt.claim("p_value", f"{s} p-value", float(p), {"kind": "test", "test": s, "outcome": y, "group": g, "groups": P.get("groups")})
    prop = (ct.T / ct.sum(axis=1)).T * 100
    ifrt.chart("proportions", "stacked_bar", f"{y} distribution within each {g} (%)", prop.round(2).reset_index().to_dict("records"), g,
               [{"key": str(c), "label": str(c)} for c in prop.columns], unit="%")
else:
    sub = df[[g, y]].copy()
    sub[y] = pd.to_numeric(sub[y], errors="coerce")
    sub = sub.dropna()
    sub[g] = sub[g].astype(str)
    if P.get("groups"):
        sub = sub[sub[g].isin([str(v) for v in P["groups"]])]
    levels = sorted(sub[g].unique(), key=lambda v: -len(sub[sub[g] == v]))
    arrays = [sub.loc[sub[g] == lv, y].to_numpy() for lv in levels]
    desc = []
    for lv, a in zip(levels, arrays):
        se = a.std(ddof=1) / np.sqrt(len(a)) if len(a) > 1 else np.nan
        tcrit = stats.t.ppf(0.975, len(a) - 1) if len(a) > 1 else np.nan
        desc.append({"group": lv, "n": len(a), "mean": a.mean(), "median": float(np.median(a)), "std": a.std(ddof=1) if len(a) > 1 else None,
                     "ci_low": a.mean() - tcrit * se, "ci_high": a.mean() + tcrit * se,
                     "skew": float(stats.skew(a)) if len(a) > 2 else None,
                     "shapiro_p": float(stats.shapiro(a[:5000]).pvalue) if len(a) >= 3 else None})
    d = pd.DataFrame(desc)
    ifrt.table("group_summary", d.round(4))
    ifrt.metric("n", int(len(sub)))
    ifrt.metric("groups", levels)
    ifrt.metric("min_group_n", int(d["n"].min()))
    ifrt.metric("max_abs_skew", float(d["skew"].abs().max()) if d["skew"].notna().any() else None)
    ifrt.metric("min_shapiro_p", float(d["shapiro_p"].min()) if d["shapiro_p"].notna().any() else None)
    ifrt.metric("levene_p", float(stats.levene(*arrays).pvalue) if len(arrays) >= 2 else None)
    ifrt.chart("group_means", "bar", f"Mean {y} by {g} with 95% CI", d[["group", "mean", "ci_low", "ci_high", "n"]].round(4).to_dict("records"), "group",
               [{"key": "mean", "label": f"Mean {y}"}], error=["ci_low", "ci_high"])
    if len(arrays) < 2:
        raise ValueError("Need at least two groups with data to compare.")
    if len(arrays) == 2:
        a, b = arrays
        diff = float(a.mean() - b.mean())
        ifrt.metric("comparison", f"{levels[0]} minus {levels[1]}")
        if s == "welch_t":
            res = stats.ttest_ind(a, b, equal_var=False)
            ci = res.confidence_interval(0.95)
            pooled = np.sqrt(((len(a) - 1) * a.var(ddof=1) + (len(b) - 1) * b.var(ddof=1)) / (len(a) + len(b) - 2))
            dd = diff / pooled if pooled > 0 else 0.0
            ifrt.metric("statistic", float(res.statistic), name="t")
            ifrt.metric("p_value", float(res.pvalue))
            ifrt.metric("mean_difference", diff, ci95=[float(ci.low), float(ci.high)])
            ifrt.metric("effect_size", float(dd), name="cohens_d", magnitude=interp_d(dd))
            p = res.pvalue
        elif s == "mann_whitney":
            res = stats.mannwhitneyu(a, b, alternative="two-sided")
            rbc = 1 - 2 * res.statistic / (len(a) * len(b))
            rng = np.random.default_rng(SEED)
            bs = [np.median(rng.choice(a, len(a))) - np.median(rng.choice(b, len(b))) for _ in range(2000)]
            md = float(np.median(a) - np.median(b))
            ifrt.metric("statistic", float(res.statistic), name="U")
            ifrt.metric("p_value", float(res.pvalue))
            ifrt.metric("median_difference", md, ci95=[float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))], method="bootstrap")
            ifrt.metric("mean_difference", diff)
            ifrt.metric("effect_size", float(-rbc), name="rank_biserial", magnitude=interp_d(2 * rbc))
            p = res.pvalue
        elif s == "permutation":
            res = stats.permutation_test((a, b), lambda x, z: np.mean(x) - np.mean(z), n_resamples=5000, random_state=SEED, vectorized=False)
            ifrt.metric("statistic", float(res.statistic), name="mean_difference")
            ifrt.metric("p_value", float(res.pvalue))
            ifrt.metric("mean_difference", diff)
            ifrt.metric("effect_size", diff / np.sqrt((a.var(ddof=1) + b.var(ddof=1)) / 2), name="standardized_difference")
            p = res.pvalue
        else:
            raise ValueError(f"Strategy {s} is for more than two groups.")
    else:
        if s in ("welch_t", "anova"):
            res = stats.f_oneway(*arrays)
            grand = sub[y].mean()
            ssb = sum(len(a) * (a.mean() - grand) ** 2 for a in arrays)
            sst = ((sub[y] - grand) ** 2).sum()
            ifrt.metric("statistic", float(res.statistic), name="F")
            ifrt.metric("effect_size", float(ssb / sst) if sst else None, name="eta_squared")
            ifrt.metric("test", "anova")
        else:
            res = stats.kruskal(*arrays)
            n = len(sub)
            ifrt.metric("statistic", float(res.statistic), name="H")
            ifrt.metric("effect_size", float(res.statistic / ((n ** 2 - 1) / (n + 1))), name="epsilon_squared")
            ifrt.metric("test", "kruskal")
        ifrt.metric("p_value", float(res.pvalue))
        p = res.pvalue
    ifrt.metric("significant", bool(p < ALPHA))
    ifrt.claim("p_value", "Test p-value", float(p), {"kind": "test", "test": s if len(arrays) == 2 else ("anova" if s in ("welch_t", "anova") else "kruskal"),
               "outcome": y, "group": g, "groups": levels})
    for i, row in d.head(6).iterrows():
        ifrt.claim(f"mean_{i}", f"Mean {y} for {row['group']}", float(row["mean"]),
                   {"kind": "group_agg", "op": "mean", "column": y, "group": g, "key": row["group"]})
ifrt.emit()
'''


class HypothesisTestMethod(Method):
    key = "hypothesis_test"
    task_type = "hypothesis_test"
    title = "Hypothesis test"
    strategies = ["welch_t", "mann_whitney", "permutation", "kruskal", "chi_square", "fisher_exact", "pearson", "spearman"]
    retry_map = {
        "non_normal": ["mann_whitney", "kruskal", "permutation", "spearman"],
        "small_expected_counts": ["fisher_exact"],
        "test_error": ["mann_whitney", "chi_square", "spearman"],
    }

    def requirements(self, profile, params):
        miss = []
        if not params.get("outcome"):
            miss.append("an outcome column to test")
        if not params.get("group"):
            miss.append("a grouping (or second variable) column")
        return miss

    @staticmethod
    def default_order(params: dict[str, Any]) -> list[str]:
        kind = params.get("design")
        if kind == "numeric_numeric":
            return ["pearson", "spearman"]
        if kind == "categorical_categorical":
            return ["chi_square", "fisher_exact"]
        return ["welch_t", "mann_whitney", "permutation"]

    def stages(self, params, strategy):
        return [Stage("test", f"Run {strategy.replace('_', ' ')} test with assumption diagnostics",
                      header(params, strategy, "import numpy as np\nimport pandas as pd\nfrom scipy import stats") + CODE,
                      "Computes group summaries, assumption diagnostics (normality, variance equality, expected counts) and the test statistic.")]

    def assess(self, result, params, strategy):
        p = metric_value(result, "p_value")
        if p is None:
            return Assessment("failed", "The test did not produce a p-value.", "test_error")
        return Assessment("succeeded", headline_metric=("p_value", p))

    def conditions(self, df, profile, params):
        import pandas as pd
        y, g = params.get("outcome"), params.get("group")
        cond = {"design": params.get("design", "numeric_categorical")}
        if cond["design"] == "numeric_categorical" and y in df and g in df:
            sub = df[[g, y]].dropna()
            vals = pd.to_numeric(sub[y], errors="coerce").dropna()
            cond["outcome_skew"] = "high" if abs(float(vals.skew())) > 1 else "low"
            n_min = sub.groupby(g).size().min() if len(sub) else 0
            cond["group_size"] = "small" if n_min < 50 else "large"
        return cond

    def findings(self, result, params):
        mv = lambda k, d=None: metric_value(result, k, d)  # noqa: E731
        m = result.get("metrics", {})
        F, R, L = [], [], []
        p, sig, test = mv("p_value"), mv("significant"), mv("test")
        es = m.get("effect_size", {})
        y, g = params.get("outcome"), params.get("group")
        if params.get("design") == "numeric_numeric":
            F.append(Finding(f"{'Significant' if sig else 'No significant'} association between {g} and {y}",
                             f"{test} correlation {es.get('value', 0):.3f} (95% CI {es.get('ci95', [0, 0])[0]:.3f} to {es.get('ci95', [0, 0])[1]:.3f}), {fmt_p(p)}, n = {mv('n')}.",
                             ["p_value", "statistic"], "observation", "high"))
        elif params.get("design") == "categorical_categorical":
            F.append(Finding(f"{y} {'differs' if sig else 'does not differ significantly'} across {g}",
                             f"{test.replace('_', ' ')} {fmt_p(p)}; Cramér's V = {es.get('value') or 0:.3f}.", ["p_value"], "observation", "high"))
        else:
            md = m.get("mean_difference", {})
            extra = ""
            if md.get("ci95"):
                extra = f" Mean difference {fmt_num(md['value'])} (95% CI {fmt_num(md['ci95'][0])} to {fmt_num(md['ci95'][1])})."
            med = m.get("median_difference")
            if med:
                extra += f" Median difference {fmt_num(med['value'])} (95% CI {fmt_num(med['ci95'][0])} to {fmt_num(med['ci95'][1])})."
            F.append(Finding(f"{y} {'differs significantly' if sig else 'does not differ significantly'} between {g} groups",
                             f"{str(test).replace('_', ' ')}: {fmt_p(p)} at alpha {mv('alpha')}. Effect size {es.get('name', '')} = {es.get('value') or 0:.3f}"
                             f"{' (' + es['magnitude'] + ')' if es.get('magnitude') else ''}.{extra}",
                             ["p_value"] + [c["id"] for c in result.get("claims", []) if c["id"].startswith("mean_")][:2], "observation", "high"))
        if sig and es.get("magnitude") in ("negligible", "small"):
            F.append(Finding("Statistically significant but practically small", "The effect is small relative to variation, so it may not matter in practice.", ["p_value"], "caution", "medium"))
        if not sig:
            L.append("A non-significant result does not prove the groups are the same; the sample may be too small to detect a modest difference.")
        L.append("This is an observational comparison: a difference between groups does not show that group membership causes it.")
        R.append(Recommendation("Use a controlled experiment (A/B test) if you need to establish cause and effect.",
                                "Observational group differences can reflect confounding variables.", ["p_value"]))
        return F, R, L
