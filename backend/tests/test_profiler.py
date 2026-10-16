import numpy as np
import pandas as pd

from app.profiler import apply_cleaning, profile_dataframe


def make_df():
    rng = np.random.default_rng(0)
    n = 300
    return pd.DataFrame({
        "customer_id": [f"C{i:04d}" for i in range(n)],
        "order_date": pd.date_range("2024-01-01", periods=n, freq="D").astype(str),
        "region": rng.choice(["North", "north ", "South"], n),
        "revenue": rng.gamma(2, 50, n),
        "quantity": rng.integers(1, 5, n),
        "churned": rng.choice([0, 1], n, p=[0.8, 0.2]),
    })


def test_profile_types_and_roles():
    p = profile_dataframe(make_df())
    cols = {c["name"]: c for c in p["columns"]}
    assert p["n_rows"] == 300
    assert cols["order_date"]["semantic_type"] == "datetime"
    assert cols["customer_id"]["semantic_type"] in ("identifier", "id")
    assert "quantity" in cols["quantity"]["roles"]
    assert any(t["column"] == "churned" for t in p["candidate_targets"])


def test_inconsistent_categories_detected_and_cleaned():
    df = make_df()
    p = profile_dataframe(df)
    assert any("region" in str(i) for i in p["issues"])
    out, log = apply_cleaning(df, [{"op": "normalize_categories", "column": "region"}])
    assert out["region"].str.strip().str.lower().nunique() == out["region"].nunique() == 2
    assert log


def test_duplicates_removed():
    df = pd.concat([make_df(), make_df().head(10)])
    out, _ = apply_cleaning(df, [{"op": "drop_duplicates"}])
    assert len(out) == 300
