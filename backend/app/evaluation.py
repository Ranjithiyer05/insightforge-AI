"""Learning evaluation: does experience memory measurably help?

Compares four agent configurations on the same benchmark of synthetic tasks
whose ground truth is known by construction:

  1. baseline            (no memory)
  2. ordinary_memory     (reuse most similar past success; unvalidated)
  3. validated_memory    (failure-aware, validated lessons)
  4. validated_verified  (validated memory + verifier inside the retry loop)

Protocol: each configuration starts with an empty, isolated memory namespace,
runs the *training* tasks (memory may be written), then the *test* tasks,
which use different random seeds and parameters (unseen datasets). Only test
tasks are scored. Every number in the results is measured from these runs;
improvement is only claimed when a paired bootstrap 95% CI excludes zero.
"""
from __future__ import annotations

import logging
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd
from sqlalchemy import delete

from .agent import MODES, EngineConfig, run_engine
from .config import settings
from .db import EvaluationRun, Lesson, SessionLocal, new_id, utcnow
from .planner import make_plan
from .profiler import profile_dataframe
from .storage import sha256

log = logging.getLogger("insightforge.eval")


# ---------------- benchmark task generators (ground truth known) ----------------

def gen_skewed_small(seed: int, effect: bool) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = int(rng.integers(22, 40))
    a = rng.lognormal(3.0, 1.1, n)
    b = rng.lognormal(3.0 + (0.9 if effect else 0.0), 1.1, n)
    return pd.DataFrame({"variant": ["A"] * n + ["B"] * n, "spend": np.round(np.r_[a, b], 2), "visits": rng.poisson(5, 2 * n)})


def gen_normal_large(seed: int, effect: bool) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = int(rng.integers(300, 500))
    a = rng.normal(50, 10, n)
    b = rng.normal(50 + (2.5 if effect else 0.0), 10, n)
    return pd.DataFrame({"variant": ["A"] * n + ["B"] * n, "score": np.round(np.r_[a, b], 2), "age": rng.integers(18, 70, 2 * n)})


def gen_imbalanced(seed: int, prevalence: float) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = 1500
    X = rng.normal(size=(n, 5))
    plan = rng.choice(["basic", "plus", "pro"], n)
    logit = -3.4 + {0.06: -0.5, 0.08: -0.2, 0.1: 0.0, 0.12: 0.2}.get(prevalence, 0) + 1.3 * X[:, 0] - 1.0 * X[:, 1] + 0.7 * X[:, 2] + np.where(plan == "pro", 0.6, 0)
    y = rng.random(n) < 1 / (1 + np.exp(-logit))
    df = pd.DataFrame(X, columns=["sessions", "days_inactive", "pages", "emails_opened", "tickets"]).round(3)
    df["plan"] = plan
    df["converted"] = np.where(y, "yes", "no")
    return df


