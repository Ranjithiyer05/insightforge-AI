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
