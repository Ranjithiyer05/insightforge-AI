"""Descriptive analysis, group comparison, segmentation and anomaly detection."""
from __future__ import annotations

from .base import Assessment, Finding, Method, Recommendation, Stage, fmt_num, header, metric_value

DESCRIBE = r'''
df = ifrt.load_df()
num = [c for c in P.get("numeric", []) if c in df.columns]
cat = [c for c in P.get("categorical", []) if c in df.columns]
ifrt.metric("rows", int(len(df)))
ifrt.claim("rows", "Number of rows", int(len(df)), {"kind": "row_count"})
if num:
    desc = df[num].apply(pd.to_numeric, errors="coerce").describe().T
    desc["missing"] = df[num].isna().sum()
    ifrt.table("numeric_summary", desc.round(4))
    for c in num[:4]:
        ifrt.claim(f"mean_{c}", f"Mean of {c}", float(pd.to_numeric(df[c], errors="coerce").mean()), {"kind": "col_agg", "op": "mean", "column": c})
    for c in num[:3]:
        x = pd.to_numeric(df[c], errors="coerce").dropna()
        counts, edges = np.histogram(x, bins=min(20, max(5, int(np.sqrt(len(x))))))
        ifrt.chart(f"hist_{c}", "bar", f"Distribution of {c}", [{"bin": f"{edges[i]:.4g}–{edges[i+1]:.4g}", "count": int(counts[i])} for i in range(len(counts))],
                   "bin", [{"key": "count", "label": "Rows"}])
    if len(num) >= 2:
        corr = df[num].apply(pd.to_numeric, errors="coerce").corr(method="spearman")
        pairs = []
        for i, a in enumerate(num):
            for b in num[i + 1:]:
                pairs.append({"a": a, "b": b, "spearman": corr.loc[a, b]})
        pairs = sorted(pairs, key=lambda r: -abs(r["spearman"] if r["spearman"] == r["spearman"] else 0))[:10]
        ifrt.table("top_correlations", pd.DataFrame(pairs).round(3))
        ifrt.artifact("top_correlations", pairs[:3])
for c in cat[:3]:
    vc = df[c].astype(str).value_counts().head(12)
    ifrt.chart(f"counts_{c}", "bar", f"Most common values of {c}", [{"value": k, "count": int(v)} for k, v in vc.items()], "value",
               [{"key": "count", "label": "Rows"}], layout="horizontal")
if P.get("date_col") and num:
    d = pd.to_datetime(df[P["date_col"]], errors="coerce", format="mixed")
    vcol = P.get("value_col") or num[0]
    ts = df.assign(_m=d.dt.to_period("M").astype(str)).groupby("_m")[vcol].sum().reset_index().rename(columns={"_m": "month", vcol: "total"})
    ifrt.chart("monthly_total", "line", f"Monthly total of {vcol}", ts.round(2).to_dict("records"), "month", [{"key": "total", "label": vcol}])
ifrt.emit()
'''

COMPARE = r'''
from scipy import stats
df = ifrt.load_df()
y, g = P["value_col"], P["group"]
sub = df[[g, y]].copy()
sub[y] = pd.to_numeric(sub[y], errors="coerce")
sub = sub.dropna()
sub[g] = sub[g].astype(str)
rows = []
for k, grp in sub.groupby(g):
    a = grp[y].to_numpy()
    se = a.std(ddof=1) / np.sqrt(len(a)) if len(a) > 1 else np.nan
    t = stats.t.ppf(0.975, len(a) - 1) if len(a) > 1 else np.nan
    rows.append({"group": k, "n": len(a), "total": a.sum(), "mean": a.mean(), "median": float(np.median(a)),
                 "ci_low": a.mean() - t * se, "ci_high": a.mean() + t * se})
d = pd.DataFrame(rows).sort_values(P.get("sort_by", "mean"), ascending=False)
ifrt.table("group_comparison", d.round(4))
ifrt.chart("group_comparison", "bar", f"Mean {y} by {g} (95% CI)", d.head(20).round(4).to_dict("records"), "group",
           [{"key": "mean", "label": f"Mean {y}"}], error=["ci_low", "ci_high"])
ifrt.chart("group_totals", "bar", f"Total {y} by {g}", d.sort_values("total", ascending=False).head(20).round(2).to_dict("records"), "group",
           [{"key": "total", "label": f"Total {y}"}])
for i, r in enumerate(d.head(5).itertuples()):
    ifrt.claim(f"group_mean_{i}", f"Mean {y} for {r.group}", float(r.mean), {"kind": "group_agg", "op": "mean", "column": y, "group": g, "key": r.group})
    ifrt.claim(f"group_total_{i}", f"Total {y} for {r.group}", float(r.total), {"kind": "group_agg", "op": "sum", "column": y, "group": g, "key": r.group})
top, bottom = d.iloc[0], d.iloc[-1]
ifrt.metric("top_group", top["group"])
ifrt.metric("top_mean", float(top["mean"]))
ifrt.metric("bottom_group", bottom["group"])
ifrt.metric("bottom_mean", float(bottom["mean"]))
ifrt.metric("groups", int(len(d)))
ifrt.metric("ci_overlap_top_bottom", bool(top["ci_low"] <= bottom["ci_high"]))
if len(d) >= 2:
    h = stats.kruskal(*[grp[y].to_numpy() for _, grp in sub.groupby(g)])
    ifrt.metric("kruskal_p", float(h.pvalue), note="screening test across all groups")
ifrt.emit()
'''

