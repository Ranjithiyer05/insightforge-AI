"""Diagnose a change in profit between two periods (e.g. "why did profit decline last month?").

Uses an exact price-volume-cost decomposition per product, which is an
accounting identity (it explains *where* the change shows up, not *why* it
happened causally), plus checks for seasonality, partial periods and whether
the change is unusual relative to historical variation.
"""
from __future__ import annotations

from typing import Any

from .base import Assessment, Finding, Method, Recommendation, Stage, fmt_num, fmt_p, header, metric_value, sql_ident

PRELUDE = r'''
def prepare(df):
    d = P["date_col"]
    df = df[df[d].notna()].copy()
    out = pd.DataFrame(index=df.index)
    out["date"] = df[d]
    out["month"] = df[d].dt.to_period("M").astype(str)
    q = P.get("quantity_col")
    out["units"] = pd.to_numeric(df[q], errors="coerce") if q else 1.0
    disc = None
    if P.get("discount_col"):
        disc = pd.to_numeric(df[P["discount_col"]], errors="coerce").fillna(0.0)
        if disc.max() > 1.0:
            disc = disc / 100.0
        out["discount"] = disc
    if P.get("unit_price_col"):
        out["list_revenue"] = pd.to_numeric(df[P["unit_price_col"]], errors="coerce") * out["units"]
    if P.get("revenue_col"):
        out["revenue"] = pd.to_numeric(df[P["revenue_col"]], errors="coerce")
    else:
        out["revenue"] = out["list_revenue"] * (1 - (disc if disc is not None else 0.0))
    if P.get("cost_col"):
        out["cost"] = pd.to_numeric(df[P["cost_col"]], errors="coerce")
    elif P.get("unit_cost_col"):
        out["cost"] = pd.to_numeric(df[P["unit_cost_col"]], errors="coerce") * out["units"]
    else:
        out["cost"] = out["revenue"] - pd.to_numeric(df[P["profit_col"]], errors="coerce")
    out["profit"] = out["revenue"] - out["cost"]
    if P.get("product_col"):
        out["product"] = df[P["product_col"]].astype(str)
    return out.dropna(subset=["revenue", "cost", "units"])


def pick_periods(w):
    months = sorted(w["month"].unique())
    days = w.groupby("month")["date"].apply(lambda s: s.dt.normalize().nunique())
    last = months[-1]
    partial = False
    if len(months) >= 3:
        typical = days[months[:-1]].median()
        month_end = pd.Period(last).end_time
        if days[last] < 0.8 * typical and (month_end - w["date"].max()).days > 3:
            partial = True
    cur = months[-2] if partial else months[-1]
    if P.get("current_period") in months:
        cur = P["current_period"]
    prev = months[months.index(cur) - 1]
    return cur, prev, partial, last
'''


