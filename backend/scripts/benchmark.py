"""Time and peak memory of the main operations, each in a fresh process.

Usage: python scripts/benchmark.py [rows]   (default: the retail demo, plus a synthetic file of `rows` rows)
Writes a Markdown table to stdout. Run from backend/.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import resource
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def synthetic(n: int):
    import numpy as np
    import pandas as pd
    rng = np.random.default_rng(0)
    df = pd.DataFrame({
        "order_date": pd.to_datetime("2023-01-01") + pd.to_timedelta(rng.integers(0, 730, n), unit="D"),
        "region": rng.choice(["North", "South", "East", "West"], n), "channel": rng.choice(["Online", "Store"], n),
        "quantity": rng.integers(1, 6, n), "unit_price": rng.gamma(3, 20, n).round(2), "discount_pct": rng.choice([0, 5, 10, 20], n),
    })
    df["revenue"] = (df.quantity * df.unit_price * (1 - df.discount_pct / 100)).round(2)
    df["returned"] = (rng.random(n) < 0.05 + 0.1 * (df.discount_pct > 10)).astype(int)
    df["order_date"] = df["order_date"].dt.strftime("%Y-%m-%d")
    return df


def task(name: str, src: str, rows: int, q):
    import pandas as pd
    from app.profiler import profile_dataframe
    df = pd.read_csv("demo_data/retail_sales_SYNTHETIC.csv") if src == "retail" else synthetic(rows)
    prof = profile_dataframe(df) if name != "profile" else None
    t = time.perf_counter()
    if name == "profile":
        profile_dataframe(df)
    elif name == "eda":
        from app.eda import run_eda
        run_eda(df, prof)
    elif name == "ask":
        from app.ask import answer
        for qq in ("total revenue by region", "revenue by month", "average revenue in North", "correlation between unit_price and revenue"):
            answer(df, prof, qq)
    elif name == "automl":
        from app.automl import train
        target = "returned" if "returned" in df else "revenue"
        train(df, prof, target, max_rows=20_000)
    elif name == "anomalies":
        from app.patterns import anomalies
        anomalies(df, prof)
    elif name == "forecast":
        from app.patterns import forecast
        forecast(df, prof)
    elif name == "segments":
        from app.patterns import segments
        segments(df, prof)
    q.put({"seconds": round(time.perf_counter() - t, 2), "peak_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)})


def main():
    rows = int(sys.argv[1]) if len(sys.argv) > 1 else 100_000
    out = []
    for src in ("retail", "synthetic"):
        for name in ("profile", "eda", "ask", "anomalies", "forecast", "segments", "automl"):
            q = mp.Queue()
            p = mp.Process(target=task, args=(name, src, rows, q))
            p.start()
            p.join()
            res = q.get() if p.exitcode == 0 else {"seconds": None, "peak_mb": None, "error": p.exitcode}
            out.append({"data": "retail demo (19,560 rows)" if src == "retail" else f"synthetic ({rows:,} rows)", "operation": name, **res})
            print(json.dumps(out[-1]), file=sys.stderr)
    print("| Data | Operation | Seconds | Peak memory (MB) |\n|---|---|---|---|")
    for r in out:
        print(f"| {r['data']} | {r['operation']} | {r['seconds']} | {r['peak_mb']} |")


if __name__ == "__main__":
    main()