SEGMENT = r'''
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.impute import SimpleImputer
from sklearn.metrics import silhouette_score
from sklearn.mixture import GaussianMixture
from sklearn.preprocessing import StandardScaler
df = ifrt.load_df()
feats = [c for c in P["features"] if c in df.columns]
X = df[feats].apply(pd.to_numeric, errors="coerce")
X = pd.DataFrame(SimpleImputer(strategy="median").fit_transform(X), columns=feats)
s = P["strategy"]
Xt = X.copy()
if s == "kmeans_log":
    for c in feats:
        if Xt[c].min() >= 0 and abs(Xt[c].skew()) > 1:
            Xt[c] = np.log1p(Xt[c])
Z = StandardScaler().fit_transform(Xt)
rng = np.random.default_rng(SEED)
samp = rng.choice(len(Z), min(3000, len(Z)), replace=False)
scores = {}
models = {}
for k in range(2, 7):
    if s == "gaussian_mixture":
        m = GaussianMixture(k, random_state=SEED).fit(Z)
        lab = m.predict(Z)
    else:
        m = KMeans(k, n_init=10, random_state=SEED).fit(Z)
        lab = m.labels_
    if len(set(lab)) < 2:
        continue
    scores[k] = float(silhouette_score(Z[samp], lab[samp]))
    models[k] = lab
best = max(scores, key=scores.get)
lab = models[best]
ifrt.metric("k", int(best))
ifrt.metric("silhouette", scores[best], note="on a sample of up to 3000 rows; -1 to 1, higher means better separated")
ifrt.chart("silhouette", "bar", "Silhouette score by number of segments", [{"k": str(k), "silhouette": round(v, 4)} for k, v in scores.items()],
           "k", [{"key": "silhouette", "label": "Silhouette"}])
prof = X.assign(segment=lab).groupby("segment").agg(["mean"])
prof.columns = [c[0] for c in prof.columns]
sizes = pd.Series(lab).value_counts().sort_index()
prof.insert(0, "size", sizes.values)
prof.insert(1, "share_pct", (sizes / sizes.sum() * 100).round(2).values)
z = (X.assign(segment=lab).groupby("segment")[feats].mean() - X.mean()) / X.std(ddof=0).replace(0, 1)
ifrt.table("segment_profiles", prof.round(4).reset_index())
desc = []
for seg in z.index:
    top = z.loc[seg].abs().sort_values(ascending=False).head(3).index
    desc.append({"segment": int(seg), "size": int(sizes[seg]), "traits": [f"{'high' if z.loc[seg, t] > 0 else 'low'} {t} ({z.loc[seg, t]:+.1f} SD)" for t in top]})
ifrt.artifact("segments", desc)
pc = PCA(2, random_state=SEED).fit_transform(Z[samp[:600]])
ifrt.chart("segments_pca", "scatter", "Segments projected on the first two principal components (sample)",
           [{"x": round(float(pc[i, 0]), 3), "y": round(float(pc[i, 1]), 3), "segment": int(lab[samp[i]])} for i in range(len(pc))],
           "x", [{"key": "y", "label": "PC2"}], group="segment", x_label="PC1", y_label="PC2")
ifrt.claim("silhouette", "Silhouette score of chosen segmentation", scores[best], {"kind": "silhouette", "features": feats, "strategy": s, "k": int(best)})
ifrt.artifact("labels_sample", {"idx": [int(i) for i in samp], "labels": [int(lab[i]) for i in samp]})
ifrt.emit()
'''