def _stage1(params: dict[str, Any], strategy: str) -> str:
    sql = (
        "SELECT month, SUM(revenue) AS revenue, SUM(cost) AS cost, SUM(revenue) - SUM(cost) AS profit,\n"
        "       COUNT(*) AS line_items, SUM(units) AS units\n"
        "FROM sales\nGROUP BY month\nORDER BY month"
    )
    return header(params, strategy, "import sqlite3\nimport numpy as np\nimport pandas as pd") + PRELUDE + f'''
df = ifrt.load_df(parse_dates=[P["date_col"]])
w = prepare(df)
cur, prev, partial, last = pick_periods(w)
if partial:
    ifrt.warn(f"The latest month {{last}} looks incomplete (fewer active days than usual); comparing {{cur}} with {{prev}} instead.")

# Monthly aggregation in SQL (in-memory SQLite, parameter-free query over a derived table).
con = sqlite3.connect(":memory:")
w[["month", "revenue", "cost", "units"]].to_sql("sales", con, index=False)
SQL = """{sql}"""
monthly = pd.read_sql_query(SQL, con)
con.close()
monthly["margin_pct"] = np.where(monthly["revenue"] != 0, monthly["profit"] / monthly["revenue"] * 100, np.nan)
ifrt.table("monthly_summary", monthly.round(2))
ifrt.artifact("sql", SQL)

m = monthly.set_index("month")
p0, p1 = float(m.loc[prev, "profit"]), float(m.loc[cur, "profit"])
r0, r1 = float(m.loc[prev, "revenue"]), float(m.loc[cur, "revenue"])
ifrt.metric("current_period", cur)
ifrt.metric("previous_period", prev)
ifrt.metric("latest_period_partial", bool(partial))
ifrt.metric("profit_current", p1, unit="currency")
ifrt.metric("profit_previous", p0, unit="currency")
ifrt.metric("profit_change", p1 - p0, unit="currency")
ifrt.metric("profit_change_pct", (p1 - p0) / abs(p0) * 100 if p0 else None, unit="%")
ifrt.metric("revenue_current", r1, unit="currency")
ifrt.metric("revenue_previous", r0, unit="currency")
ifrt.metric("revenue_change_pct", (r1 - r0) / abs(r0) * 100 if r0 else None, unit="%")
ifrt.metric("margin_current_pct", float(m.loc[cur, "margin_pct"]), unit="%")
ifrt.metric("margin_previous_pct", float(m.loc[prev, "margin_pct"]), unit="%")
ifrt.metric("months_covered", int(len(m)))

ifrt.claim("profit_current", f"Profit in {{cur}}", p1, {{"kind": "period_sum", "measure": "profit", "period": cur}})
ifrt.claim("profit_previous", f"Profit in {{prev}}", p0, {{"kind": "period_sum", "measure": "profit", "period": prev}})
ifrt.claim("revenue_current", f"Revenue in {{cur}}", r1, {{"kind": "period_sum", "measure": "revenue", "period": cur}})
ifrt.claim("revenue_previous", f"Revenue in {{prev}}", r0, {{"kind": "period_sum", "measure": "revenue", "period": prev}})

ifrt.chart("monthly_trend", "line", "Revenue, cost and profit by month", monthly.round(2).to_dict("records"), "month",
           [{{"key": "revenue", "label": "Revenue"}}, {{"key": "cost", "label": "Cost"}}, {{"key": "profit", "label": "Profit"}}],
           highlight=[prev, cur], unit="currency")
ifrt.chart("monthly_margin", "line", "Profit margin by month (%)", monthly[["month", "margin_pct"]].round(2).to_dict("records"), "month",
           [{{"key": "margin_pct", "label": "Margin %"}}], highlight=[prev, cur], unit="%")
ifrt.emit()
'''


