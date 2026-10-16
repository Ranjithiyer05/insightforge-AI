"""Create tables and the synthetic demo datasets. Usage: python scripts/init_db.py"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.db import init_db  # noqa: E402

settings.ensure_dirs()
init_db()
if not (ROOT / "demo_data" / "retail_sales_SYNTHETIC.csv").exists():
    subprocess.run([sys.executable, str(ROOT / "scripts" / "generate_demo_data.py")], check=True)
print(f"Database ready at {settings.database_url}")
