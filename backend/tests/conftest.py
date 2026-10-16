import os
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="ifg-test-")
os.environ["INSIGHTFORGE_DATA_DIR"] = _tmp
os.environ.setdefault("LLM_PROVIDER", "none")
os.environ.pop("DATABASE_URL", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402

init_db()


@pytest.fixture
def db():
    s = SessionLocal()
    try:
        yield s
    finally:
        s.rollback()
        s.close()