def _stage2(params: dict[str, Any], strategy: str) -> str:
    return header(params, strategy, "import numpy as np\nimport pandas as pd") + PRELUDE + r'''
df = ifrt.load_df(parse_dates=[P["date_col"]])
w = prepare(df)
cur, prev, partial, last = pick_periods(w)
agg = dict(units=("units", "sum"), revenue=("revenue", "sum"), cost=("cost", "sum"))
g0 = w[w["month"] == prev].groupby("product").agg(**agg)
g1 = w[w["month"] == cur].groupby("product").agg(**agg)
t = g0.join(g1, lsuffix="_prev", rsuffix="_cur", how="outer").fillna(0.0)
t["profit_prev"] = t["revenue_prev"] - t["cost_prev"]
t["profit_cur"] = t["revenue_cur"] - t["cost_cur"]
t["profit_delta"] = t["profit_cur"] - t["profit_prev"]

# Exact price-volume-cost decomposition: delta = volume + price + cost (accounting identity).
q0, q1 = t["units_prev"], t["units_cur"]
p0 = np.where(q0 > 0, t["revenue_prev"] / q0.where(q0 > 0, 1), 0.0)
p1 = np.where(q1 > 0, t["revenue_cur"] / q1.where(q1 > 0, 1), 0.0)
c0 = np.where(q0 > 0, t["cost_prev"] / q0.where(q0 > 0, 1), 0.0)
c1 = np.where(q1 > 0, t["cost_cur"] / q1.where(q1 > 0, 1), 0.0)
both = (q0 > 0) & (q1 > 0)
t["volume_effect"] = np.where(both, (q1 - q0) * (p0 - c0), t["profit_delta"])
t["price_discount_effect"] = np.where(both, q1 * (p1 - p0), 0.0)
t["unit_cost_effect"] = np.where(both, -q1 * (c1 - c0), 0.0)
t["net_price_change_pct"] = np.where(both & (p0 != 0), (p1 - p0) / np.where(p0 != 0, p0, 1) * 100, np.nan)
t["unit_cost_change_pct"] = np.where(both & (c0 != 0), (c1 - c0) / np.where(c0 != 0, c0, 1) * 100, np.nan)
t["units_change_pct"] = np.where(q0 > 0, (q1 - q0) / q0.where(q0 > 0, 1) * 100, np.nan)
resid = float((t["profit_delta"] - t["volume_effect"] - t["price_discount_effect"] - t["unit_cost_effect"]).abs().max())
ifrt.metric("decomposition_max_residual", resid)
t = t.sort_values("profit_delta")
eff = ["volume_effect", "price_discount_effect", "unit_cost_effect"]
dom = t[eff].idxmin(axis=1).where(t["profit_delta"] < 0, t[eff].idxmax(axis=1))
t["dominant_driver"] = dom.str.replace("_effect", "")
out = t.reset_index().rename(columns={"index": "product"})
ifrt.table("product_contribution", out.round(2))

total = float(t["profit_delta"].sum())
ifrt.metric("total_profit_delta", total, unit="currency")
for e in eff:
    ifrt.metric(f"total_{e}", float(t[e].sum()), unit="currency")
    ifrt.claim(f"total_{e}", f"Total {e.replace('_', ' ')} ({prev} to {cur})", float(t[e].sum()),
               {"kind": "pvm_effect", "effect": e, "periods": [prev, cur]})
decliners = t[t["profit_delta"] < 0]
ifrt.metric("products_declining", int(len(decliners)))
ifrt.metric("products_total", int(len(t)))
neg_total = float(decliners["profit_delta"].sum())
top3 = decliners.head(3)
ifrt.metric("top3_share_of_declines", float(top3["profit_delta"].sum() / neg_total * 100) if neg_total else None, unit="%")
ifrt.claim("total_profit_delta", f"Change in profit {prev} to {cur}", total,
           {"kind": "period_delta", "measure": "profit", "periods": [prev, cur]})
ranked = []
for i, (prod, row) in enumerate(t.head(5).iterrows()):
    ranked.append({"product": prod, "profit_delta": float(row["profit_delta"]), "dominant_driver": row["dominant_driver"],
                   "volume_effect": float(row["volume_effect"]), "price_discount_effect": float(row["price_discount_effect"]),
                   "unit_cost_effect": float(row["unit_cost_effect"]), "units_change_pct": row["units_change_pct"],
                   "net_price_change_pct": row["net_price_change_pct"], "unit_cost_change_pct": row["unit_cost_change_pct"]})
    if i < 3:
        ifrt.claim(f"product_delta_{i+1}", f"Profit change for {prod}", float(row["profit_delta"]),
                   {"kind": "period_delta", "measure": "profit", "periods": [prev, cur], "filter": {"product": prod}})
ifrt.artifact("ranked_products", ranked)

top = t.reindex(t["profit_delta"].abs().sort_values(ascending=False).index).head(10).sort_values("profit_delta")
ifrt.chart("product_delta", "bar", f"Profit change by product ({prev} to {cur})",
           [{"product": k, "profit_delta": round(float(v), 2)} for k, v in top["profit_delta"].items()], "product",
           [{"key": "profit_delta", "label": "Profit change"}], unit="currency", layout="horizontal")
ifrt.chart("driver_decomposition", "stacked_bar", "What moved profit, by product (price-volume-cost decomposition)",
           [{"product": k, "volume": round(float(r["volume_effect"]), 2), "price_discount": round(float(r["price_discount_effect"]), 2),
             "unit_cost": round(float(r["unit_cost_effect"]), 2)} for k, r in top.head(8).iterrows()], "product",
           [{"key": "volume", "label": "Volume"}, {"key": "price_discount", "label": "Price / discount"}, {"key": "unit_cost", "label": "Unit cost"}],
           unit="currency", layout="horizontal")
ifrt.emit()
'''


