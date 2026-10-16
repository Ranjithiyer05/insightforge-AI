"""InsightForge AI HTTP API (FastAPI)."""
from __future__ import annotations

import logging
import shutil
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, Response as FResponse, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from . import auth, llm, memory, planner, reports, storage
from .auth import admin_user, current_user, memory_namespace
from .agent import MODES, execute_analysis
from .analyses import REGISTRY
from .config import settings
from .db import ShareLink, Analysis, AppSetting, AuthSession, Dataset, EvaluationRun, Experiment, Lesson, Project, User, get_session, init_db, new_id, utcnow
from .evaluation import execute_evaluation
from .profiler import apply_cleaning, preview_rows, profile_dataframe
from .sandbox.executor import netns_available

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("insightforge.api")
pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="if-worker")
DEMO_DIR = Path(__file__).resolve().parent.parent / "demo_data"
DEMOS = {
    "retail": ("retail_sales_SYNTHETIC.csv", "Retail sales (synthetic demo)"),
    "churn": ("customer_churn_SYNTHETIC.csv", "Customer churn (synthetic demo)"),
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    from .db import SessionLocal
    db = SessionLocal()
    try:
        for a in db.scalars(select(Analysis).where(Analysis.status.in_(["queued", "running"]))).all():
            a.status, a.error = "failed", "Interrupted because the server restarted. Re-run the analysis."
        for r in db.scalars(select(EvaluationRun).where(EvaluationRun.status.in_(["queued", "running"]))).all():
            r.status, r.error = "failed", "Interrupted because the server restarted."
        if settings.retention_days > 0:
            cutoff = utcnow() - timedelta(days=settings.retention_days)
            for d in db.scalars(select(Dataset).where(Dataset.created_at < cutoff)).all():
                _delete_dataset_files(d.id)
                db.delete(d)
        db.commit()
    finally:
        db.close()
    yield
    pool.shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="InsightForge AI", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])


# ---------------- helpers ----------------

def _iso(dt):
    return dt.isoformat() if dt else None


def ds_dict(d: Dataset, with_profile: bool = False) -> dict[str, Any]:
    out = {"id": d.id, "name": d.name, "original_filename": d.original_filename, "file_type": d.file_type, "size_bytes": d.size_bytes,
           "n_rows": d.n_rows, "n_cols": d.n_cols, "is_synthetic": d.is_synthetic, "project_id": d.project_id, "created_at": _iso(d.created_at),
           "sha256": d.sha256, "quality_score": (d.profile or {}).get("quality_score"),
           "issues": len([i for i in (d.profile or {}).get("issues", []) if i["severity"] == "warning"]), "cleaning_log": d.cleaning_log}
    if with_profile:
        out["profile"] = d.profile
    return out


def an_dict(a: Analysis, full: bool = False) -> dict[str, Any]:
    out = {"id": a.id, "question": a.question, "status": a.status, "task_type": (a.plan or {}).get("task_type"), "task_label": (a.plan or {}).get("task_label"),
           "dataset_id": a.dataset_id, "project_id": a.project_id, "parent_id": a.parent_id, "agent_mode": a.agent_mode, "created_at": _iso(a.created_at),
           "updated_at": _iso(a.updated_at), "error": a.error,
           "summary": (a.result or {}).get("executive_summary"), "verification": ((a.result or {}).get("verification") or {}).get("status")}
    if full:
        out["plan"] = a.plan
        out["result"] = a.result
        out["steps"] = [step_dict(s) for s in a.steps]
    return out


def step_dict(s) -> dict[str, Any]:
    return {"id": s.id, "idx": s.idx, "key": s.key, "title": s.title, "kind": s.kind, "status": s.status, "attempt": s.attempt, "rationale": s.rationale,
            "code": s.code, "inputs": s.inputs, "outputs": s.outputs, "stdout": s.stdout, "stderr": s.stderr, "error": s.error,
            "duration_ms": s.duration_ms, "cpu_s": s.cpu_s, "started_at": _iso(s.started_at), "finished_at": _iso(s.finished_at)}


def exp_dict(e: Experiment) -> dict[str, Any]:
    return {"id": e.id, "analysis_id": e.analysis_id, "task_type": e.task_type, "strategy": e.strategy, "status": e.status, "attempt": e.attempt,
            "retry_of": e.retry_of, "failure_reason": e.failure_reason, "diagnosis": e.diagnosis, "metrics": e.metrics, "verification": e.verification,
            "dataset_signature": e.dataset_signature, "params": e.params, "duration_ms": e.duration_ms, "cpu_s": e.cpu_s, "created_at": _iso(e.created_at)}


def get_or_404(db: Session, model, id_: str, user: User | None = None):
    obj = db.get(model, id_)
    if obj is None:
        raise HTTPException(404, f"{model.__name__} not found")
    if user is not None:
        owner = getattr(obj, "owner_id", None) if model is not Lesson else (obj.namespace == memory_namespace(user.id) and user.id)
        if owner != user.id:
            raise HTTPException(404, f"{model.__name__} not found")  # 404, not 403: do not reveal other users' ids
    return obj


def agent_settings(db: Session, user: User) -> dict[str, Any]:
    s = db.get(AppSetting, f"agent:{user.id}")
    base = {"agent_mode": "validated_verified", "retry_budget": settings.retry_budget, "memory_enabled": True}
    return {**base, **(s.value if s else {})}


def _delete_dataset_files(dataset_id: str) -> None:
    folder = (settings.uploads_dir / dataset_id).resolve()
    if settings.uploads_dir.resolve() in folder.parents and folder.exists():
        shutil.rmtree(folder)


