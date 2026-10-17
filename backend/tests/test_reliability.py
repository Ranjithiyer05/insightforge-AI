"""Phase 2 reliability fixes: memory limit vs BLAS, durable dataset files, fast CSV parsing, cascades."""
import shutil

import pandas as pd
from fastapi.testclient import TestClient

from app import storage
from app.config import settings
from app.main import app
from app.sandbox import executor


def _client(email):
    c = TestClient(app)
    assert c.post("/api/auth/register", json={"email": email, "password": "secretpass1"}).status_code == 200
    return c


def test_sklearn_runs_under_render_memory_limit(tmp_path, monkeypatch):
    # Render's free plan sets SANDBOX_MEMORY_MB=384; BLAS-backed models used to fail under RLIMIT_AS.
    monkeypatch.setattr(settings, "sandbox_memory_mb", 384)
    data = tmp_path / "data.csv"
    pd.DataFrame({"a": range(500), "b": [i % 7 for i in range(500)]}).to_csv(data, index=False)
    src = ("import ifrt\nfrom sklearn.cluster import KMeans\ndf = ifrt.load_df()\n"
           "km = KMeans(n_clusters=3, n_init=3, random_state=0).fit(df[['a', 'b']])\nifrt.metric('k', 3)\nifrt.emit()\n")
    r = executor.run_code(src, data, tmp_path / "run")
    assert r.ok, r.error


def test_memory_limit_still_enforced(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "sandbox_memory_mb", 256)
    data = tmp_path / "data.csv"
    pd.DataFrame({"a": [1]}).to_csv(data, index=False)
    r = executor.run_code("import numpy as np\nx = np.ones(200_000_000)\n", data, tmp_path / "run")
    assert not r.ok


def test_semicolon_csv_parses_with_fast_engine():
    raw = b"a;b;c\n1;2;x\n3;4;y\n"
    df = storage.parse_bytes(raw, "csv")
    assert list(df.columns) == ["a", "b", "c"] and len(df) == 2


def test_dataset_file_restored_after_disk_wipe():
    c = _client("restore@x.com")
    ds = c.post("/api/datasets/demo/churn").json()
    shutil.rmtree(settings.uploads_dir / ds["id"])  # simulate a restart on an ephemeral disk
    storage.forget_dataset(ds["id"])
    r = c.get(f"/api/datasets/{ds['id']}/preview?limit=5")
    assert r.status_code == 200 and r.json()["total"] == ds["n_rows"]


def test_missing_file_without_backup_returns_410(monkeypatch):
    c = _client("gone@x.com")
    ds = c.post("/api/datasets/demo/churn").json()
    shutil.rmtree(settings.uploads_dir / ds["id"])
    storage.forget_dataset(ds["id"])
    monkeypatch.setattr(storage, "_restore_blob", lambda *_: False)
    assert c.get(f"/api/datasets/{ds['id']}/preview").status_code == 410


def test_health_reports_storage_mode():
    body = TestClient(app).get("/api/health").json()
    assert body["ok"] and body["storage"]["persistent"] is False  # tests run on SQLite