def gen_balanced(seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = 1200
    income = rng.normal(55, 15, n)
    debt = rng.normal(20, 8, n)
    score = rng.normal(650, 60, n)
    logit = -0.2 - 0.04 * (income - 55) + 0.09 * (debt - 20) - 0.012 * (score - 650)
    y = (rng.random(n) < 1 / (1 + np.exp(-logit))).astype(int)
    return pd.DataFrame({"income_k": income.round(1), "debt_k": debt.round(1), "credit_score": score.round(), "loan_id": [f"L{i}" for i in range(n)], "defaulted": y})


def gen_seasonal(seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = int(rng.integers(40, 60))
    t = np.arange(n)
    amp = rng.uniform(150, 300)
    y = 1000 + 6 * t + amp * np.sin(2 * np.pi * t / 12) + rng.normal(0, 40, n)
    return pd.DataFrame({"month": pd.date_range("2019-01-01", periods=n, freq="MS").strftime("%Y-%m-%d"), "sales": y.round(2)})


def gen_profit(seed: int, shocked: str) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    products = {"Alpha": (40, 18), "Bravo": (55, 25), "Charlie": (25, 9), "Delta": (80, 41), "Echo": (30, 12)}
    days = pd.date_range("2024-01-01", "2025-03-31", freq="D")
    rows = []
    for day in days:
        last = day >= pd.Timestamp("2025-03-01")
        for p, (price, cost) in products.items():
            k = rng.poisson(6)
            c = cost * (1.35 if (last and p == shocked) else 1.0)
            for _ in range(k):
                q = int(rng.integers(1, 4))
                disc = max(0.0, rng.normal(0.05, 0.02))
                rows.append((day.date().isoformat(), p, q, price, round(disc * 100, 1), round(price * q * (1 - disc), 2), round(c * q * rng.normal(1, 0.01), 2)))
    return pd.DataFrame(rows, columns=["date", "product", "quantity", "unit_price", "discount_pct", "revenue", "cost"])


@dataclass
class Task:
    id: str
    family: str
    question: str
    df: pd.DataFrame
    expected_task: str
    truth: dict[str, Any]
    grade: Callable[[dict[str, Any], dict[str, Any]], tuple[bool, bool]]  # (correct, valid)


def _sig(out) -> bool | None:
    m = out.get("metrics", {}).get("significant")
    return m.get("value") if m else None


def _mv(out, k):
    m = out.get("metrics", {}).get(k)
    return m.get("value") if m else None


def build_tasks(split: str, n_seeds: int) -> list[Task]:
    base = 1000 if split == "train" else 5000
    tasks: list[Task] = []
    for i in range(n_seeds):
        s = base + i * 17
        eff = (i % 2 == 0)
        tasks.append(Task(f"{split}-skewed-{i}", "Skewed small-sample comparison", "Is there a significant difference in spend between variants?",
                          gen_skewed_small(s, eff), "hypothesis_test", {"effect": eff},
                          lambda o, st, eff=eff: (_sig(o) == eff, st.get("final_strategy") in ("mann_whitney", "permutation"))))
        eff2 = (i % 2 == 1)
        tasks.append(Task(f"{split}-normal-{i}", "Large normal-sample comparison", "Is there a significant difference in score between variants?",
                          gen_normal_large(s + 1, eff2), "hypothesis_test", {"effect": eff2},
                          lambda o, st, eff=eff2: (_sig(o) == eff, st.get("final_strategy") in ("welch_t", "mann_whitney", "permutation"))))
        prev = [0.08, 0.1, 0.06, 0.12][i % 4]
        tasks.append(Task(f"{split}-imbalanced-{i}", "Imbalanced classification", "Which users are likely to convert?",
                          gen_imbalanced(s + 2, prev), "classification", {"prevalence": prev},
                          lambda o, st: ((_mv(o, "balanced_accuracy") or 0) >= 0.65, (_mv(o, "recall") or 0) >= 0.3)))
        tasks.append(Task(f"{split}-balanced-{i}", "Balanced classification", "Which loans are likely to default?",
                          gen_balanced(s + 3), "classification", {},
                          lambda o, st: ((_mv(o, "balanced_accuracy") or 0) >= 0.6, "loan_id" not in (_mv(o, "features_used") or []))))
        tasks.append(Task(f"{split}-seasonal-{i}", "Seasonal forecasting", "Forecast sales for the next 6 months",
                          gen_seasonal(s + 4), "forecasting", {},
                          lambda o, st: ((_mv(o, "skill_vs_best_baseline") or -1) > 0, _mv(o, "holdout_periods") is not None)))
        shocked = ["Bravo", "Delta", "Alpha", "Echo"][i % 4]
        tasks.append(Task(f"{split}-profit-{i}", "Profit decline diagnosis", "Why did profit decline last month and which products should we investigate?",
                          gen_profit(s + 5, shocked), "profit_change", {"shocked": shocked},
                          lambda o, st, sh=shocked: ((o.get("artifacts", {}).get("ranked_products") or [{}])[0].get("product") == sh,
                                                     abs(_mv(o, "decomposition_max_residual") or 1) < 1e-6)))
    return tasks


class ListRecorder:
    def __init__(self):
        self.steps: list[dict[str, Any]] = []

    def start(self, key, title, kind, **kw):
        st = {"key": key, "title": title, "kind": kind, "attempt": kw.get("attempt", 1)}
        self.steps.append(st)
        return st

    def finish(self, st, status, **kw):
        st["status"] = status
        st["error"] = kw.get("error")

    def experiment(self, data):
        return new_id("evx")


def _boot_ci(diffs: list[float], seed: int = 0) -> tuple[float, float, float]:
    d = np.asarray(diffs, dtype=float)
    if len(d) == 0:
        return 0.0, 0.0, 0.0
    rng = np.random.default_rng(seed)
    bs = [rng.choice(d, len(d)).mean() for _ in range(4000)]
    return float(d.mean()), float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))


