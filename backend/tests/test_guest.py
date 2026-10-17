from datetime import timedelta

from fastapi.testclient import TestClient

from app.db import SessionLocal, User, utcnow
from app.main import app, purge_guests


def test_guest_demo_and_purge():
    c = TestClient(app)
    r = c.post("/api/auth/guest")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["is_guest"] and not body["is_admin"]
    assert c.get(f"/api/datasets/{body['dataset_id']}").status_code == 200
    db = SessionLocal()
    u = db.get(User, body["id"])
    u.created_at = utcnow() - timedelta(days=3)
    db.commit()
    assert purge_guests(db) >= 1
    assert db.get(User, body["id"]) is None
    db.close()


def test_guest_limit_is_per_visitor_not_global():
    from fastapi.testclient import TestClient
    from app.main import app
    for i in range(6):
        r = TestClient(app).post("/api/auth/guest", headers={"x-forwarded-for": f"10.9.0.{i}"})
        assert r.status_code == 200, r.text
    same = [TestClient(app).post("/api/auth/guest", headers={"x-forwarded-for": "10.9.9.9"}).status_code for _ in range(6)]
    assert same[:5] == [200] * 5 and same[5] == 429


def test_overview_activity_is_real():
    c = TestClient(app, headers={"x-forwarded-for": "10.9.8.7"})
    assert c.post("/api/auth/guest").status_code == 200
    o = c.get("/api/overview").json()
    assert len(o["series"]) == 90
    today = o["series"][-1]
    assert today["datasets"] >= 1 and sum(r["datasets"] for r in o["series"]) == o["counts"]["datasets"]
    w = o["windows"]["7"]["datasets"]
    assert w["current"] == o["counts"]["datasets"] and w["previous"] == 0 and w["change_pct"] is None