ANOMALY = r'''
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
df = ifrt.load_df()
feats = [c for c in P["features"] if c in df.columns]
X = df[feats].apply(pd.to_numeric, errors="coerce")
Xi = pd.DataFrame(SimpleImputer(strategy="median").fit_transform(X), columns=feats)
s = P["strategy"]
if s == "isolation_forest":
    iso = IsolationForest(n_estimators=300, contamination=P.get("contamination", "auto"), random_state=SEED).fit(Xi)
    flag = iso.predict(Xi) == -1
    score = -iso.score_samples(Xi)
else:
    med = Xi.median()
    mad = (Xi - med).abs().median().replace(0, np.nan)
    rz = 0.6745 * (Xi - med) / mad
    score = rz.abs().max(axis=1).fillna(0).to_numpy()
    flag = score > 3.5
ifrt.metric("anomalies", int(flag.sum()))
ifrt.metric("anomaly_rate_pct", float(flag.mean() * 100), unit="%")
ifrt.claim("anomalies", "Rows flagged as anomalous", int(flag.sum()), {"kind": "anomaly_count", "features": feats, "strategy": s})
out = df.assign(anomaly_score=score, is_anomaly=flag).sort_values("anomaly_score", ascending=False)
ifrt.table("top_anomalies", out.head(25).round(4))
comp = pd.DataFrame({"anomalous": Xi[flag].median(), "typical": Xi[~flag].median()})
ifrt.table("anomaly_vs_typical_median", comp.round(4).reset_index().rename(columns={"index": "feature"}))
if len(feats) >= 2:
    v = Xi.var().sort_values(ascending=False).index[:2]
    samp = np.random.default_rng(SEED).choice(len(Xi), min(800, len(Xi)), replace=False)
    ifrt.chart("anomaly_scatter", "scatter", f"{v[1]} vs {v[0]} (anomalies highlighted, sample)",
               [{"x": round(float(Xi.iloc[i][v[0]]), 4), "y": round(float(Xi.iloc[i][v[1]]), 4), "segment": "anomaly" if flag[i] else "typical"} for i in samp],
               "x", [{"key": "y", "label": v[1]}], group="segment", x_label=v[0], y_label=v[1])
ifrt.emit()
'''


class DescriptiveMethod(Method):
    key = "descriptive"
    task_type = "descriptive"
    title = "Exploratory data analysis"
    strategies = ["summary"]

    def stages(self, params, strategy):
        return [Stage("describe", "Summarise distributions, categories and correlations",
                      header(params, strategy, "import numpy as np\nimport pandas as pd") + DESCRIBE,
                      "Computes summary statistics, distributions and rank correlations for the relevant columns.")]

    def assess(self, result, params, strategy):
        return Assessment("succeeded") if metric_value(result, "rows") else Assessment("failed", "No summary produced.", "missing_output")

    def findings(self, result, params):
        F = [Finding(f"Dataset has {metric_value(result, 'rows'):,} rows", "Summary statistics for numeric columns and frequency tables for categorical columns are shown below.",
                     ["rows"], "observation", "high")]
        for p in result.get("artifacts", {}).get("top_correlations", []):
            if p["spearman"] is not None and abs(p["spearman"]) >= 0.3:
                F.append(Finding(f"{p['a']} and {p['b']} move together (Spearman {p['spearman']:.2f})",
                                 "This is a rank correlation; it does not establish that one causes the other.", ["top_correlations"], "observation", "medium"))
        return F, [], ["Descriptive statistics summarise this sample only; they do not test hypotheses or imply causation."]


class ComparisonMethod(Method):
    key = "comparison"
    task_type = "comparison"
    title = "Group comparison"
    strategies = ["group_summary"]

    def requirements(self, profile, params):
        return [m for m, k in (("a numeric measure to compare", "value_col"), ("a grouping column", "group")) if not params.get(k)]

    def stages(self, params, strategy):
        return [Stage("compare", f"Compare {params.get('value_col')} across {params.get('group')}",
                      header(params, strategy, "import numpy as np\nimport pandas as pd") + COMPARE,
                      "Computes per-group totals, means and 95% confidence intervals, with a screening test across groups.")]

    def assess(self, result, params, strategy):
        return Assessment("succeeded") if metric_value(result, "groups") else Assessment("failed", "No groups compared.", "missing_output")

    def findings(self, result, params):
        mv = lambda k, d=None: metric_value(result, k, d)  # noqa: E731
        overlap = mv("ci_overlap_top_bottom")
        F = [Finding(f"{mv('top_group')} has the highest mean {params.get('value_col')} ({fmt_num(mv('top_mean'))}); {mv('bottom_group')} the lowest ({fmt_num(mv('bottom_mean'))})",
                     f"Across {mv('groups')} groups. " + ("The 95% intervals of the top and bottom groups overlap, so the gap may be noise." if overlap else
                                                          "Their 95% confidence intervals do not overlap."),
                     ["group_mean_0", "group_total_0"], "observation", "high")]
        if mv("kruskal_p") is not None:
            F.append(Finding("Screening test across groups", f"Kruskal-Wallis p = {mv('kruskal_p'):.4f}. Ask a hypothesis-testing question for a full test with assumption checks.",
                             ["kruskal_p"], "inference", "medium"))
        return F, [], ["Group differences are descriptive and can be explained by other variables (confounding)."]


