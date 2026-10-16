"""Agent orchestration: plan -> execute -> assess -> verify -> retry -> learn -> report.

The engine is independent of storage: it reports progress through a
`Recorder`, so the same code runs user analyses (persisted step by step) and
the learning evaluation (kept in memory).

Agent modes (used by the learning evaluation and selectable in Settings):
  baseline            no experience memory, no verifier in the loop
  ordinary_memory     reuses the most similar past *successful* strategy (unvalidated)
  validated_memory    failure-aware, validated lessons; verifier only used to validate lessons
  validated_verified  validated memory + independent verification inside the retry loop
"""
from __future__ import annotations

import logging
import platform
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import pandas as pd
from sqlalchemy.orm import Session

from . import llm, memory
from .analyses import Assessment, get_method
from .config import settings
from .db import Analysis, Experiment, SessionLocal, Step, utcnow
from .profiler import dataset_signature
from .sandbox.executor import CodeValidationError, netns_available, run_code
from .verifier import Verifier, check_narrative

log = logging.getLogger("insightforge.agent")

MODES = {
    "baseline": {"read": None, "write": False, "verify_loop": False, "verify_lessons": False, "label": "Baseline (no memory)"},
    "ordinary_memory": {"read": "ordinary", "write": True, "verify_loop": False, "verify_lessons": False, "label": "Ordinary experience retrieval"},
    "validated_memory": {"read": "validated", "write": True, "verify_loop": False, "verify_lessons": True, "label": "Failure-aware validated memory"},
    "validated_verified": {"read": "validated", "write": True, "verify_loop": True, "verify_lessons": True, "label": "Validated memory + independent verification"},
}


class Recorder(Protocol):
    def start(self, key: str, title: str, kind: str, *, code: str = "", rationale: str = "", inputs: dict | None = None,
              attempt: int = 1) -> Any: ...
    def finish(self, handle: Any, status: str, *, outputs: dict | None = None, error: str | None = None, stdout: str = "",
               stderr: str = "", duration_ms: int | None = None, cpu_s: float | None = None) -> None: ...
    def experiment(self, data: dict[str, Any]) -> str: ...


@dataclass
class EngineConfig:
    mode: str = "validated_verified"
    namespace: str = "default"
    retry_budget: int = 2
    use_llm: bool = True


@dataclass
class EngineOutcome:
    status: str
    result: dict[str, Any] = field(default_factory=dict)
    report: dict[str, Any] = field(default_factory=dict)
    attempts: list[dict[str, Any]] = field(default_factory=list)
    verification: dict[str, Any] | None = None
    final_strategy: str | None = None
    lessons_used: list[dict[str, Any]] = field(default_factory=list)
    cpu_s: float = 0.0
    duration_ms: int = 0
    llm_usage: list[dict[str, Any]] = field(default_factory=list)
    human_review_needed: bool = False


def _empty_result() -> dict[str, Any]:
    return {"tables": {}, "charts": [], "metrics": {}, "claims": [], "notes": [], "warnings": [], "artifacts": {}}


def _merge(into: dict[str, Any], part: dict[str, Any]) -> None:
    for k in ("tables", "metrics", "artifacts"):
        into[k].update(part.get(k, {}))
    for k in ("charts", "claims", "notes", "warnings"):
        into[k] += part.get(k, [])


def _summary_outputs(res: dict[str, Any]) -> dict[str, Any]:
    return {
        "metrics": {k: v for k, v in list(res.get("metrics", {}).items())[:40]},
        "tables": {k: {"columns": v["columns"], "rows": v["rows"][:25], "total_rows": len(v["rows"])} for k, v in res.get("tables", {}).items()},
        "charts": [c["id"] for c in res.get("charts", [])],
        "claims": res.get("claims", []),
        "warnings": res.get("warnings", []),
        "notes": res.get("notes", []),
    }