def _create_dataset(db: Session, user: User, raw: bytes, filename: str, kind: str, df, project_id: str | None, synthetic: bool, name: str | None = None) -> Dataset:
    ds_id = new_id("ds")
    storage.store_dataframe(ds_id, df)
    profile = profile_dataframe(df)
    d = Dataset(id=ds_id, owner_id=user.id, project_id=project_id, name=name or storage.safe_display_name(filename), original_filename=storage.safe_display_name(filename),
                stored_path=f"{ds_id}/data.csv", file_type=kind, size_bytes=len(raw), sha256=storage.sha256(raw), n_rows=int(df.shape[0]),
                n_cols=int(df.shape[1]), is_synthetic=synthetic, profile=profile)
    db.add(d)
    db.commit()
    return d


# ---------------- status & overview ----------------

@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/status")
def status(db: Session = Depends(get_session), user: User = Depends(current_user)):
    running = db.scalar(select(func.count()).select_from(Analysis).where(Analysis.owner_id == user.id, Analysis.status.in_(["queued", "running"])))
    evals = db.scalar(select(func.count()).select_from(EvaluationRun).where(EvaluationRun.owner_id == user.id, EvaluationRun.status.in_(["queued", "running"])))
    return {"llm": llm.status(), "sandbox": {"network_isolation": netns_available(), "timeout_s": settings.sandbox_timeout_s,
                                             "memory_mb": settings.sandbox_memory_mb},
            "running_analyses": running, "running_evaluations": evals, "agent": agent_settings(db, user),
            "limits": {"max_upload_mb": settings.max_upload_mb, "max_rows": settings.max_rows},
            "retention_days": settings.retention_days, "methods": sorted(REGISTRY)}


@app.get("/api/overview")
def overview(db: Session = Depends(get_session), user: User = Depends(current_user)):
    count = lambda m, *w: db.scalar(select(func.count()).select_from(m).where(*w, (m.namespace == ns) if m is Lesson else (m.owner_id == user.id)))  # noqa: E731
    ns = memory_namespace(user.id)
    return {
        "counts": {"projects": count(Project), "datasets": count(Dataset), "analyses": count(Analysis),
                   "completed": count(Analysis, Analysis.status == "completed"), "needs_review": count(Analysis, Analysis.status == "needs_review"),
                   "failed": count(Analysis, Analysis.status == "failed"), "experiments": count(Experiment),
                   "lessons_validated": count(Lesson, Lesson.status == "validated"),
                   "lessons_candidate": count(Lesson, Lesson.status == "candidate"),
                   "evaluations": count(EvaluationRun, EvaluationRun.status == "completed")},
        "recent_projects": [{"id": p.id, "name": p.name, "created_at": _iso(p.created_at), "analyses": len(p.analyses)}
                            for p in db.scalars(select(Project).where(Project.owner_id == user.id).order_by(Project.created_at.desc()).limit(5)).all()],
        "recent_datasets": [ds_dict(d) for d in db.scalars(select(Dataset).where(Dataset.owner_id == user.id).order_by(Dataset.created_at.desc()).limit(5)).all()],
        "recent_analyses": [an_dict(a) for a in db.scalars(select(Analysis).where(Analysis.owner_id == user.id).order_by(Analysis.created_at.desc()).limit(6)).all()],
        "experiment_status": {s: count(Experiment, Experiment.status == s) for s in ("succeeded", "weak", "failed", "invalid")},
    }


@app.get("/api/search")
def search(q: str = Query(min_length=1, max_length=100), db: Session = Depends(get_session), user: User = Depends(current_user)):
    like = f"%{q}%"
    return {
        "datasets": [ds_dict(d) for d in db.scalars(select(Dataset).where(Dataset.owner_id == user.id, Dataset.name.ilike(like)).limit(8)).all()],
        "analyses": [an_dict(a) for a in db.scalars(select(Analysis).where(Analysis.owner_id == user.id, Analysis.question.ilike(like)).limit(8)).all()],
        "lessons": [memory.lesson_dict(l) for l in db.scalars(select(Lesson).where(Lesson.namespace == memory_namespace(user.id), or_(Lesson.statement.ilike(like), Lesson.strategy.ilike(like))).limit(8)).all()],
        "projects": [{"id": p.id, "name": p.name} for p in db.scalars(select(Project).where(Project.owner_id == user.id, Project.name.ilike(like)).limit(8)).all()],
    }


# ---------------- projects ----------------

class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)


@app.get("/api/projects")
def list_projects(db: Session = Depends(get_session), user: User = Depends(current_user)):
    return [{"id": p.id, "name": p.name, "description": p.description, "created_at": _iso(p.created_at), "datasets": len(p.datasets), "analyses": len(p.analyses)}
            for p in db.scalars(select(Project).where(Project.owner_id == user.id).order_by(Project.created_at.desc())).all()]


@app.post("/api/projects")
def create_project(body: ProjectIn, db: Session = Depends(get_session), user: User = Depends(current_user)):
    p = Project(owner_id=user.id, name=body.name.strip(), description=body.description.strip())
    db.add(p)
    db.commit()
    return {"id": p.id, "name": p.name, "description": p.description, "created_at": _iso(p.created_at)}


@app.get("/api/projects/{pid}")
def get_project(pid: str, db: Session = Depends(get_session), user: User = Depends(current_user)):
    p = get_or_404(db, Project, pid, user)
    return {"id": p.id, "name": p.name, "description": p.description, "created_at": _iso(p.created_at),
            "datasets": [ds_dict(d) for d in p.datasets], "analyses": [an_dict(a) for a in p.analyses]}


@app.delete("/api/projects/{pid}")
def delete_project(pid: str, confirm: bool = False, db: Session = Depends(get_session), user: User = Depends(current_user)):
    if not confirm:
        raise HTTPException(400, "Deleting a project removes its analyses. Repeat with confirm=true.")
    db.delete(get_or_404(db, Project, pid, user))
    db.commit()
    return {"deleted": pid}


# ---------------- datasets ----------------