def run_evaluation(run_id: str, n_train: int = 2, n_test: int = 2, modes: list[str] | None = None, progress: Callable[[str], None] | None = None) -> dict[str, Any]:
    modes = modes or list(MODES)
    train, test = build_tasks("train", n_train), build_tasks("test", n_test)
    root = settings.runs_dir / f"eval_{run_id}"
    root.mkdir(parents=True, exist_ok=True)
    per_mode: dict[str, list[dict[str, Any]]] = {}
    lesson_snapshots: dict[str, list[dict[str, Any]]] = {}
    for mode in modes:
        ns = f"eval_{run_id}_{mode}"
        db = SessionLocal()
        history_failures: set[tuple] = set()
        rows: list[dict[str, Any]] = []
        try:
            for phase, tasks in (("train", train), ("test", test)):
                for t in tasks:
                    if progress:
                        progress(f"{MODES[mode]['label']}: {phase} task {t.id}")
                    path = root / f"{t.id}.csv"
                    if not path.exists():
                        t.df.to_csv(path, index=False)
                    raw = path.read_bytes()
                    df = pd.read_csv(path)
                    prof = profile_dataframe(df)
                    plan = make_plan(t.question, prof)
                    t0 = time.perf_counter()
                    rec = ListRecorder()
                    try:
                        out = run_engine(df=df, data_path=path, dataset_sha=sha256(raw), profile=prof, plan=plan,
                                         cfg=EngineConfig(mode=mode, namespace=ns, retry_budget=settings.retry_budget, use_llm=False),
                                         recorder=rec, db=db, run_root=root / mode / t.id)
                        db.commit()
                    except Exception as exc:
                        db.rollback()
                        log.warning("eval task %s failed: %s", t.id, exc)
                        rows.append({"task": t.id, "family": t.family, "phase": phase, "completed": False, "error": str(exc)[:200]})
                        continue
                    repeated = 0
                    for a in out.attempts:
                        key = (plan["task_type"], a["strategy"], tuple(sorted(a["conditions"].items())))
                        bad = a["status"] != "succeeded"
                        if bad and key in history_failures:
                            repeated += 1
                        if bad:
                            history_failures.add(key)
                    correct, valid = (False, False)
                    if out.status != "failed":
                        correct, valid = t.grade(out.result, {"final_strategy": out.final_strategy})
                    rows.append({
                        "task": t.id, "family": t.family, "phase": phase, "planned_task": plan["task_type"], "plan_correct": plan["task_type"] == t.expected_task,
                        "completed": out.status != "failed", "status": out.status, "correct": bool(correct), "valid": bool(valid),
                        "attempts": len(out.attempts), "strategies": [a["strategy"] for a in out.attempts], "final_strategy": out.final_strategy,
                        "repeated_failures": repeated, "needs_human": out.human_review_needed, "seconds": round(time.perf_counter() - t0, 2),
                        "sandbox_cpu_s": round(out.cpu_s, 2), "llm_tokens": sum((u.get("input_tokens") or 0) + (u.get("output_tokens") or 0) for u in out.llm_usage),
                        "lessons_applied": len(out.lessons_used),
                    })
            lesson_snapshots[mode] = [{"strategy": l.strategy, "outcome": l.outcome, "status": l.status, "conditions": l.conditions,
                                       "support": l.support_count, "confidence": l.confidence, "statement": l.statement}
                                      for l in db.query(Lesson).filter(Lesson.namespace == ns).all()]
        finally:
            db.execute(delete(Lesson).where(Lesson.namespace == ns))
            db.commit()
            db.close()
        per_mode[mode] = rows
    return summarize(per_mode, lesson_snapshots, n_train, n_test)


