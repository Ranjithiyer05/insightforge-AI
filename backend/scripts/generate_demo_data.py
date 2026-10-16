"""Generate the clearly-labelled SYNTHETIC demo datasets shipped with InsightForge AI.

retail_sales_SYNTHETIC.csv
    Order lines Jan 2024 – Jun 2025 for an invented outdoor/fitness retailer.
    Planted, known effects in June 2025 (so the demo has a ground truth):
      * Trail Running Shoe: supplier unit cost +22%
      * Smart Water Bottle: promotion, discount ~25% (from ~5%), volume up ~30%
      * Yoga Mat Pro: demand drop ~40% (simulated stock-out)
      * Insulated Jacket: normal seasonal summer decline (also present in June 2024)
    Data-quality quirks: a few duplicated rows, inconsistent region spellings,
    some missing channel values.

customer_churn_SYNTHETIC.csv
    Invented subscription customers with ~20% churn, driven by tenure,
    support tickets, contract type and price increases.

Run: python scripts/generate_demo_data.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent.parent / "demo_data"

PRODUCTS = [
    # name, category, price, unit cost, base daily units, seasonality ("summer"/"winter"/None)
    ("Trail Running Shoe", "Footwear", 129.0, 58.0, 9, None),
    ("Road Running Shoe", "Footwear", 119.0, 55.0, 8, None),
    ("Hiking Boot", "Footwear", 159.0, 74.0, 4, "winter"),
    ("Insulated Jacket", "Outerwear", 189.0, 82.0, 5, "winter"),
    ("Rain Shell", "Outerwear", 99.0, 41.0, 4, None),
    ("Fleece Pullover", "Outerwear", 69.0, 27.0, 5, "winter"),
    ("Smart Water Bottle", "Accessories", 39.0, 14.0, 10, "summer"),
    ("Sport Sunglasses", "Accessories", 79.0, 24.0, 4, "summer"),
    ("Running Cap", "Accessories", 25.0, 8.0, 7, "summer"),
    ("Yoga Mat Pro", "Fitness", 89.0, 31.0, 6, None),
    ("Resistance Band Set", "Fitness", 35.0, 11.0, 6, None),
    ("Adjustable Dumbbells", "Fitness", 249.0, 140.0, 2, "winter"),
]
REGIONS = ["North", "South", "East", "West"]
CHANNELS = ["Online", "Store"]


def retail(seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    days = pd.date_range("2024-01-01", "2025-06-30", freq="D")
    rows = []
    oid = 100000
    for day in days:
        m = day.month
        weekend = 1.25 if day.dayofweek >= 5 else 1.0
        trend = 1 + 0.06 * ((day - days[0]).days / 365)
        jun25 = day.year == 2025 and m == 6
        for name, cat, price, ucost, base, season in PRODUCTS:
            s = 1.0
            if season == "summer":
                s = 1 + 0.45 * np.cos((m - 7) / 12 * 2 * np.pi)
            elif season == "winter":
                s = 1 + 0.55 * np.cos((m - 1) / 12 * 2 * np.pi)
            lam = base * s * weekend * trend / 2.2
            disc_mu = 0.05
            cost = ucost * (1 + 0.01 * (day.year - 2024))
            if jun25 and name == "Trail Running Shoe":
                cost = ucost * 1.22
            if jun25 and name == "Smart Water Bottle":
                disc_mu, lam = 0.25, lam * 1.3
            if jun25 and name == "Yoga Mat Pro":
                lam *= 0.6
            n_lines = rng.poisson(lam)
            for _ in range(n_lines):
                oid += 1
                qty = int(rng.choice([1, 1, 1, 2, 2, 3]))
                disc = float(np.clip(rng.normal(disc_mu, 0.03), 0, 0.5))
                disc = round(disc * 100) / 100
                uc = round(cost * rng.normal(1, 0.02), 2)
                rev = round(price * qty * (1 - disc), 2)
                rows.append({
                    "order_id": f"SO-{oid}", "order_date": day.date().isoformat(),
                    "region": rng.choice(REGIONS, p=[0.3, 0.25, 0.25, 0.2]),
                    "channel": rng.choice(CHANNELS, p=[0.55, 0.45]),
                    "category": cat, "product": name, "quantity": qty, "unit_price": price,
                    "discount_pct": round(disc * 100, 1), "revenue": rev, "unit_cost": uc, "cost": round(uc * qty, 2),
                })
    df = pd.DataFrame(rows)
    # Data-quality quirks (documented above).
    idx = rng.choice(len(df), 40, replace=False)
    df.loc[idx[:25], "region"] = df.loc[idx[:25], "region"].str.lower()
    df.loc[idx[25:], "region"] = df.loc[idx[25:], "region"] + " "
    df.loc[rng.choice(len(df), 60, replace=False), "channel"] = np.nan
    dups = df.sample(18, random_state=seed)
    return pd.concat([df, dups]).sort_values("order_date", kind="stable").reset_index(drop=True)


def churn(seed: int = 11, n: int = 4000) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    tenure = rng.gamma(2.0, 14, n).clip(1, 72).round()
    contract = rng.choice(["Monthly", "Annual", "Two-year"], n, p=[0.55, 0.3, 0.15])
    tickets = rng.poisson(1.2, n)
    monthly = rng.normal(55, 18, n).clip(15, 140).round(2)
    price_increase = rng.choice([0, 1], n, p=[0.75, 0.25])
    usage = rng.normal(20, 8, n).clip(0).round(1)
    region = rng.choice(REGIONS, n)
    logit = (-1.4 - 0.045 * tenure + 0.45 * tickets + 0.9 * price_increase + 0.012 * (monthly - 55)
             - 0.04 * (usage - 20) + np.where(contract == "Monthly", 0.8, np.where(contract == "Annual", -0.4, -1.2)))
    p = 1 / (1 + np.exp(-logit))
    churned = (rng.random(n) < p).astype(int)
    return pd.DataFrame({
        "customer_id": [f"C{100000 + i}" for i in range(n)], "region": region, "contract_type": contract,
        "tenure_months": tenure.astype(int), "monthly_charge": monthly, "support_tickets_90d": tickets,
        "had_price_increase": price_increase, "avg_weekly_usage_hours": usage, "churned": churned,
    })


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    r = retail()
    r.to_csv(OUT / "retail_sales_SYNTHETIC.csv", index=False)
    c = churn()
    c.to_csv(OUT / "customer_churn_SYNTHETIC.csv", index=False)
    print(f"retail: {len(r):,} rows; churn: {len(c):,} rows, churn rate {c.churned.mean():.1%}")