def run_engine(*, df: pd.DataFrame, data_path: Path, dataset_sha: str, profile: dict[str, Any], plan: dict[str, Any], cfg: EngineConfig,
               recorder: Recorder, db: Session, run_root: Path, analysis_id: str | None = None) -> EngineOutcome:
    t_start = time.perf_counter()
    mode = MODES[cfg.mode]
    task = plan["task_type"]
    params = dict(plan["params"])
    method = get_method(task)
    out = EngineOutcome(status="failed")

    # 1. Profile check on the selected columns
    h = recorder.start("profile", "Inspect dataset and data quality", "profile", rationale="Re-check data quality for the columns this plan uses.")
    cols = [c for c in plan.get("required_columns", []) if c in df.columns]
    issues = [i for i in profile.get("issues", []) if i.get("column") in cols or i.get("column") is None]
    recorder.finish(h, "completed", outputs={"rows": int(len(df)), "columns_used": cols, "issues": issues,
                                             "missing_in_used_columns": {c: int(df[c].isna().sum()) for c in cols}})

    # 2. Memory retrieval
    conditions = method.conditions(df, profile, params)
    target = params.get("target") or params.get("outcome")
    signature = dataset_signature(profile, target, df)
    strategies = list(plan["strategies"])
    h = recorder.start("memory", "Retrieve relevant past experience", "memory", inputs={"conditions": conditions, "signature": signature, "mode": cfg.mode})
    retrieved: list[dict[str, Any]] = []
    notes: list[str] = []
    if mode["read"]:
        retrieved = memory.retrieve(db, namespace=cfg.namespace, task_type=task, conditions=conditions, signature=signature, mode=mode["read"])
        if not plan.get("strategies_locked"):
            strategies, notes = memory.rank_strategies(strategies, retrieved, mode["read"])
        else:
            notes = ["Strategy order was set by the user; lessons are shown but not applied."]
        memory.log_usage(db, retrieved, analysis_id, "; ".join(notes) or "retrieved, no change to plan")
    out.lessons_used = [{**memory.lesson_dict(r["lesson"]), "similarity": r["similarity"], "score": r["score"]} for r in retrieved]
    recorder.finish(h, "completed", outputs={
        "mode": mode["label"], "lessons": out.lessons_used, "strategy_order": strategies,
        "effect": notes or (["Memory disabled for this agent mode."] if not mode["read"] else ["No sufficiently similar validated lessons found; using the default order."])})

    # 3. Execute with justified retries
    tried: list[str] = []
    strategy = strategies[0]
    best: dict[str, Any] | None = None
    attempt = 0
    while strategy:
        attempt += 1
        tried.append(strategy)
        result = _empty_result()
        error = None
        a_cpu, a_ms = 0.0, 0
        stage_params = {**params}
        for stage in method.stages(stage_params, strategy):
            sh = recorder.start(stage.key, stage.title, stage.kind, code=stage.code, rationale=stage.rationale,
                                inputs={"strategy": strategy, "params": stage_params}, attempt=attempt)
            try:
                ex = run_code(stage.code, data_path, run_root / f"a{attempt}_{stage.key}")
            except CodeValidationError as exc:
                recorder.finish(sh, "failed", error=f"Code validation rejected the script: {exc}")
                error = str(exc)
                break
            a_cpu += ex.cpu_s
            a_ms += ex.duration_ms
            if not ex.ok:
                recorder.finish(sh, "failed", error=ex.error, stdout=ex.stdout, stderr=ex.stderr, duration_ms=ex.duration_ms, cpu_s=ex.cpu_s,
                                outputs={"isolation": ex.isolation})
                error = ex.error
                break
            _merge(result, ex.result)
            recorder.finish(sh, "completed", outputs={**_summary_outputs(ex.result), "isolation": ex.isolation}, stdout=ex.stdout,
                            stderr=ex.stderr, duration_ms=ex.duration_ms, cpu_s=ex.cpu_s)
        out.cpu_s += a_cpu
        assessment = Assessment("failed", error, "model_error" if task in ("classification", "regression", "forecasting", "segmentation") else "test_error") \
            if error else method.assess(result, params, strategy)

        verification = None
        findings: list[dict[str, Any]] = []
        if not error:
            F, _, _ = method.findings(result, {**params, "strategy": strategy})
            findings = [f.to_dict() for f in F]
        if not error and (mode["verify_loop"] or mode["verify_lessons"]):
            vh = recorder.start("verify", "Independently verify results", "verify", attempt=attempt,
                                rationale="Recompute claims from raw data, check assumptions, leakage and evidence links.")
            try:
                verification = Verifier(df, {**params, "strategy": strategy}, profile).verify(task, result, findings)
                vstat = {"passed": "completed", "needs_review": "needs_review", "failed": "failed"}[verification["status"]]
                recorder.finish(vh, vstat, outputs=verification)
            except Exception as exc:
                verification = {"status": "needs_review", "checks": [{"id": "verifier", "status": "warn", "category": "verifier", "message": f"Verifier error: {exc}"}],
                                "reason_codes": [], "counts": {}, "verified_claims": {}}
                recorder.finish(vh, "needs_review", error=f"Verifier error: {exc}")

        v_ok = verification is None or verification["status"] == "passed"
        numeric_ok = verification is not None and not any(c["category"] == "numeric" and c["status"] == "fail" for c in verification["checks"])
        exp_status = assessment.status
        reason = assessment.reason_code
        diagnosis = assessment.diagnosis
        if exp_status == "succeeded" and verification is not None and not v_ok:
            exp_status = "invalid" if verification["status"] == "failed" or verification["reason_codes"] else "weak"
            reason = (verification["reason_codes"] or [reason])[0]
            fails = [c["message"] for c in verification["checks"] if c["status"] in ("fail",) or c.get("blocking")]
            diagnosis = "Verification: " + " ".join(fails[:2])
        exp = {"attempt": attempt, "strategy": strategy, "status": exp_status, "reason_code": reason, "diagnosis": diagnosis,
               "headline": assessment.headline_metric, "verification_status": verification["status"] if verification else "not_run",
               "cpu_s": round(a_cpu, 3), "duration_ms": a_ms, "error": error, "conditions": conditions, "signature": signature,
               "metrics": {k: v.get("value") for k, v in result.get("metrics", {}).items() if isinstance(v.get("value"), (int, float, bool, str))}}
        exp["id"] = recorder.experiment({**exp, "task_type": task, "params": {**params, "strategy": strategy}, "verification": verification or {}})
        out.attempts.append(exp)

        # Memory write (evidence is "verified" only if the verifier ran and every numeric claim matched).
        if mode["write"]:
            lesson_ok = exp_status == "succeeded" if mode["verify_lessons"] else assessment.status == "succeeded"
            memory.record_outcome(db, namespace=cfg.namespace, task_type=task, strategy=strategy, outcome="success" if lesson_ok else "failure",
                                  conditions=conditions, signature=signature, experiment_id=exp["id"], analysis_id=analysis_id, dataset_sha=dataset_sha,
                                  metric=assessment.headline_metric, verified=bool(mode["verify_lessons"] and numeric_ok), detail=(diagnosis or "")[:300])

        loop_ok = assessment.status == "succeeded" and (v_ok if mode["verify_loop"] else True)
        candidate = {"strategy": strategy, "result": result, "verification": verification, "assessment": assessment, "ok": loop_ok, "attempt": attempt}
        if error is None and (best is None or (loop_ok and not best["ok"])):
            best = candidate
        if loop_ok:
            best = candidate
            break
        if attempt > cfg.retry_budget:
            break
        nxt = method.next_strategy(tried, reason, strategies)
        if nxt and plan.get("strategies_locked") and nxt not in strategies:
            # the user fixed the strategy list (or excluded a method): stay inside it
            nxt = next((s_ for s_ in strategies if s_ not in tried), None)
        dh = recorder.start("diagnose", "Diagnose result and choose a justified alternative", "decision", attempt=attempt)
        recorder.finish(dh, "completed" if nxt else "needs_review", outputs={
            "diagnosis": diagnosis, "reason_code": reason, "next_strategy": nxt,
            "justification": (f"'{strategy}' was {exp_status}: {diagnosis}. Trying '{nxt}', which addresses '{reason}'." if nxt else
                              "No remaining justified alternative within the strategy list."),
            "retry_budget_remaining": cfg.retry_budget - attempt + 1})
        strategy = nxt

    out.duration_ms = int((time.perf_counter() - t_start) * 1000)
    if best is None:
        out.status = "failed"
        out.report = {"status": "failed", "error": out.attempts[-1]["error"] if out.attempts else "No attempt ran.", "attempts": out.attempts}
        return out

    out.result, out.final_strategy, out.verification = best["result"], best["strategy"], best["verification"]
    final_params = {**params, "strategy": best["strategy"]}
    if mode["verify_loop"]:
        out.status = "completed" if best["ok"] else "needs_review"
    else:
        out.status = "completed" if best["assessment"].status == "succeeded" else "needs_review"
    out.human_review_needed = out.status == "needs_review"

    # 4. Learn step (persisted above, summarised here)
    lh = recorder.start("learn", "Record experiment and update memory", "memory")
    recorder.finish(lh, "completed", outputs={"recorded_attempts": len(out.attempts), "memory_written": mode["write"], "namespace": cfg.namespace,
                                              "note": "Lessons are promoted to validated only after verified evidence on at least two datasets."
                                              if mode["write"] else "Memory writes disabled in this mode."})

    # 5. Report
    rh = recorder.start("report", "Compose report", "report")
    report = compose_report(plan, final_params, method, out, profile, use_llm=cfg.use_llm and llm.available())
    out.report = report
    out.llm_usage = report.get("llm_usage", [])
    recorder.finish(rh, "completed", outputs={"findings": len(report["findings"]), "recommendations": len(report["recommendations"]),
                                              "narrative_source": report["narrative_source"]})
    return out