def summarize(per_mode: dict[str, list[dict[str, Any]]], lessons: dict[str, Any], n_train: int, n_test: int) -> dict[str, Any]:
    summary = {}
    for mode, rows in per_mode.items():
        t = [r for r in rows if r["phase"] == "test"]
        n = len(t) or 1
        summary[mode] = {
            "label": MODES[mode]["label"], "n_test_tasks": len(t),
            "task_completion": sum(r["completed"] for r in t) / n,
            "correctness": sum(r.get("correct", False) for r in t) / n,
            "statistical_validity": sum(r.get("valid", False) for r in t) / n,
            "mean_attempts": float(np.mean([r.get("attempts", 0) for r in t])) if t else 0,
            "repeated_failures": int(sum(r.get("repeated_failures", 0) for r in t)),
            "human_interventions": int(sum(r.get("needs_human", False) for r in t)),
            "mean_seconds": float(np.mean([r.get("seconds", 0) for r in t])) if t else 0,
            "sandbox_cpu_s": float(sum(r.get("sandbox_cpu_s", 0) for r in t)),
            "llm_tokens": int(sum(r.get("llm_tokens", 0) for r in t)),
            "plan_accuracy": sum(r.get("plan_correct", False) for r in t) / n,
        }
    comparisons = []
    base = {r["task"]: r for r in per_mode.get("baseline", []) if r["phase"] == "test"}
    for mode, rows in per_mode.items():
        if mode == "baseline" or not base:
            continue
        for metric, better in (("correct", "higher"), ("valid", "higher"), ("attempts", "lower"), ("repeated_failures", "lower")):
            diffs = [float(r.get(metric, 0)) - float(base[r["task"]].get(metric, 0)) for r in rows if r["phase"] == "test" and r["task"] in base]
            mean, lo, hi = _boot_ci(diffs)
            improved = (lo > 0) if better == "higher" else (hi < 0)
            worse = (hi < 0) if better == "higher" else (lo > 0)
            comparisons.append({"mode": mode, "metric": metric, "better": better, "mean_diff_vs_baseline": mean, "ci95": [lo, hi], "n": len(diffs),
                                "verdict": "improved" if improved else "worse" if worse else "no significant difference"})
    claims = [c for c in comparisons if c["verdict"] == "improved"]
    return {
        "protocol": {"train_seeds_per_family": n_train, "test_seeds_per_family": n_test, "families": sorted({r["family"] for rows in per_mode.values() for r in rows}),
                     "note": "Test tasks use unseen random seeds and parameters. Memory is isolated per configuration and cleared after the run."},
        "summary": summary, "comparisons": comparisons, "per_task": per_mode, "lessons_learned": lessons,
        "conclusion": ("Measured improvements (95% bootstrap CI excludes zero): " + "; ".join(f"{MODES[c['mode']]['label']} on {c['metric']} ({c['mean_diff_vs_baseline']:+.2f})" for c in claims))
        if claims else "No configuration showed a statistically supported improvement over the baseline in this run.",
    }


def execute_evaluation(run_id: str) -> None:
    db = SessionLocal()
    try:
        run = db.get(EvaluationRun, run_id)
        run.status = "running"
        db.commit()
        cfg = run.config

        def progress(msg: str):
            run.results = {**(run.results or {}), "progress": msg}
            db.commit()
        results = run_evaluation(run_id, cfg.get("n_train", 2), cfg.get("n_test", 2), cfg.get("modes"), progress)
        run.results = results
        run.status = "completed"
        run.finished_at = utcnow()
        db.commit()
    except Exception as exc:
        log.error("evaluation crashed: %s", traceback.format_exc(limit=4))
        db.rollback()
        run = db.get(EvaluationRun, run_id)
        run.status, run.error, run.finished_at = "failed", f"{type(exc).__name__}: {str(exc)[:300]}", utcnow()
        db.commit()
    finally:
        db.close()


_ = Path