@app.post("/api/datasets/upload")
async def upload_dataset(file: UploadFile = File(...), project_id: str | None = Form(None), sheet: str | None = Form(None), db: Session = Depends(get_session), user: User = Depends(current_user)):
    limit = settings.max_upload_mb * 1024 * 1024
    raw = await file.read(limit + 1)
    if len(raw) > limit:
        raise HTTPException(413, f"File is larger than the {settings.max_upload_mb} MB limit.")
    if not raw:
        raise HTTPException(400, "The file is empty.")
    try:
        kind = storage.detect_type(file.filename or "", raw[:8192])
        df = storage.parse_bytes(raw, kind, sheet if sheet else 0)
    except storage.UploadError as exc:
        raise HTTPException(400, str(exc)) from None
    if project_id:
        get_or_404(db, Project, project_id, user)
    d = _create_dataset(db, user, raw, file.filename or "dataset.csv", kind, df, project_id, synthetic=False)
    return ds_dict(d, with_profile=True)


@app.post("/api/datasets/demo/{name}")
def load_demo(name: str, project_id: str | None = None, db: Session = Depends(get_session), user: User = Depends(current_user)):
    if name not in DEMOS:
        raise HTTPException(404, "Unknown demo dataset")
    fn, label = DEMOS[name]
    raw = (DEMO_DIR / fn).read_bytes()
    df = storage.parse_bytes(raw, "csv")
    if project_id:
        get_or_404(db, Project, project_id, user)
    d = _create_dataset(db, user, raw, fn, "csv", df, project_id, synthetic=True, name=label)
    return ds_dict(d, with_profile=True)


@app.get("/api/datasets")
def list_datasets(q: str | None = None, synthetic: bool | None = None, project_id: str | None = None, db: Session = Depends(get_session), user: User = Depends(current_user)):
    stmt = select(Dataset).where(Dataset.owner_id == user.id).order_by(Dataset.created_at.desc())
    if q:
        stmt = stmt.where(Dataset.name.ilike(f"%{q}%"))
    if synthetic is not None:
        stmt = stmt.where(Dataset.is_synthetic == synthetic)
    if project_id:
        stmt = stmt.where(Dataset.project_id == project_id)
    out = []
    for d in db.scalars(stmt).all():
        x = ds_dict(d)
        x["analyses"] = db.scalar(select(func.count()).select_from(Analysis).where(Analysis.owner_id == user.id, Analysis.dataset_id == d.id))
        out.append(x)
    return out


@app.get("/api/datasets/{did}")
def get_dataset(did: str, db: Session = Depends(get_session), user: User = Depends(current_user)):
    d = get_or_404(db, Dataset, did, user)
    x = ds_dict(d, with_profile=True)
    x["analyses"] = [an_dict(a) for a in db.scalars(select(Analysis).where(Analysis.owner_id == user.id, Analysis.dataset_id == did).order_by(Analysis.created_at.desc())).all()]
    return x


@app.get("/api/datasets/{did}/preview")
def dataset_preview(did: str, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0), db: Session = Depends(get_session), user: User = Depends(current_user)):
    get_or_404(db, Dataset, did, user)
    df = storage.load_dataset(did)
    return {"columns": list(df.columns), "rows": preview_rows(df.iloc[offset:offset + limit], limit), "total": int(len(df)), "offset": offset}


class CleanIn(BaseModel):
    operations: list[dict[str, Any]]
    confirm: bool = False


@app.post("/api/datasets/{did}/clean")
def clean_dataset(did: str, body: CleanIn, db: Session = Depends(get_session), user: User = Depends(current_user)):
    d = get_or_404(db, Dataset, did, user)
    if not body.confirm:
        raise HTTPException(400, "Cleaning operations change data. Review them and repeat with confirm=true. The original dataset is kept.")
    df = storage.load_dataset(did)
    try:
        cleaned, log_ = apply_cleaning(df, body.operations)
    except (ValueError, KeyError) as exc:
        raise HTTPException(400, str(exc)) from None
    raw = cleaned.to_csv(index=False).encode()
    nd = _create_dataset(db, user, raw, d.original_filename, d.file_type, cleaned, d.project_id, d.is_synthetic, name=f"{d.name} (cleaned)")
    nd.cleaning_log = (d.cleaning_log or []) + [{"from_dataset": d.id, "at": utcnow().isoformat(), "operations": log_}]
    db.commit()
    return ds_dict(nd, with_profile=True)


@app.delete("/api/datasets/{did}")
def delete_dataset(did: str, confirm: bool = False, db: Session = Depends(get_session), user: User = Depends(current_user)):
    d = get_or_404(db, Dataset, did, user)
    if not confirm:
        raise HTTPException(400, "This permanently deletes the dataset file and its analyses. Repeat with confirm=true.")
    _delete_dataset_files(did)
    for a in db.scalars(select(Analysis).where(Analysis.owner_id == user.id, Analysis.dataset_id == did)).all():
        shutil.rmtree(settings.runs_dir / a.id, ignore_errors=True)
        db.delete(a)
    db.delete(d)
    db.commit()
    return {"deleted": did}


# ---------------- analyses ----------------

class PlanIn(BaseModel):
    dataset_id: str
    question: str = Field(min_length=3, max_length=2000)
    project_id: str | None = None
    parent_id: str | None = None


class PlanEdit(BaseModel):
    task_type: str | None = None
    params: dict[str, Any] | None = None
    strategies: list[str] | None = None
    retry_budget: int | None = Field(default=None, ge=0, le=5)
    question: str | None = None