class SegmentationMethod(Method):
    key = "segmentation"
    task_type = "segmentation"
    title = "Segmentation"
    strategies = ["kmeans", "kmeans_log", "gaussian_mixture"]
    retry_map = {"weak_structure": ["kmeans_log", "gaussian_mixture"]}

    def requirements(self, profile, params):
        return [] if len(params.get("features") or []) >= 2 else ["at least two numeric columns to segment on"]

    def stages(self, params, strategy):
        return [Stage("segment", f"Find segments with {strategy.replace('_', ' ')} (k = 2..6, chosen by silhouette)",
                      header(params, strategy, "import numpy as np\nimport pandas as pd") + SEGMENT,
                      "Standardises features, tries 2–6 segments and keeps the best-separated solution.")]

    def assess(self, result, params, strategy):
        sil = metric_value(result, "silhouette")
        if sil is None:
            return Assessment("failed", "Clustering failed.", "model_error")
        if sil < 0.2:
            return Assessment("weak", f"Silhouette {sil:.2f}: segments are poorly separated.", "weak_structure", ("silhouette", sil))
        return Assessment("succeeded", headline_metric=("silhouette", sil))

    def conditions(self, df, profile, params):
        import pandas as pd
        f = params.get("features") or []
        sk = [abs(float(pd.to_numeric(df[c], errors="coerce").skew())) for c in f if c in df]
        return {"skewed_features": "yes" if sk and max(sk) > 1 else "no"}

    def findings(self, result, params):
        segs = result.get("artifacts", {}).get("segments", [])
        F = [Finding(f"{metric_value(result, 'k')} segments found (silhouette {metric_value(result, 'silhouette', 0):.2f})",
                     "; ".join(f"Segment {s['segment']} ({s['size']:,} rows): " + ", ".join(s["traits"]) for s in segs), ["silhouette"], "observation", "medium")]
        return F, [Recommendation("Review segment profiles with domain experts before using them for targeting.", "Clusters are statistical groupings, not ground truth.", ["silhouette"])], \
            ["Segments depend on which features were included and how they were scaled."]


class AnomalyMethod(Method):
    key = "anomaly_detection"
    task_type = "anomaly_detection"
    title = "Anomaly detection"
    strategies = ["isolation_forest", "robust_zscore"]

    def requirements(self, profile, params):
        return [] if params.get("features") else ["at least one numeric column"]

    def stages(self, params, strategy):
        return [Stage("anomaly", f"Flag unusual rows with {strategy.replace('_', ' ')}", header(params, strategy, "import numpy as np\nimport pandas as pd") + ANOMALY,
                      "Scores each row by how different it is from the rest and lists the most unusual records.")]

    def assess(self, result, params, strategy):
        a = metric_value(result, "anomalies")
        if a is None:
            return Assessment("failed", "No anomaly scores.", "model_error")
        if metric_value(result, "anomaly_rate_pct", 0) > 20:
            return Assessment("weak", "More than 20% of rows were flagged, which is not a useful definition of 'anomalous'.", "too_many_flags")
        return Assessment("succeeded")

    retry_map = {"too_many_flags": ["robust_zscore"]}

    def findings(self, result, params):
        F = [Finding(f"{metric_value(result, 'anomalies'):,} rows flagged as unusual ({metric_value(result, 'anomaly_rate_pct', 0):.1f}%)",
                     "The most unusual rows are listed with their scores. Unusual does not necessarily mean wrong.", ["anomalies"], "observation", "medium")]
        return F, [Recommendation("Review the top flagged rows manually to separate data errors from genuine extreme cases.", "Anomaly scores are statistical, not confirmed problems.", ["anomalies"])], \
            ["Anomaly detection is unsupervised; without labelled examples its precision cannot be measured."]