def compose_report(plan, params, method, out: EngineOutcome, profile, use_llm: bool) -> dict[str, Any]:
    F, R, L = method.findings(out.result, params)
    findings = [f.to_dict() for f in F]
    v = out.verification
    vc = (v or {}).get("verified_claims", {})
    for f in findings:
        claims = [e for e in f["evidence"] if e in vc]
        f["verified"] = bool(claims) and all(vc[e] for e in claims) if v else None
    limitations = list(dict.fromkeys(L + out.result.get("notes", [])))
    if v is None:
        limitations.insert(0, "Results were not independently verified in this agent mode.")
    elif v["status"] != "passed":
        limitations.insert(0, "Independent verification raised issues; see the verification panel before relying on these results.")
    quality = [i for i in profile.get("issues", []) if i["severity"] == "warning"]
    def _first_sentence(t: str) -> str:
        part = t.split(". ")[0].strip()
        return part if part.endswith(".") else part + "."
    summary = " ".join(f"{f['title']}: {_first_sentence(f['detail'])}" for f in findings[:3] if f["kind"] != "caution")
    narrative_source = "deterministic"
    llm_usage = []
    narrative_check = None
    if use_llm:
        try:
            schema = {"type": "object", "properties": {"executive_summary": {"type": "string"}}, "required": ["executive_summary"]}
            facts = [{"title": f["title"], "detail": f["detail"]} for f in findings]
            data, usage = llm.structured(
                "Write a concise executive summary (3-5 sentences) for a business reader. Use ONLY the numbers in the findings. "
                "Do not claim causation. Mention the main uncertainty.", f"Question: {plan['question']}\nFindings: {facts}\nLimitations: {limitations[:4]}", schema,
                "submit_summary", 600)
            llm_usage.append(usage)
            values = [m.get("value") for m in out.result.get("metrics", {}).values() if isinstance(m.get("value"), (int, float))]
            values += [c["value"] for c in out.result.get("claims", []) if isinstance(c.get("value"), (int, float))]
            values += [abs(x) for x in values]
            unsupported = check_narrative(data["executive_summary"], [float(x) for x in values])
            narrative_check = {"unsupported_numbers": unsupported}
            if not unsupported:
                summary, narrative_source = data["executive_summary"], f"llm:{usage['model']} (numbers checked against verified results)"
            else:
                narrative_source = "deterministic (LLM summary rejected: unsupported numbers " + ", ".join(unsupported[:5]) + ")"
        except llm.LLMError as exc:
            narrative_source = f"deterministic (LLM unavailable: {exc})"
    return {
        "title": plan["question"],
        "objective": plan["objective"],
        "task_type": plan["task_type"],
        "status": out.status,
        "executive_summary": summary,
        "narrative_source": narrative_source,
        "narrative_check": narrative_check,
        "findings": findings,
        "recommendations": [r.to_dict() for r in R],
        "limitations": limitations,
        "warnings": out.result.get("warnings", []),
        "data_quality": quality,
        "charts": out.result.get("charts", []),
        "tables": out.result.get("tables", {}),
        "metrics": out.result.get("metrics", {}),
        "claims": out.result.get("claims", []),
        "verification": v,
        "final_strategy": out.final_strategy,
        "attempts": out.attempts,
        "lessons_used": out.lessons_used,
        "llm_usage": llm_usage,
        "reproducibility": {
            "python": platform.python_version(),
            "libraries": _versions(),
            "random_seed": 42,
            "params": params,
            "isolation": "subprocess sandbox: static validation, rlimits, timeout, scrubbed env, audit hook" + (", no-network namespace" if netns_available() else ""),
        },
    }