@app.post("/api/analyses/plan")
def create_plan(body: PlanIn, db: Session = Depends(get_session), user: User = Depends(current_user)):
    d = get_or_404(db, Dataset, body.dataset_id, user)
    ag = agent_settings(db, user)
    plan = planner.make_plan(body.question, d.profile)
    plan["retry_budget"] = ag["retry_budget"]
    plan["estimated_sandbox_runs"]["max"] = plan["estimated_sandbox_runs"]["min"] * (1 + ag["retry_budget"])
    if body.project_id:
        get_or_404(db, Project, body.project_id, user)
    if body.parent_id:
        get_or_404(db, Analysis, body.parent_id, user)
    a = Analysis(owner_id=user.id, dataset_id=d.id, project_id=body.project_id or d.project_id, parent_id=body.parent_id, question=body.question.strip(), plan=plan,
                 status="draft", agent_mode=ag["agent_mode"] if ag["memory_enabled"] else "baseline")
    db.add(a)
    db.commit()
    return an_dict(a, full=True)


@app.patch("/api/analyses/{aid}/plan")
def edit_plan(aid: str, body: PlanEdit, db: Session = Depends(get_session), user: User = Depends(current_user)):
    a = get_or_404(db, Analysis, aid, user)
    if a.status != "draft":
        raise HTTPException(409, "Only draft plans can be edited. Re-run the analysis to start a new draft.")
    d = db.get(Dataset, a.dataset_id)
    old = a.plan
    task = body.task_type or old["task_type"]
    if task not in REGISTRY:
        raise HTTPException(400, f"Unknown task type '{task}'")
    question = body.question or a.question
    if task != old["task_type"]:
        params, notes = planner.build_params(task, question, d.profile)
    else:
        params, notes = dict(old["params"]), list(old.get("assumptions", []))
    if body.params:
        cols = {c["name"] for c in d.profile["columns"]}
        for k, v in body.params.items():
            vals = v if isinstance(v, list) else [v]
            if k not in ("alpha", "horizon", "freq", "agg", "design", "current_period", "positive_class", "groups", "contamination") and \
                    any(isinstance(x, str) and x not in cols for x in vals):
                raise HTTPException(400, f"'{v}' is not a column in this dataset")
            params[k] = v
    method = REGISTRY[task]
    strategies = body.strategies or (old["strategies"] if task == old["task_type"] else planner.strategy_order(task, params))
    bad = [s for s in strategies if s not in method.strategies]
    if bad:
        raise HTTPException(400, f"Unknown strategies for {task}: {bad}")
    plan = planner.finalize_plan(question, d.profile, task, params, old["confidence"] if task == old["task_type"] else 1.0,
                                 old["reasons"] + ["Plan edited by the user."], notes, old["planner"], strategies,
                                 body.retry_budget if body.retry_budget is not None else old.get("retry_budget"))
    plan["strategies_locked"] = bool(body.strategies) or old.get("strategies_locked", False)
    a.plan, a.question = plan, question
    db.commit()
    return an_dict(a, full=True)


@app.post("/api/analyses/{aid}/approve")
def approve(aid: str, db: Session = Depends(get_session), user: User = Depends(current_user)):
    a = get_or_404(db, Analysis, aid, user)
    if a.status != "draft":
        raise HTTPException(409, f"Analysis is already {a.status}.")
    if not a.plan.get("feasible"):
        raise HTTPException(400, "This plan cannot run: " + "; ".join(a.plan.get("missing_requirements", [])))
    a.status = "queued"
    db.commit()
    pool.submit(execute_analysis, a.id)
    return an_dict(a)


@app.post("/api/analyses/{aid}/rerun")
def rerun(aid: str, db: Session = Depends(get_session), user: User = Depends(current_user)):
    a = get_or_404(db, Analysis, aid, user)
    b = Analysis(owner_id=user.id, dataset_id=a.dataset_id, project_id=a.project_id, parent_id=a.id, question=a.question, plan=a.plan, status="queued", agent_mode=a.agent_mode)
    db.add(b)
    db.commit()
    pool.submit(execute_analysis, b.id)
    return an_dict(b)


@app.get("/api/analyses")
def list_analyses(status: str | None = None, dataset_id: str | None = None, q: str | None = None, db: Session = Depends(get_session), user: User = Depends(current_user)):
    stmt = select(Analysis).where(Analysis.owner_id == user.id).order_by(Analysis.created_at.desc())
    if status:
        stmt = stmt.where(Analysis.status == status)
    if dataset_id:
        stmt = stmt.where(Analysis.dataset_id == dataset_id)
    if q:
        stmt = stmt.where(Analysis.question.ilike(f"%{q}%"))
    names = {d.id: d.name for d in db.scalars(select(Dataset).where(Dataset.owner_id == user.id)).all()}
    return [{**an_dict(a), "dataset_name": names.get(a.dataset_id)} for a in db.scalars(stmt.limit(200)).all()]


@app.get("/api/analyses/{aid}")
def get_analysis(aid: str, db: Session = Depends(get_session), user: User = Depends(current_user)):
    a = get_or_404(db, Analysis, aid, user)
    d = db.get(Dataset, a.dataset_id)
    out = an_dict(a, full=True)
    out["dataset"] = ds_dict(d, with_profile=True) if d else None
    out["children"] = [an_dict(c) for c in db.scalars(select(Analysis).where(Analysis.owner_id == user.id, Analysis.parent_id == aid)).all()]
    return out


@app.delete("/api/analyses/{aid}")
def delete_analysis(aid: str, confirm: bool = False, db: Session = Depends(get_session), user: User = Depends(current_user)):
    a = get_or_404(db, Analysis, aid, user)
    if not confirm:
        raise HTTPException(400, "Repeat with confirm=true to delete this analysis and its execution record.")
    if a.status in ("queued", "running"):
        raise HTTPException(409, "Wait for the analysis to finish before deleting it.")
    shutil.rmtree(settings.runs_dir / a.id, ignore_errors=True)
    for sl in db.scalars(select(ShareLink).where(ShareLink.analysis_id == aid)).all():
        db.delete(sl)
    db.delete(a)
    db.commit()
    return {"deleted": aid}


