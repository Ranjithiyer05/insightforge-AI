import numpy as np
import pandas as pd

from app.planner import classify, make_plan
from app.profiler import profile_dataframe


def profile():
    rng = np.random.default_rng(1)
    n = 200
    return profile_dataframe(pd.DataFrame({
        "order_date": pd.date_range("2024-01-01", periods=n, freq="D").astype(str),
        "region": rng.choice(["N", "S"], n), "revenue": rng.gamma(2, 50, n), "cost": rng.gamma(2, 30, n),
        "tenure_months": rng.integers(1, 60, n), "churned": rng.choice([0, 1], n),
    }))


def test_classify():
    p = profile()
    assert classify("Which customers are likely to churn?", p)[0] == "classification"
    assert classify("Forecast revenue for the next 3 months", p)[0] == "forecasting"
    assert classify("Is there a significant difference in tenure between churned and retained?", p)[0] == "hypothesis_test"
    assert classify("Segment our customers", p)[0] == "segmentation"


def test_plan_has_target_and_steps():
    plan = make_plan("Which customers are likely to churn?", profile())
    assert plan["params"]["target"] == "churned"
    assert plan["steps"] and plan["strategies"]
