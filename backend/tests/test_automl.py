import time

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.automl import AutoMLError, predict_rows, shapley, train
from app.main import app
from app.profiler import profile_dataframe


def churn(n=600, leak=False):
    rng = np.random.default_rng(0)
    tenure = rng.integers(1, 60, n)
    tickets = rng.poisson(2, n)
    contract = rng.choice(["Monthly", "Annual"], n)
    logit = -1 + 0.6 * tickets - 0.05 * tenure + (contract == "Monthly") * 1.0
    y = (rng.random(n) < 1 / (1 + np.exp(-logit))).astype(int)
    df = pd.DataFrame({"customer_id": [f"C{i}" for i in range(n)], "tenure": tenure, "tickets": tickets, "contract": contract,
                       "noise": rng.normal(size=n), "churned": y})
    if leak:
        df["cancel_reason"] = np.where(y == 1, "price", "none")
    return df


def test_classification_beats_baseline_and_excludes_ids_and_leakage():
    df = churn(leak=True)
    r, blob = train(df, profile_dataframe(df), "churned")
    ex = {e["feature"] for e in r["excluded"]}
    assert "customer_id" in ex and "cancel_reason" in ex
    lb = {b["model"]: b for b in r["leaderboard"]}
    assert lb[r["best_model"]]["cv_roc_auc"] > lb["baseline"]["cv_roc_auc"] + 0.1
    assert r["n_train"] + r["n_test"] == len(df) and 0.6 < r["test_metrics"]["roc_auc"] < 0.99
    top = [i["feature"] for i in r["importance"][:3]]
    assert "tickets" in top and "noise" not in top[:2]


def test_shapley_is_additive():
    df = churn()
    r, blob = train(df, profile_dataframe(df), "churned")
    out = predict_rows(blob, [df.drop(columns="churned").iloc[3].to_dict()])[0]
    e = out["explanation"]
    assert e["output"] == pytest.approx(out["probability"], abs=1e-3)
    assert e["base_value"] + sum(c["contribution"] for c in e["contributions"]) == pytest.approx(out["probability"], abs=1e-3)


def test_shapley_matches_linear_model_exactly():
    X = pd.DataFrame({"a": [0.0, 1, 2, 3], "b": [1.0, 1, 0, 0]})
    bg = pd.DataFrame({"a": [1.0], "b": [0.0]})
    phi, base = shapley(lambda d: 2 * d["a"].to_numpy() - 3 * d["b"].to_numpy(), X, bg, n_perm=5)
    assert np.allclose(phi[:, 0], 2 * (X["a"] - 1)) and np.allclose(phi[:, 1], -3 * X["b"])


def test_regression_time_split_and_errors():
    rng = np.random.default_rng(1)
    n = 400
    df = pd.DataFrame({"day": pd.date_range("2024-01-01", periods=n, freq="D").astype(str), "x": rng.normal(size=n), "g": rng.choice(list("abc"), n)})
    df["y"] = 3 * df["x"] + (df["g"] == "a") * 2 + rng.normal(scale=0.5, size=n)
    r, _ = train(df, profile_dataframe(df), "y", split="time")
    assert r["task"] == "regression" and r["test_metrics"]["r2"] > 0.8 and "latest 25%" in r["split_description"]
    assert r["test_metrics"]["rmse"] < r["test_metrics"]["baseline_rmse"]
    with pytest.raises(AutoMLError):
        train(df.head(40), profile_dataframe(df.head(40)), "y")
    one = df.assign(c="same")
    with pytest.raises(AutoMLError):
        train(one, profile_dataframe(one), "c")


def test_automl_api_runs_and_is_private():
    c = TestClient(app)
    c.post("/api/auth/register", json={"email": "ml@x.com", "password": "secretpass1"})
    ds = c.post("/api/datasets/demo/churn").json()
    m = c.post(f"/api/datasets/{ds['id']}/automl", json={"target": "churned"}).json()
    for _ in range(240):
        m = c.get(f"/api/models/{m['id']}").json()
        if m["status"] in ("succeeded", "failed"):
            break
        time.sleep(0.5)
    assert m["status"] == "succeeded", m.get("error")
    schema = m["result"]["input_schema"]
    row = {f["name"]: f.get("median", f.get("mode")) for f in schema}
    p = c.post(f"/api/models/{m['id']}/predict", json={"rows": [row]}).json()["predictions"][0]
    assert 0 <= p["probability"] <= 1 and p["explanation"]["contributions"]
    assert c.get(f"/api/datasets/{ds['id']}/models").json()[0]["summary"]["best_model"] == m["result"]["best_model"]
    other = TestClient(app)
    other.post("/api/auth/register", json={"email": "ml2@x.com", "password": "secretpass1"})
    assert other.get(f"/api/models/{m['id']}").status_code == 404
    assert other.post(f"/api/models/{m['id']}/predict", json={"rows": [row]}).status_code == 404
    assert c.post(f"/api/datasets/{ds['id']}/automl", json={"target": "nope"}).status_code == 422