def _stage3(params: dict[str, Any], strategy: str) -> str:
    return header(params, strategy, "import numpy as np\nimport pandas as pd\nfrom scipy import stats") + PRELUDE + r'''
df = ifrt.load_df(parse_dates=[P["date_col"]])
w = prepare(df)
cur, prev, partial, last = pick_periods(w)
months = sorted(w["month"].unique())

# 1) Discount rate trend
if "discount" in w.columns:
    if "list_revenue" in w.columns:
        dm = w.groupby("month").apply(lambda g: float((g["discount"] * g["list_revenue"]).sum() / g["list_revenue"].sum() * 100), include_groups=False)
        how = "list-price-weighted"
    else:
        dm = w.groupby("month").apply(lambda g: float(np.average(g["discount"], weights=g["revenue"].abs() + 1e-9) * 100), include_groups=False)
        how = "revenue-weighted"
    ifrt.metric("discount_rate_current_pct", float(dm[cur]), unit="%", method=how)
    ifrt.metric("discount_rate_previous_pct", float(dm[prev]), unit="%", method=how)
    ifrt.claim("discount_rate_current_pct", f"Average discount rate in {cur} ({how})", float(dm[cur]),
               {"kind": "weighted_discount", "period": cur, "method": how})
    ifrt.claim("discount_rate_previous_pct", f"Average discount rate in {prev} ({how})", float(dm[prev]),
               {"kind": "weighted_discount", "period": prev, "method": how})
    ifrt.chart("discount_trend", "line", f"Average discount rate by month ({how}, %)",
               [{"month": k, "discount_pct": round(v, 3)} for k, v in dm.items()], "month",
               [{"key": "discount_pct", "label": "Discount %"}], highlight=[prev, cur], unit="%")
    if "product" in w.columns:
        pd_ = w[w["month"].isin([prev, cur])].groupby(["product", "month"]).apply(
            lambda g: float(g["discount"].mean() * 100), include_groups=False).unstack()
        if prev in pd_ and cur in pd_:
            pd_["change_pp"] = pd_[cur] - pd_[prev]
            ifrt.table("discount_by_product", pd_.sort_values("change_pp", ascending=False).round(2).reset_index())
else:
    ifrt.note("No discount column was identified, so discounting could not be assessed directly.")

# 2) Unit cost trend
uc = w.groupby("month").apply(lambda g: float(g["cost"].sum() / g["units"].sum()), include_groups=False)
ifrt.metric("unit_cost_current", float(uc[cur]))
ifrt.metric("unit_cost_previous", float(uc[prev]))

# 3) Is this change unusual? Compare with historical month-to-month profit changes.
mp = w.groupby("month")["profit"].sum()
mp = mp.loc[[m for m in months if m <= cur]]
chg = mp.pct_change().dropna() * 100
hist = chg.iloc[:-1]
last_chg = float(chg.iloc[-1]) if len(chg) else None
ifrt.metric("historical_changes_n", int(len(hist)))
if len(hist) >= 4 and hist.std() > 0:
    z = (last_chg - hist.mean()) / hist.std(ddof=1)
    pct = float((hist <= last_chg).mean() * 100)
    ifrt.metric("mom_change_z", float(z))
    ifrt.metric("mom_change_percentile", pct, unit="%")
    ifrt.metric("historical_mom_change_sd_pct", float(hist.std(ddof=1)), unit="%")
else:
    ifrt.note("Too few months of history to judge whether this change is unusual.")
ifrt.chart("mom_changes", "bar", "Month-over-month profit change (%)",
           [{"month": k, "change_pct": round(float(v), 2)} for k, v in chg.items()], "month",
           [{"key": "change_pct", "label": "MoM change %"}], highlight=[cur], unit="%")

# 4) Seasonality: did the same transition happen a year earlier?
cp, pp = pd.Period(cur), pd.Period(prev)
ly_cur, ly_prev = str(cp - 12), str(pp - 12)
allm = w.groupby("month")["profit"].sum()
if ly_cur in allm.index and ly_prev in allm.index and allm[ly_prev] != 0:
    yoy = float((allm[ly_cur] - allm[ly_prev]) / abs(allm[ly_prev]) * 100)
    ifrt.metric("same_transition_last_year_pct", yoy, unit="%", periods=[ly_prev, ly_cur])
    ifrt.claim("same_transition_last_year_pct", f"Profit change {ly_prev} to {ly_cur}", yoy,
               {"kind": "period_pct_change", "measure": "profit", "periods": [ly_prev, ly_cur]})
else:
    ifrt.note("No data for the same months last year, so seasonality could not be checked.")

# 5) Uncertainty on the size of the change, using daily profit totals.
daily = w.assign(day=w["date"].dt.normalize()).groupby(["month", "day"])["profit"].sum().reset_index()
a = daily.loc[daily["month"] == prev, "profit"].to_numpy()
b = daily.loc[daily["month"] == cur, "profit"].to_numpy()
if len(a) >= 5 and len(b) >= 5:
    rng = np.random.default_rng(SEED)
    boots = [rng.choice(b, len(b)).mean() - rng.choice(a, len(a)).mean() for _ in range(2000)]
    lo, hi = np.percentile(boots, [2.5, 97.5])
    diff = float(b.mean() - a.mean())
    welch = stats.ttest_ind(b, a, equal_var=False)
    mw = stats.mannwhitneyu(b, a, alternative="two-sided")
    ifrt.metric("daily_profit_mean_diff", diff, unit="currency", ci95=[float(lo), float(hi)], method="bootstrap (2000 resamples)")
    ifrt.metric("daily_profit_welch_p", float(welch.pvalue))
    ifrt.metric("daily_profit_mannwhitney_p", float(mw.pvalue))
    ifrt.metric("days_compared", [int(len(a)), int(len(b))])
    ifrt.claim("daily_profit_mean_diff", f"Mean daily profit difference ({cur} minus {prev})", diff,
               {"kind": "daily_mean_diff", "periods": [prev, cur]})
    ifrt.claim("daily_profit_welch_p", "Welch t-test p-value on daily profit", float(welch.pvalue),
               {"kind": "daily_welch_p", "periods": [prev, cur]})
    ifrt.note("Daily totals within a month are not fully independent (weekly patterns), so p-values and intervals are approximate.")
ifrt.emit()
'''


