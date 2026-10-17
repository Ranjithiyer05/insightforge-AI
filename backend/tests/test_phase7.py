import time

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.automl import AutoMLError, run_scenario, train
from app.compare import compare
from app.main import app
from app.profiler import profile_dataframe


def reg_frame(n=500, seed=0):
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({"price": rng.uniform(10, 50, n), "ads": rng.uniform(0, 10, n), "region": rng.choice(["N", "S"], n)})
    df["sales"] = 200 - 3 * df["price"] + 5 * df["ads"] + (df["region"] == "N") * 10 + rng.normal(scale=2, size=n)
    return df


def test_scenario_on_linear_effect():
    df = reg_frame()
    r, blob = train(df, profile_dataframe(df), "sales")
    s = run_scenario(blob, df, [{"feature": "ads", "op": "add", "value": 1}])
    # model learned roughly +5 sales per ad unit; scenario must recover that, with the interval covering the estimate
    assert 3 < s["difference"] < 7 and s["ci95"][0] <= s["difference"] <= s["ci95"][1]
    assert s["rows"] == len(df) and "not a causal" in s["caveat"]
    f = run_scenario(blob, df, [{"feature": "region", "op": "set", "value": "N"}], filters=[{"column": "region", "op": "==", "value": "S"}])
    assert f["rows"] == int((df.region == "S").sum()) and f["difference"] > 5
    far = run_scenario(blob, df, [{"feature": "price", "op": "multiply", "value": 3}])
    assert far["warnings"]  # extrapolation flagged
    with pytest.raises(AutoMLError):
        run_scenario(blob, df, [{"feature": "region", "op": "set", "value": "Mars"}])
    with pytest.raises(AutoMLError):
        run_scenario(blob, df, [{"feature": "nope", "op": "set", "value": 1}])


def test_compare_detects_shift_and_schema_changes():
    a = reg_frame(seed=1)
    b = reg_frame(seed=2)
    b["price"] = b["price"] + 15
    b["region"] = np.where(np.arange(len(b)) % 5 == 0, "W", b["region"])
    b = b.drop(columns="ads").assign(extra=1)
    r = compare(a, b, "jan", "feb")
    cols = {c["column"]: c for c in r["columns"]}
    assert r["added_columns"] == ["extra"] and r["removed_columns"] == ["ads"]
    assert cols["price"]["verdict"] == "large shift" and "W" in cols["region"]["new_categories"]
    same = compare(a, reg_frame(seed=3), "x", "y")
    assert all(c["verdict"] == "stable" for c in same["columns"] if "verdict" in c)


def test_reports_and_compare_api():
    c = TestClient(app)
    c.post("/api/auth/register", json={"email": "p7@x.com", "password": "secretpass1"})
    d1 = c.post("/api/datasets/demo/retail").json()
    d2 = c.post("/api/datasets/demo/churn").json()
    q = c.post(f"/api/datasets/{d1['id']}/ask", json={"question": "total revenue by region"}).json()
    c.post(f"/api/ask/{q['id']}/pin")
    h = c.get(f"/api/datasets/{d1['id']}/report?format=html")
    assert h.status_code == 200 and "<svg" in h.text and "total revenue by region" in h.text and "<script" not in h.text
    p = c.get(f"/api/datasets/{d1['id']}/report?format=pdf")
    assert p.status_code == 200 and p.content[:4] == b"%PDF"
    cmp = c.get(f"/api/compare/datasets?a={d1['id']}&b={d2['id']}").json()
    assert "region" in [x["column"] for x in cmp["columns"]] and cmp["removed_columns"]
    other = TestClient(app)
    other.post("/api/auth/register", json={"email": "p7b@x.com", "password": "secretpass1"})
    assert other.get(f"/api/datasets/{d1['id']}/report").status_code == 404
    assert other.get(f"/api/compare/datasets?a={d1['id']}&b={d2['id']}").status_code == 404
