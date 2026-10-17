import io
import subprocess
import sys
import zipfile

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import patterns as pt
from app.main import app
from app.profiler import profile_dataframe


def ts(n=400, seed=0):
    rng = np.random.default_rng(seed)
    days = pd.date_range("2023-01-01", periods=n, freq="D")
    y = 100 + 0.2 * np.arange(n) + 10 * np.sin(np.arange(n) / 30 * 2 * np.pi) + rng.normal(scale=2, size=n)
    df = pd.DataFrame({"day": days.astype(str), "sales": y, "units": rng.poisson(20, n)})
    return df


def test_anomalies_find_planted_outliers():
    df = ts()
    df.loc[[50, 220], "sales"] = [900, -500]
    r = pt.anomalies(df, profile_dataframe(df), contamination=0.01)
    rows = {t["row"] for t in r["top"]}
    assert {51, 221} <= rows and any("sales" in w for t in r["top"] for w in t["why"])
    assert any(h["period"] == "2023-02-20" for h in r["periods"]["hits"])


def test_forecast_beats_naive_on_trend_and_admits_noise():
    df = ts(800)
    r = pt.forecast(df, profile_dataframe(df), "day", "sales", "month")
    assert r["beats_naive"] and r["best_model"] != "naive" and any("forecast" in p for p in r["series"])
    noise = pd.DataFrame({"day": pd.date_range("2023-01-01", periods=36, freq="MS").astype(str), "v": np.random.default_rng(3).normal(size=36)})
    r2 = pt.forecast(noise, profile_dataframe(noise), "day", "v", "month")
    assert len(r2["models"]) == 4 and (r2["beats_naive"] or r2["notes"])
    with pytest.raises(pt.PatternError):
        pt.forecast(noise.head(5), profile_dataframe(noise.head(5)), "day", "v", "month")


def test_segments_find_clear_groups_and_flag_weak_ones():
    rng = np.random.default_rng(1)
    a = rng.normal([0, 0], 0.3, size=(200, 2))
    b = rng.normal([5, 5], 0.3, size=(200, 2))
    df = pd.DataFrame(np.vstack([a, b]), columns=["x", "y"]).assign(z=rng.normal(size=400))
    r = pt.segments(df, profile_dataframe(df), ["x", "y"])
    assert r["k"] == 2 and r["strength"] == "clear"
    blob = pd.DataFrame(rng.normal(size=(400, 3)), columns=["p", "q", "r"])
    assert pt.segments(blob, profile_dataframe(blob))["strength"] == "weak"


def test_dashboard_versions_monitoring_pipeline_and_reproduce(tmp_path):
    c = TestClient(app)
    c.post("/api/auth/register", json={"email": "p8@x.com", "password": "secretpass1"})
    df = pd.DataFrame({"region": ["N", "S", "N", "S"] * 10, "sales": [10.0] * 40, "city": [" pune", "Pune"] * 20})
    up = c.post("/api/datasets/upload", files={"file": ("m1.csv", df.to_csv(index=False), "text/csv")}).json()
    q = c.post(f"/api/datasets/{up['id']}/ask", json={"question": "total sales"}).json()
    board = c.post("/api/dashboards", json={"name": "Sales", "dataset_id": up["id"], "tiles": [
        {"kind": "kpi", "title": "Total sales", "question": "total sales", "spec": q["spec"], "rule": {"op": "change_pct_below", "threshold": -10}},
        {"kind": "ask", "title": "By region", "spec": {**q["spec"], "group_by": "region"}}]}).json()
    r1 = c.get(f"/api/dashboards/{board['id']}").json()
    assert r1["tiles"][0]["value"] == 400 and r1["tiles"][0]["monitor"]["status"] == "ok"
    assert c.get("/api/alerts").json() == []  # no data change, no alert
    df2 = df.assign(sales=5.0)
    v2 = c.post(f"/api/datasets/{up['id']}/versions", files={"file": ("m2.csv", df2.to_csv(index=False), "text/csv")}).json()
    assert v2["name"].endswith("(version 2)")
    r2 = c.get(f"/api/dashboards/{board['id']}").json()
    assert r2["dataset"]["id"] == v2["id"] and r2["tiles"][0]["value"] == 200 and r2["tiles"][0]["monitor"]["status"] == "breach"
    alerts = c.get("/api/alerts").json()
    assert len(alerts) == 1 and "-50.0%" in alerts[0]["message"]
    c.get(f"/api/dashboards/{board['id']}")
    assert len(c.get("/api/alerts").json()) == 1  # re-rendering does not duplicate alerts
    # clean v2, then reproduce from the bundle
    ops = [{"op": "normalize_text", "column": "city", "case": "title", "reason": "spacing"}, {"op": "drop_duplicates"}]
    cl = c.post(f"/api/datasets/{v2['id']}/clean", json={"operations": ops, "confirm": True}).json()
    pipe = c.get(f"/api/datasets/{cl['id']}/pipeline").json()
    kinds = [n.get("kind") for n in pipe["nodes"] if n["type"] == "dataset"]
    assert kinds == ["upload", "new_data", "cleaned"] and {"dashboard", "question"} <= {n["type"] for n in pipe["nodes"]}
    z = zipfile.ZipFile(io.BytesIO(c.get(f"/api/datasets/{cl['id']}/reproduce.zip").content))
    z.extractall(tmp_path)
    df2.to_csv(tmp_path / "orig.csv", index=False)
    out = subprocess.run([sys.executable, "replay.py", "orig.csv", "out.csv"], cwd=tmp_path, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    rebuilt = pd.read_csv(tmp_path / "out.csv")
    assert len(rebuilt) == cl["n_rows"] and set(rebuilt["city"]) == {"Pune"}
    other = TestClient(app)
    other.post("/api/auth/register", json={"email": "p8b@x.com", "password": "secretpass1"})
    assert other.get(f"/api/dashboards/{board['id']}").status_code == 404
    assert other.post(f"/api/datasets/{up['id']}/versions", files={"file": ("x.csv", "a\n1\n", "text/csv")}).status_code == 404
    assert other.get(f"/api/datasets/{up['id']}/patterns/anomalies").status_code == 404