class ProfitChangeMethod(Method):
    key = "profit_change"
    task_type = "profit_change"
    title = "Profit change diagnosis"
    strategies = ["pvm_decomposition"]

    def requirements(self, profile, params):
        missing = []
        if not params.get("date_col"):
            missing.append("a date column (to define months)")
        if not (params.get("revenue_col") or params.get("unit_price_col")):
            missing.append("a revenue/sales column or a unit price column")
        if not (params.get("cost_col") or params.get("unit_cost_col") or params.get("profit_col")):
            missing.append("a cost, unit cost or profit column")
        if not params.get("product_col"):
            missing.append("a product (or category) column to compare products")
        if not (params.get("revenue_col") or params.get("quantity_col")):
            missing.append("a quantity column (needed to derive revenue from unit price)")
        return missing

    def stages(self, params, strategy):
        return [
            Stage("trend", "Calculate monthly revenue and profit trend (SQL)", _stage1(params, strategy),
                  "Aggregates line items to months with SQL so the trend and the two periods being compared are explicit.", kind="sql"),
            Stage("products", "Compare products and decompose the profit change", _stage2(params, strategy),
                  "Splits each product's profit change exactly into volume, price/discount and unit-cost effects."),
            Stage("drivers", "Check discounts, costs, seasonality and uncertainty", _stage3(params, strategy),
                  "Tests alternative explanations: discounting, cost inflation, normal month-to-month noise and seasonality."),
        ]

    def assess(self, result, params, strategy):
        if metric_value(result, "profit_change") is None:
            return Assessment("failed", "The profit trend could not be computed.", "missing_output")
        resid = metric_value(result, "decomposition_max_residual")
        if resid is not None and resid > 1e-6 * max(1.0, abs(metric_value(result, "profit_previous", 1.0))):
            return Assessment("invalid", f"Decomposition does not reconcile (residual {resid:.4f}).", "decomposition_mismatch")
        return Assessment("succeeded", headline_metric=("profit_change_pct", metric_value(result, "profit_change_pct", 0.0)))

    def findings(self, result, params):
        F: list[Finding] = []
        R: list[Recommendation] = []
        L: list[str] = []
        mv = lambda k, d=None: metric_value(result, k, d)  # noqa: E731
        cur, prev = mv("current_period"), mv("previous_period")
        chg, chg_pct = mv("profit_change"), mv("profit_change_pct")
        p0, p1 = mv("profit_previous"), mv("profit_current")
        direction = "fell" if (chg or 0) < 0 else "rose"
        F.append(Finding(
            f"Profit {direction} {abs(chg_pct or 0):.1f}% in {cur} versus {prev}",
            f"Profit went from {fmt_num(p0, True)} in {prev} to {fmt_num(p1, True)} in {cur} ({fmt_num(chg, True)}). "
            f"Revenue changed {mv('revenue_change_pct', 0):+.1f}% and margin moved from {mv('margin_previous_pct', 0):.1f}% to {mv('margin_current_pct', 0):.1f}%.",
            ["profit_current", "profit_previous", "revenue_current", "revenue_previous"], "observation", "high"))
        if (chg or 0) >= 0:
            F.append(Finding("The premise of a decline is not supported", f"Profit did not decline between {prev} and {cur}; it increased. The rest of this report explains what moved.",
                             ["profit_current", "profit_previous"], "caution", "high"))
        if mv("latest_period_partial"):
            L.append("The most recent month in the file looks incomplete, so it was excluded from the comparison.")
        effects = {"volume": mv("total_volume_effect", 0), "price / discount": mv("total_price_discount_effect", 0), "unit cost": mv("total_unit_cost_effect", 0)}
        parts = ", ".join(f"{k} {fmt_num(v, True)}" for k, v in effects.items())
        biggest = min(effects, key=effects.get) if (chg or 0) < 0 else max(effects, key=effects.get)
        F.append(Finding(
            f"Largest driver overall: {biggest}",
            f"Across all products the change splits into {parts}. These components are an exact accounting decomposition, not causal estimates.",
            ["total_volume_effect", "total_price_discount_effect", "total_unit_cost_effect", "total_profit_delta"], "observation", "high"))
        ranked = result.get("artifacts", {}).get("ranked_products", [])
        drivers_text = {"volume": "lower unit sales", "price_discount": "lower net selling price (price cuts or deeper discounts)", "unit_cost": "higher unit cost"}
        if ranked:
            top_lines = []
            for i, r in enumerate(ranked[:3]):
                if r["profit_delta"] >= 0:
                    continue
                d = r["dominant_driver"]
                detail = {"volume": f"units {r['units_change_pct']:+.1f}%" if r.get("units_change_pct") is not None else "volume change",
                          "price_discount": f"net price {r['net_price_change_pct']:+.1f}%" if r.get("net_price_change_pct") is not None else "net price change",
                          "unit_cost": f"unit cost {r['unit_cost_change_pct']:+.1f}%" if r.get("unit_cost_change_pct") is not None else "unit cost change"}[d]
                top_lines.append(f"{r['product']} ({fmt_num(r['profit_delta'], True)}, mainly {drivers_text[d]}: {detail})")
                R.append(Recommendation(
                    f"Investigate {r['product']}: " + {
                        "volume": "check stock availability, demand and seasonality for the drop in units.",
                        "price_discount": "review whether the price cut or discount paid for itself in extra volume.",
                        "unit_cost": "review supplier pricing, freight and cost allocation for the unit-cost increase."}[d],
                    f"Profit change {fmt_num(r['profit_delta'], True)}; dominant component {d.replace('_', ' / ')} ({detail}).",
                    [f"product_delta_{i+1}"]))
            if top_lines:
                share = mv("top3_share_of_declines")
                F.append(Finding("Products to investigate first", "; ".join(top_lines) + (f". Together the top three decliners account for {share:.0f}% of all product-level declines." if share else "."),
                                 [f"product_delta_{i+1}" for i in range(min(3, len(ranked)))], "observation", "high"))
        d0, d1 = mv("discount_rate_previous_pct"), mv("discount_rate_current_pct")
        if d0 is not None and d1 is not None:
            F.append(Finding(f"Average discount moved from {d0:.1f}% to {d1:.1f}%",
                             "Discounting " + ("increased" if d1 > d0 else "decreased") + f" by {abs(d1 - d0):.1f} percentage points between the two months.",
                             ["discount_rate_previous_pct", "discount_rate_current_pct"], "observation", "high"))
        z, pctile = mv("mom_change_z"), mv("mom_change_percentile")
        if z is not None:
            n_hist = mv("historical_changes_n")
            unusual = abs(z) >= 2 or pctile <= 5 or pctile >= 95
            rank = (f"it is lower than all {n_hist} earlier month-to-month changes" if pctile == 0 else
                    f"it is higher than all {n_hist} earlier changes" if pctile == 100 else f"it sits at the {pctile:.0f}th percentile of {n_hist} earlier changes")
            F.append(Finding("The change is " + ("unusual" if unusual else "within normal variation") + " compared with history",
                             f"The month-over-month change has z = {z:.2f} relative to history, and {rank}.", ["mom_change_z"], "inference", "medium"))
        yoy = mv("same_transition_last_year_pct")
        if yoy is not None:
            seasonal = (chg_pct or 0) < 0 and yoy < 0
            F.append(Finding("Seasonality " + ("may explain part of the change" if seasonal else "does not obviously explain the change"),
                             f"A year earlier, the same pair of months showed a profit change of {yoy:+.1f}%.",
                             ["same_transition_last_year_pct"], "inference", "medium"))
            if seasonal:
                L.append("Part of the decline may be seasonal; compare against the same month last year before acting.")
        diff = result.get("metrics", {}).get("daily_profit_mean_diff")
        if diff:
            lo, hi = diff.get("ci95", [None, None])
            F.append(Finding("Uncertainty in the size of the change",
                             f"Mean daily profit changed by {fmt_num(diff['value'], True)} (95% bootstrap CI {fmt_num(lo, True)} to {fmt_num(hi, True)}; "
                             f"Welch {fmt_p(mv('daily_profit_welch_p'))}).", ["daily_profit_mean_diff", "daily_profit_welch_p"], "inference", "medium"))
        L += [
            "The price-volume-cost split shows where the change appears in the numbers; it does not prove why customers or suppliers behaved differently.",
            "Other factors not in the data (competitor activity, stock-outs, marketing changes) could explain part of the change.",
        ]
        if not params.get("quantity_col"):
            L.append("No quantity column was available, so 'volume' counts line items rather than units.")
        return F, R, L

    def conditions(self, df, profile, params):
        return {"has_discount": "yes" if params.get("discount_col") else "no"}