def _versions() -> dict[str, str]:
    import numpy, scipy, sklearn, statsmodels  # noqa: E401
    return {"pandas": pd.__version__, "numpy": numpy.__version__, "scipy": scipy.__version__, "scikit-learn": sklearn.__version__,
            "statsmodels": statsmodels.__version__}


# ---------------- persistence for user analyses ----------------

class DBRecorder:
    def __init__(self, db: Session, analysis: Analysis):
        self.db, self.analysis = db, analysis
        self.idx = len(analysis.steps)

    def start(self, key, title, kind, *, code="", rationale="", inputs=None, attempt=1):
        st = Step(analysis_id=self.analysis.id, idx=self.idx, key=key, title=title + (f" (attempt {attempt})" if attempt > 1 and kind in ("python", "sql") else ""),
                  kind=kind, status="running", attempt=attempt, rationale=rationale, code=code, inputs=inputs or {}, started_at=utcnow())
        self.idx += 1
        self.db.add(st)
        self.db.commit()
        return st

    def finish(self, st, status, *, outputs=None, error=None, stdout="", stderr="", duration_ms=None, cpu_s=None):
        st.status, st.outputs, st.error = status, outputs or {}, error
        st.stdout, st.stderr = stdout[-8000:], stderr[-8000:]
        st.finished_at = utcnow()
        st.duration_ms = duration_ms if duration_ms is not None else int((st.finished_at - st.started_at).total_seconds() * 1000)
        st.cpu_s = cpu_s
        self.db.commit()

    def experiment(self, data):
        e = Experiment(owner_id=self.analysis.owner_id, analysis_id=self.analysis.id, task_type=data["task_type"], strategy=data["strategy"], status=data["status"],
                       attempt=data["attempt"], failure_reason=data.get("error"), diagnosis=data.get("diagnosis"), metrics=data.get("metrics", {}),
                       verification={k: data["verification"].get(k) for k in ("status", "counts", "reason_codes", "checks")} if data.get("verification") else {},
                       dataset_signature=data.get("signature", {}), params=data.get("params", {}), duration_ms=data.get("duration_ms"), cpu_s=data.get("cpu_s"))
        prev = self.db.query(Experiment).filter(Experiment.analysis_id == self.analysis.id).order_by(Experiment.created_at.desc()).first()
        if prev:
            e.retry_of = prev.id
        self.db.add(e)
        self.db.commit()
        return e.id


