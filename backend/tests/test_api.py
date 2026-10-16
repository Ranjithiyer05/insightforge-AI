import time

from fastapi.testclient import TestClient

from app.main import app


def _client(email):
    c = TestClient(app)
    r = c.post("/api/auth/register", json={"email": email, "password": "secretpass1", "name": email[0]})
    assert r.status_code in (200, 201), r.text
    return c


def test_isolation_and_admin():
    a = _client("iso-a@x.com")
    b = _client("iso-b@x.com")
    ds = a.post("/api/datasets/demo/churn").json()
    assert b.get(f"/api/datasets/{ds['id']}").status_code == 404
    me_b = b.get("/api/auth/me").json()
    if not me_b["is_admin"]:
        assert b.get("/api/admin/users").status_code == 403
    assert TestClient(app).get("/api/datasets").status_code == 401


def test_retail_demo_end_to_end():
    c = _client("e2e@x.com")
    ds = c.post("/api/datasets/demo/retail").json()
    an = c.post("/api/analyses/plan", json={"dataset_id": ds["id"], "question": "Why did profit decline last month?"}).json()
    assert an["plan"]["task_type"] == "profit_change"
    assert c.post(f"/api/analyses/{an['id']}/approve").status_code == 200
    for _ in range(120):
        res = c.get(f"/api/analyses/{an['id']}").json()
        if res["status"] not in ("queued", "running"):
            break
        time.sleep(1)
    assert res["status"] == "completed", res.get("error")
    assert res["verification"] == "passed"
    assert c.get(f"/api/analyses/{an['id']}/report.pdf").content[:4] == b"%PDF"
