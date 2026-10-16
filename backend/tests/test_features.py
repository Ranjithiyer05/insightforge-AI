import time

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from app.main import app
from app.profiler import apply_cleaning, data_handling


def test_fill_missing_methods():
    df = pd.DataFrame({"x": [1.0, None, 3.0, None], "c": ["a", None, "a", "b"]})
    out, log = apply_cleaning(df, [{"op": "fill_missing", "column": "x", "method": "median"}, {"op": "fill_missing", "column": "c", "method": "mode"}])
    assert out["x"].tolist() == [1.0, 2.0, 3.0, 2.0]
    assert out["c"].isna().sum() == 0 and log[0]["cells_filled"] == 2
    out2, _ = apply_cleaning(df, [{"op": "fill_missing", "column": "x", "method": "constant", "value": "0"}])
    assert out2["x"].tolist() == [1.0, 0.0, 3.0, 0.0]


def test_data_handling_counts():
    df = pd.DataFrame({"g": ["a", None, "b"], "v": [1, 2, None], "z": [None, None, None]})
    h = data_handling(df, "comparison", {"group": "g", "value_col": "v"})
    assert h["rows_with_missing"] == 2 and h["missing_by_column"] == {"g": 1, "v": 1}


def _c(email):
    c = TestClient(app)
    assert c.post("/api/auth/register", json={"email": email, "password": "secretpass1", "name": "F"}).status_code in (200, 201)
    return c


def _wait(c, aid):
    for _ in range(120):
        r = c.get(f"/api/analyses/{aid}").json()
        if r["status"] not in ("queued", "running"):
            return r
        time.sleep(1)
    return r


def test_explore_followup_share():
    c = _c("feat@x.com")
    ds = c.post("/api/datasets/demo/churn").json()
    ex = c.get(f"/api/datasets/{ds['id']}/explore").json()
    assert any(col["kind"] == "numeric" and col["histogram"] for col in ex["columns"])
    assert ex["correlation"] and len(ex["correlation"]["matrix"]) == len(ex["correlation"]["columns"])

    an = c.post("/api/analyses/plan", json={"dataset_id": ds["id"], "question": "Which customers are likely to churn?"}).json()
    c.post(f"/api/analyses/{an['id']}/approve")
    res = _wait(c, an["id"])
    assert res["status"] in ("completed", "needs_review")
    assert "data_handling" in res["result"]

    fu = c.post(f"/api/analyses/{an['id']}/followup", json={"question": "Try a different model"}).json()
    assert fu["status"] == "draft" and fu["parent_id"] == an["id"] and fu["plan"]["task_type"] == "classification"
    assert res["result"]["final_strategy"] not in fu["plan"]["strategies"] and fu["plan"]["strategies_locked"]
    c.post(f"/api/analyses/{fu['id']}/approve")
    res2 = _wait(c, fu["id"])
    assert res2["result"]["final_strategy"] != res["result"]["final_strategy"]

    sh = c.post(f"/api/analyses/{an['id']}/share").json()
    anon = TestClient(app)
    pub = anon.get(f"/api/public/share/{sh['token']}")
    assert pub.status_code == 200 and "findings" in pub.json()["result"]
    assert "reproducibility" not in pub.json()["result"] and "tables" not in pub.json()["result"]
    other = _c("feat-other@x.com")
    assert other.post(f"/api/analyses/{an['id']}/share").status_code == 404
    c.delete(f"/api/analyses/{an['id']}/share")
    assert anon.get(f"/api/public/share/{sh['token']}").status_code == 404