def execute_analysis(analysis_id: str) -> None:
    """Background job: run an approved analysis and persist every step."""
    from .storage import dataset_path, load_dataset
    from .db import Dataset
    db = SessionLocal()
    try:
        a = db.get(Analysis, analysis_id)
        if a is None:
            return
        ds = db.get(Dataset, a.dataset_id)
        a.status = "running"
        db.commit()
        df = load_dataset(ds.id)
        mode = a.agent_mode if a.agent_mode in MODES else "validated_verified"
        from .auth import memory_namespace
        cfg = EngineConfig(mode=mode, namespace=memory_namespace(a.owner_id) if a.owner_id else "default",
                           retry_budget=int(a.plan.get("retry_budget", settings.retry_budget)))
        outcome = run_engine(df=df, data_path=dataset_path(ds.id), dataset_sha=ds.sha256, profile=ds.profile, plan=a.plan, cfg=cfg,
                             recorder=DBRecorder(db, a), db=db, run_root=settings.runs_dir / a.id, analysis_id=a.id)
        from .profiler import data_handling
        report = dict(outcome.report)
        try:
            report["data_handling"] = data_handling(df, a.plan.get("task_type", ""), a.plan.get("params", {}))
        except Exception:  # informational only
            pass
        a.result = report
        a.status = outcome.status
        a.error = outcome.report.get("error") if outcome.status == "failed" else None
        db.commit()
    except Exception as exc:  # never leave an analysis stuck in "running"
        log.error("analysis %s crashed: %s", analysis_id, traceback.format_exc(limit=3))
        db.rollback()
        a = db.get(Analysis, analysis_id)
        if a:
            a.status, a.error = "failed", f"Internal error: {type(exc).__name__}: {str(exc)[:300]}"
            for st in a.steps:
                if st.status in ("running", "queued"):
                    st.status, st.error = "failed", "Interrupted by an internal error."
            db.commit()
    finally:
        db.close()