def _finished(db, aid, user) -> tuple[Analysis, Dataset]:
    a = get_or_404(db, Analysis, aid, user)
    if a.status not in ("completed", "needs_review") or not a.result.get("findings") and not a.result.get("metrics"):
        raise HTTPException(409, "The analysis has no results to export yet.")
    return a, db.get(Dataset, a.dataset_id)


@app.get("/api/analyses/{aid}/report.pdf")
def export_pdf(aid: str, db: Session = Depends(get_session), user: User = Depends(current_user)):
    a, d = _finished(db, aid, user)
    pdf = reports.build_pdf(an_dict(a, full=True), ds_dict(d))
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="insightforge_{aid}.pdf"'})


@app.get("/api/analyses/{aid}/tables.zip")
def export_tables(aid: str, db: Session = Depends(get_session), user: User = Depends(current_user)):
    a, _ = _finished(db, aid, user)
    return Response(reports.tables_zip(a.result), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="insightforge_{aid}_tables.zip"'})


@app.get("/api/analyses/{aid}/code.zip")
def export_code(aid: str, db: Session = Depends(get_session), user: User = Depends(current_user)):
    a = get_or_404(db, Analysis, aid, user)
    d = db.get(Dataset, a.dataset_id)
    data = reports.code_zip(an_dict(a, full=True), [step_dict(s) for s in a.steps], ds_dict(d))
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="insightforge_{aid}_code.zip"'})


# ---------------- experiments ----------------

@app.get("/api/experiments")
def list_experiments(task_type: str | None = None, status: str | None = None, analysis_id: str | None = None, db: Session = Depends(get_session), user: User = Depends(current_user)):
    stmt = select(Experiment).where(Experiment.owner_id == user.id).order_by(Experiment.created_at.desc())
    for col, val in ((Experiment.task_type, task_type), (Experiment.status, status), (Experiment.analysis_id, analysis_id)):
        if val:
            stmt = stmt.where(col == val)
    qs = {a.id: a.question for a in db.scalars(select(Analysis).where(Analysis.owner_id == user.id)).all()}
    return [{**exp_dict(e), "question": qs.get(e.analysis_id)} for e in db.scalars(stmt.limit(300)).all()]


@app.get("/api/experiments/{eid}")
def get_experiment(eid: str, db: Session = Depends(get_session), user: User = Depends(current_user)):
    return exp_dict(get_or_404(db, Experiment, eid, user))


# ---------------- memory ----------------

class LessonEdit(BaseModel):
    statement: str | None = Field(default=None, max_length=2000)
    status: str | None = None
    conditions: dict[str, str] | None = None
    reason: str = Field(default="", max_length=500)


@app.get("/api/lessons")
def list_lessons(q: str | None = None, status: str | None = None, task_type: str | None = None, db: Session = Depends(get_session), user: User = Depends(current_user)):
    stmt = select(Lesson).where(Lesson.namespace == memory_namespace(user.id)).order_by(Lesson.updated_at.desc())
    if q:
        stmt = stmt.where(or_(Lesson.statement.ilike(f"%{q}%"), Lesson.strategy.ilike(f"%{q}%")))
    if status:
        stmt = stmt.where(Lesson.status == status)
    if task_type:
        stmt = stmt.where(Lesson.task_type == task_type)
    return [memory.lesson_dict(l) for l in db.scalars(stmt).all()]


@app.get("/api/lessons/{lid}")
def get_lesson(lid: str, db: Session = Depends(get_session), user: User = Depends(current_user)):
    return memory.lesson_dict(get_or_404(db, Lesson, lid, user), full=True)


@app.patch("/api/lessons/{lid}")
def edit_lesson(lid: str, body: LessonEdit, db: Session = Depends(get_session), user: User = Depends(current_user)):
    l = get_or_404(db, Lesson, lid, user)
    try:
        memory.user_update(db, l, body.model_dump(exclude={"reason"}), body.reason)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    db.commit()
    return memory.lesson_dict(l, full=True)


@app.delete("/api/lessons/{lid}")
def delete_lesson(lid: str, db: Session = Depends(get_session), user: User = Depends(current_user)):
    db.delete(get_or_404(db, Lesson, lid, user))
    db.commit()
    return {"deleted": lid}


# ---------------- evaluation ----------------

class EvalIn(BaseModel):
    n_train: int = Field(default=2, ge=1, le=4)
    n_test: int = Field(default=2, ge=1, le=4)
    modes: list[str] | None = None


@app.post("/api/evaluations")
def start_evaluation(body: EvalIn, db: Session = Depends(get_session), user: User = Depends(current_user)):
    if body.modes and any(m not in MODES for m in body.modes):
        raise HTTPException(400, f"modes must be among {list(MODES)}")
    if db.scalar(select(func.count()).select_from(EvaluationRun).where(EvaluationRun.status.in_(["queued", "running"]))):
        raise HTTPException(409, "An evaluation is already running on this server. Try again when it finishes.")
    r = EvaluationRun(owner_id=user.id, config=body.model_dump(), status="queued")
    db.add(r)
    db.commit()
    pool.submit(execute_evaluation, r.id)
    return {"id": r.id, "status": r.status}


@app.get("/api/evaluations")
def list_evaluations(db: Session = Depends(get_session), user: User = Depends(current_user)):
    return [{"id": r.id, "status": r.status, "config": r.config, "created_at": _iso(r.created_at), "finished_at": _iso(r.finished_at), "error": r.error,
             "conclusion": (r.results or {}).get("conclusion"), "progress": (r.results or {}).get("progress")}
            for r in db.scalars(select(EvaluationRun).where(EvaluationRun.owner_id == user.id).order_by(EvaluationRun.created_at.desc())).all()]


@app.get("/api/evaluations/{rid}")
def get_evaluation(rid: str, db: Session = Depends(get_session), user: User = Depends(current_user)):
    r = get_or_404(db, EvaluationRun, rid, user)
    return {"id": r.id, "status": r.status, "config": r.config, "results": r.results, "error": r.error, "created_at": _iso(r.created_at), "finished_at": _iso(r.finished_at)}


@app.get("/api/agent-modes")
def agent_modes():
    return [{"id": k, "label": v["label"], "memory": v["read"], "verifier_in_loop": v["verify_loop"]} for k, v in MODES.items()]


# ---------------- settings ----------------

class SettingsIn(BaseModel):
    agent_mode: str | None = None
    retry_budget: int | None = Field(default=None, ge=0, le=5)
    memory_enabled: bool | None = None


@app.get("/api/settings")
def get_settings(db: Session = Depends(get_session), user: User = Depends(current_user)):
    return {"agent": agent_settings(db, user), "llm": llm.status(),
            "execution": {"sandbox_timeout_s": settings.sandbox_timeout_s, "sandbox_memory_mb": settings.sandbox_memory_mb,
                          "network_isolation": netns_available(), "max_upload_mb": settings.max_upload_mb, "max_rows": settings.max_rows},
            "privacy": {"retention_days": settings.retention_days, "llm_sample_rows": settings.allow_external_llm_sample_rows,
                        "storage": "Datasets are stored only on this server's disk under the data directory."},
            "editable_via_env": ["LLM_PROVIDER", "LLM_MODEL", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "LLM_BASE_URL", "SANDBOX_TIMEOUT_S", "SANDBOX_MEMORY_MB",
                                 "MAX_UPLOAD_MB", "DATASET_RETENTION_DAYS", "ALLOW_LLM_SAMPLE_ROWS"]}


@app.put("/api/settings")
def put_settings(body: SettingsIn, db: Session = Depends(get_session), user: User = Depends(current_user)):
    cur = agent_settings(db, user)
    if body.agent_mode is not None:
        if body.agent_mode not in MODES:
            raise HTTPException(400, "unknown agent mode")
        cur["agent_mode"] = body.agent_mode
    if body.retry_budget is not None:
        cur["retry_budget"] = body.retry_budget
    if body.memory_enabled is not None:
        cur["memory_enabled"] = body.memory_enabled
    s = db.get(AppSetting, f"agent:{user.id}")
    if s:
        s.value = cur
    else:
        db.add(AppSetting(key=f"agent:{user.id}", value=cur))
    db.commit()
    return cur


class WipeIn(BaseModel):
    confirm: str


@app.post("/api/data/wipe")
def wipe(body: WipeIn, db: Session = Depends(get_session), user: User = Depends(current_user)):
    if body.confirm != "DELETE ALL":
        raise HTTPException(400, "Type DELETE ALL to confirm.")
    _wipe_user(db, user.id)
    return {"wiped": True}


def _wipe_user(db: Session, uid: str) -> None:
    for sl in db.scalars(select(ShareLink).where(ShareLink.owner_id == uid)).all():
        db.delete(sl)
    for a in db.scalars(select(Analysis).where(Analysis.owner_id == uid)).all():
        shutil.rmtree(settings.runs_dir / a.id, ignore_errors=True)
        db.delete(a)
    for d in db.scalars(select(Dataset).where(Dataset.owner_id == uid)).all():
        _delete_dataset_files(d.id)
        db.delete(d)
    for model in (Experiment, Project, EvaluationRun):
        for obj in db.scalars(select(model).where(model.owner_id == uid)).all():
            db.delete(obj)
    for l in db.scalars(select(Lesson).where(Lesson.namespace == memory_namespace(uid))).all():
        db.delete(l)
    s = db.get(AppSetting, f"agent:{uid}")
    if s:
        db.delete(s)
    db.commit()


@app.get("/api/export/memory")
def export_memory(db: Session = Depends(get_session), user: User = Depends(current_user)):
    return [memory.lesson_dict(l, full=True) for l in db.scalars(select(Lesson).where(Lesson.namespace == memory_namespace(user.id))).all()]


# ---------------- accounts ----------------

class RegisterIn(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(max_length=200)
    name: str = Field(default="", max_length=120)


class LoginIn(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(max_length=200)


def user_dict(u: User) -> dict[str, Any]:
    return {"id": u.id, "email": u.email, "name": u.name or u.email.split("@")[0], "is_admin": u.is_admin, "disabled": u.disabled, "created_at": _iso(u.created_at)}


@app.post("/api/auth/register")
def register(body: RegisterIn, response: FResponse, db: Session = Depends(get_session)):
    email = auth.validate_credentials(body.email, body.password)
    if auth.user_by_email(db, email):
        raise HTTPException(409, "An account with this email already exists.")
    u = User(email=email, name=body.name.strip()[:120], password_hash=auth.hash_password(body.password), is_admin=auth.should_be_admin(db, email))
    db.add(u)
    db.commit()
    auth.start_session(db, response, u)
    return user_dict(u)


@app.post("/api/auth/login")
def login(body: LoginIn, request: Request, response: FResponse, db: Session = Depends(get_session)):
    email = body.email.strip().lower()
    auth.check_rate(request, email)
    u = auth.user_by_email(db, email)
    if u is None or not auth.verify_password(body.password, u.password_hash):
        auth.record_fail(request, email)
        raise HTTPException(401, "Incorrect email or password.")
    if u.disabled:
        raise HTTPException(403, "This account has been disabled by an administrator.")
    auth.start_session(db, response, u)
    return user_dict(u)


@app.post("/api/auth/logout")
def logout(request: Request, response: FResponse, db: Session = Depends(get_session)):
    auth.end_session(db, request, response)
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: User = Depends(current_user)):
    return user_dict(user)


# ---------------- admin (account management only; no access to users' data) ----------------

def _storage_bytes(uid: str, db: Session) -> int:
    total = 0
    for d in db.scalars(select(Dataset).where(Dataset.owner_id == uid)).all():
        f = settings.uploads_dir / d.id / "data.csv"
        total += f.stat().st_size if f.exists() else 0
    return total


@app.get("/api/admin/users")
def admin_users(db: Session = Depends(get_session), admin: User = Depends(admin_user)):
    out = []
    for u in db.scalars(select(User).order_by(User.created_at)).all():
        c = lambda m: db.scalar(select(func.count()).select_from(m).where(m.owner_id == u.id))  # noqa: E731
        out.append({**user_dict(u), "datasets": c(Dataset), "analyses": c(Analysis), "experiments": c(Experiment),
                    "lessons": db.scalar(select(func.count()).select_from(Lesson).where(Lesson.namespace == memory_namespace(u.id))),
                    "storage_bytes": _storage_bytes(u.id, db),
                    "active_sessions": db.scalar(select(func.count()).select_from(AuthSession).where(AuthSession.user_id == u.id))})
    return out


@app.get("/api/admin/stats")
def admin_stats(db: Session = Depends(get_session), admin: User = Depends(admin_user)):
    c = lambda m, *w: db.scalar(select(func.count()).select_from(m).where(*w))  # noqa: E731
    return {"users": c(User), "disabled_users": c(User, User.disabled.is_(True)), "datasets": c(Dataset), "analyses": c(Analysis),
            "running": c(Analysis, Analysis.status.in_(["queued", "running"])), "failed": c(Analysis, Analysis.status == "failed"),
            "evaluations": c(EvaluationRun), "llm": llm.status(), "sandbox_network_isolation": netns_available(),
            "storage_bytes": sum(f.stat().st_size for f in settings.uploads_dir.rglob("*") if f.is_file())}


class AdminUserEdit(BaseModel):
    disabled: bool | None = None
    is_admin: bool | None = None


@app.patch("/api/admin/users/{uid}")
def admin_edit_user(uid: str, body: AdminUserEdit, db: Session = Depends(get_session), admin: User = Depends(admin_user)):
    u = db.get(User, uid)
    if u is None:
        raise HTTPException(404, "User not found")
    if u.id == admin.id and (body.disabled or body.is_admin is False):
        raise HTTPException(400, "You cannot disable or demote your own account.")
    if body.disabled is not None:
        u.disabled = body.disabled
        if body.disabled:
            for s in db.scalars(select(AuthSession).where(AuthSession.user_id == u.id)).all():
                db.delete(s)
    if body.is_admin is not None:
        u.is_admin = body.is_admin
    db.commit()
    return user_dict(u)


@app.delete("/api/admin/users/{uid}")
def admin_delete_user(uid: str, confirm: bool = False, db: Session = Depends(get_session), admin: User = Depends(admin_user)):
    u = db.get(User, uid)
    if u is None:
        raise HTTPException(404, "User not found")
    if u.id == admin.id:
        raise HTTPException(400, "You cannot delete your own account here.")
    if not confirm:
        raise HTTPException(400, "This permanently deletes the account and all of its data. Repeat with confirm=true.")
    _wipe_user(db, u.id)
    db.delete(u)
    db.commit()
    return {"deleted": uid}


# ---------------- dataset explorer ----------------

@app.get("/api/datasets/{did}/explore")
def explore_dataset(did: str, db: Session = Depends(get_session), user: User = Depends(current_user)):
    """Distributions, top values and correlations, all computed from the stored file."""
    import numpy as np
    import pandas as pd
    d = get_or_404(db, Dataset, did, user)
    df = storage.load_dataset(did)
    types = {c["name"]: c.get("semantic_type") for c in (d.profile or {}).get("columns", [])}
    numeric, out_cols = [], []
    for col in df.columns:
        s = df[col]
        info: dict[str, Any] = {"name": col, "semantic_type": types.get(col), "missing": int(s.isna().sum()), "n": int(len(s))}
        num = pd.to_numeric(s, errors="coerce")
        is_num = types.get(col) in ("numeric", "continuous", "integer", "currency", "percentage", "count") or (num.notna().mean() > 0.95 and s.nunique() > 12)
        if is_num and num.notna().sum() >= 2:
            x = num.dropna()
            counts, edges = np.histogram(x, bins=min(24, max(5, int(np.sqrt(len(x))))))
            info["kind"] = "numeric"
            info["histogram"] = [{"bin": f"{edges[i]:.4g}–{edges[i + 1]:.4g}", "start": float(edges[i]), "count": int(counts[i])} for i in range(len(counts))]
            info["stats"] = {k: float(v) for k, v in {"mean": x.mean(), "median": x.median(), "std": x.std(), "min": x.min(), "max": x.max(),
                                                       "q1": x.quantile(0.25), "q3": x.quantile(0.75), "skew": x.skew()}.items() if pd.notna(v)}
            numeric.append(col)
        else:
            vc = s.astype("string").fillna("(missing)").value_counts()
            info["kind"] = "categorical"
            info["unique"] = int(s.nunique(dropna=True))
            info["top"] = [{"value": str(k)[:60], "count": int(v)} for k, v in vc.head(12).items()]
            info["other"] = int(vc.iloc[12:].sum())
        out_cols.append(info)
    corr = None
    if len(numeric) >= 2:
        use = numeric[:15]
        m = df[use].apply(pd.to_numeric, errors="coerce").corr(method="pearson", min_periods=10)
        corr = {"columns": use, "matrix": [[None if pd.isna(v) else round(float(v), 3) for v in row] for row in m.to_numpy()],
                "note": "Pearson correlation on pairwise non-missing rows. Correlation is not causation." + (" Showing the first 15 numeric columns." if len(numeric) > 15 else "")}
    return {"columns": out_cols, "correlation": corr, "n_rows": int(len(df))}


# ---------------- follow-up questions ----------------

class FollowUpIn(BaseModel):
    question: str = Field(min_length=3, max_length=2000)


_SAME_TASK_HINTS = ("different model", "another model", "other model", "different method", "another method", "different test", "try again", "instead", "why")


@app.post("/api/analyses/{aid}/followup")
def follow_up(aid: str, body: FollowUpIn, db: Session = Depends(get_session), user: User = Depends(current_user)):
    """Plan a new analysis that builds on a finished one: same dataset, linked as a child, editable before it runs."""
    parent = get_or_404(db, Analysis, aid, user)
    d = get_or_404(db, Dataset, parent.dataset_id, user)
    q = body.question.strip()
    ag = agent_settings(db, user)
    fresh = planner.make_plan(q, d.profile)
    ql = q.lower()
    reuse = fresh["confidence"] < 0.5 or any(h in ql for h in _SAME_TASK_HINTS)
    pplan = parent.plan or {}
    if reuse and pplan.get("task_type"):
        params = {**pplan.get("params", {})}
        mentioned = planner.mentioned_columns(q, d.profile)
        for k, v in fresh.get("params", {}).items():
            if v and isinstance(v, str) and v in mentioned:
                params[k] = v
        strategies = list(pplan.get("strategies", []))
        used = (parent.result or {}).get("final_strategy")
        if used and used in strategies and any(h in ql for h in ("different", "another", "other", "instead", "try again")):
            # the user asked for a different method, so the one already used is not tried again
            strategies = [s_ for s_ in strategies if s_ != used] or strategies
            switch = True
        else:
            switch = False
        plan = planner.make_plan(q, d.profile, task_override=pplan["task_type"], params_override=params)
        plan["strategies"] = strategies or plan["strategies"]
        if switch:
            plan["strategies_locked"] = True  # memory must not move the method we were asked to replace back to the front
        plan["reasons"] = [f"Follow-up to “{parent.question[:80]}”: kept its analysis type and settings"
                           + (f", excluding the method used before ({used.replace('_', ' ')})." if switch else ".")] + plan.get("reasons", [])
    else:
        plan = fresh
        plan["reasons"] = [f"Follow-up to “{parent.question[:80]}”: the new question asks for a different analysis."] + plan.get("reasons", [])
    plan["followup_of"] = {"id": parent.id, "question": parent.question}
    plan["retry_budget"] = ag["retry_budget"]
    plan["estimated_sandbox_runs"]["max"] = plan["estimated_sandbox_runs"]["min"] * (1 + ag["retry_budget"])
    a = Analysis(owner_id=user.id, dataset_id=d.id, project_id=parent.project_id, parent_id=parent.id, question=q, plan=plan, status="draft", agent_mode=parent.agent_mode)
    db.add(a)
    db.commit()
    return an_dict(a, full=True)


# ---------------- share links ----------------

def _hash_token(t: str) -> str:
    import hashlib
    return hashlib.sha256(t.encode()).hexdigest()


@app.get("/api/analyses/{aid}/share")
def share_status(aid: str, db: Session = Depends(get_session), user: User = Depends(current_user)):
    get_or_404(db, Analysis, aid, user)
    sl = db.scalars(select(ShareLink).where(ShareLink.analysis_id == aid, ShareLink.owner_id == user.id)).first()
    return {"shared": bool(sl), "created_at": _iso(sl.created_at) if sl else None}


@app.post("/api/analyses/{aid}/share")
def create_share(aid: str, db: Session = Depends(get_session), user: User = Depends(current_user)):
    """Create (or replace) a read-only link. The token is shown once; only its hash is stored."""
    import secrets
    a, _ = _finished(db, aid, user)
    for old in db.scalars(select(ShareLink).where(ShareLink.analysis_id == a.id)).all():
        db.delete(old)
    token = secrets.token_urlsafe(24)
    db.add(ShareLink(token_hash=_hash_token(token), analysis_id=a.id, owner_id=user.id))
    db.commit()
    return {"token": token, "path": f"/share/{token}"}


@app.delete("/api/analyses/{aid}/share")
def revoke_share(aid: str, db: Session = Depends(get_session), user: User = Depends(current_user)):
    get_or_404(db, Analysis, aid, user)
    n = 0
    for sl in db.scalars(select(ShareLink).where(ShareLink.analysis_id == aid, ShareLink.owner_id == user.id)).all():
        db.delete(sl)
        n += 1
    db.commit()
    return {"revoked": n}


@app.get("/api/public/share/{token}")
def view_share(token: str, db: Session = Depends(get_session)):
    """Public, read-only view: findings, metrics, charts and verification. No code, logs, raw rows or account details."""
    sl = db.scalars(select(ShareLink).where(ShareLink.token_hash == _hash_token(token))).first()
    a = db.get(Analysis, sl.analysis_id) if sl else None
    owner = db.get(User, sl.owner_id) if sl else None
    if not sl or not a or not owner or owner.disabled:
        raise HTTPException(404, "This link is invalid or has been revoked.")
    d = db.get(Dataset, a.dataset_id)
    r = a.result or {}
    keep = ("objective", "data_quality", "executive_summary", "narrative_source", "findings", "recommendations", "metrics", "charts", "verification", "limitations", "warnings", "final_strategy", "data_handling")
    return {"question": a.question, "task_type": (a.plan or {}).get("task_type"),
            "task_label": (a.plan or {}).get("task_label"), "status": a.status, "created_at": _iso(a.created_at),
            "dataset": {"name": d.name if d else None, "n_rows": d.n_rows if d else None, "n_cols": d.n_cols if d else None, "is_synthetic": d.is_synthetic if d else None},
            "result": {k: r[k] for k in keep if k in r}}
