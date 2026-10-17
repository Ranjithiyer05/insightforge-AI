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
from .db import AskQuery, Dashboard, ModelRun, MonitorEvent, DatasetBlob, ShareLink, Analysis, AppSetting, AuthSession, Dataset, EvaluationRun, Experiment, Lesson, Project, User, get_session, init_db, new_id, utcnow
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
                for a in db.scalars(select(Analysis).where(Analysis.dataset_id == d.id)).all():
                    shutil.rmtree(settings.runs_dir / a.id, ignore_errors=True)
                    db.delete(a)
                _delete_dataset_files(d.id)
                db.delete(d)
        db.commit()
        purge_guests(db)
        for m in db.scalars(select(ModelRun).where(ModelRun.status.in_(["queued", "running"]))).all():
            m.status, m.error = "failed", "The server restarted while this model was training. Start it again."
        db.commit()
    finally:
        db.close()
    yield
    pool.shutdown(wait=False, cancel_futures=True)


app = FastAPI(title="InsightForge AI", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(storage.DatasetFileMissing)
def _missing_file(_request: Request, exc: storage.DatasetFileMissing):
    from fastapi.responses import JSONResponse
    return JSONResponse({"detail": str(exc)}, status_code=410)


# ---------------- helpers ----------------

def _iso(dt):
    return dt.isoformat() if dt else None


def ds_dict(d: Dataset, with_profile: bool = False) -> dict[str, Any]:
    out = {"id": d.id, "name": d.name, "original_filename": d.original_filename, "file_type": d.file_type, "size_bytes": d.size_bytes,
           "n_rows": d.n_rows, "n_cols": d.n_cols, "is_synthetic": d.is_synthetic, "project_id": d.project_id, "created_at": _iso(d.created_at),
           "sha256": d.sha256, "quality_score": (d.profile or {}).get("quality_score"),
           "issues": len([i for i in (d.profile or {}).get("issues", []) if i["severity"] == "warning"]), "cleaning_log": d.cleaning_log,
           "parent_id": d.parent_id, "sheet_names": d.sheet_names or []}
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
    storage.forget_dataset(dataset_id)
    from .db import SessionLocal
    s = SessionLocal()
    try:
        blob = s.get(DatasetBlob, dataset_id)
        if blob is not None:
            s.delete(blob)
            s.commit()
    finally:
        s.close()


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
    return {"ok": True, "storage": {"persistent": settings.persistent_db,
                                    "message": None if settings.persistent_db else
                                    "This server keeps data on a temporary disk. Accounts and datasets are erased when it restarts "
                                    "(free hosting restarts after inactivity). Set DATABASE_URL to a Postgres database to keep them."}}


@app.get("/api/status")
def status(db: Session = Depends(get_session), user: User = Depends(current_user)):
    running = db.scalar(select(func.count()).select_from(Analysis).where(Analysis.owner_id == user.id, Analysis.status.in_(["queued", "running"])))
    evals = db.scalar(select(func.count()).select_from(EvaluationRun).where(EvaluationRun.owner_id == user.id, EvaluationRun.status.in_(["queued", "running"])))
    return {"llm": llm.status(), "sandbox": {"network_isolation": netns_available(), "timeout_s": settings.sandbox_timeout_s,
                                             "memory_mb": settings.sandbox_memory_mb},
            "running_analyses": running, "running_evaluations": evals, "agent": agent_settings(db, user),
            "limits": {"max_upload_mb": settings.max_upload_mb, "max_rows": settings.max_rows},
            "storage_persistent": settings.persistent_db,
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
def upload_dataset(file: UploadFile = File(...), project_id: str | None = Form(None), sheet: str | None = Form(None), db: Session = Depends(get_session), user: User = Depends(current_user)):
    # Plain `def`: FastAPI runs it in a worker thread, so parsing a large file never blocks the event loop.
    limit = settings.max_upload_mb * 1024 * 1024
    raw = file.file.read(limit + 1)
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
    if kind == "excel":
        d.sheet_names = storage.excel_sheets(raw)
        if sheet:
            d.name = f"{d.name} [{sheet}]"
        db.commit()
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
    if cleaned.shape[1] == 0 or cleaned.shape[0] == 0:
        raise HTTPException(400, "These steps would leave no rows or no columns, so nothing was saved.")
    raw = cleaned.to_csv(index=False).encode()
    base = d.name.split(" (cleaned")[0]
    version = 2 + sum(1 for e in (d.cleaning_log or []))
    nd = _create_dataset(db, user, raw, d.original_filename, d.file_type, cleaned, d.project_id, d.is_synthetic, name=f"{base} (cleaned v{version})")
    nd.parent_id = d.id
    nd.cleaning_log = (d.cleaning_log or []) + [{"from_dataset": d.id, "from_name": d.name, "at": utcnow().isoformat(), "operations": log_,
                                                  "rows_before": int(len(df)), "rows_after": int(len(cleaned)),
                                                  "columns_before": int(df.shape[1]), "columns_after": int(cleaned.shape[1])}]
    db.commit()
    return ds_dict(nd, with_profile=True)


class CleanPreviewIn(BaseModel):
    operations: list[dict[str, Any]] = Field(max_length=50)


@app.post("/api/datasets/{did}/clean/preview")
def clean_preview(did: str, body: CleanPreviewIn, db: Session = Depends(get_session), user: User = Depends(current_user)):
    """Dry run: what the steps would change, with matched before/after rows. Nothing is saved."""
    from .cleaning import CleaningError, run_operations, side_by_side
    get_or_404(db, Dataset, did, user)
    df = storage.load_dataset(did)
    try:
        cleaned, log_ = run_operations(df, body.operations)
    except CleaningError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"log": log_, "rows_before": int(len(df)), "rows_after": int(len(cleaned)), "columns_before": list(df.columns), "columns_after": list(cleaned.columns),
            "comparison": side_by_side(df, cleaned, log_)}


@app.get("/api/datasets/{did}/clean/suggestions")
def clean_suggestions(did: str, db: Session = Depends(get_session), user: User = Depends(current_user)):
    from .cleaning import OPS, suggest
    d = get_or_404(db, Dataset, did, user)
    return {"suggestions": suggest(d.profile or {}), "operations": OPS}


@app.get("/api/datasets/{did}/lineage")
def lineage(did: str, db: Session = Depends(get_session), user: User = Depends(current_user)):
    """The chain of versions this dataset was cleaned from, and versions cleaned from it."""
    d = get_or_404(db, Dataset, did, user)
    chain, cur, guard = [], d, 0
    while cur is not None and guard < 50:
        chain.append({"id": cur.id, "name": cur.name, "n_rows": cur.n_rows, "n_cols": cur.n_cols, "created_at": _iso(cur.created_at)})
        cur = db.get(Dataset, cur.parent_id) if cur.parent_id else None
        if cur is not None and cur.owner_id != user.id:
            break
        guard += 1
    children = [{"id": c.id, "name": c.name, "created_at": _iso(c.created_at)} for c in
                db.scalars(select(Dataset).where(Dataset.owner_id == user.id, Dataset.parent_id == did)).all()]
    return {"chain": list(reversed(chain)), "children": children, "history": d.cleaning_log or []}


@app.get("/api/datasets/{did}/download")
def download_dataset(did: str, format: str = Query("csv", pattern="^(csv|xlsx)$"), db: Session = Depends(get_session), user: User = Depends(current_user)):
    import io as _io
    d = get_or_404(db, Dataset, did, user)
    df = storage.load_dataset(did)
    safe = df.apply(lambda col: col.map(storage.csv_safe) if col.dtype == object else col)
    stem = storage.safe_display_name(d.name).replace(" ", "_")[:80] or "dataset"
    if format == "xlsx":
        buf = _io.BytesIO()
        safe.to_excel(buf, index=False, engine="openpyxl")
        return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": f'attachment; filename="{stem}.xlsx"'})
    return Response(safe.to_csv(index=False).encode(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{stem}.csv"'})


_eda_cache: dict[str, dict[str, Any]] = {}


@app.get("/api/datasets/{did}/eda")
def dataset_eda(did: str, db: Session = Depends(get_session), user: User = Depends(current_user)):
    return _dataset_eda(get_or_404(db, Dataset, did, user))


class AskIn(BaseModel):
    question: str | None = Field(default=None, max_length=500)
    spec: dict[str, Any] | None = None


@app.post("/api/datasets/{did}/ask")
def ask_dataset(did: str, body: AskIn, db: Session = Depends(get_session), user: User = Depends(current_user)):
    """Answer a natural-language question with generated pandas code; the code shown is the code run."""
    from .ask import AskError, answer
    d = get_or_404(db, Dataset, did, user)
    if not body.question and not body.spec:
        raise HTTPException(400, "Ask a question.")
    try:
        res = answer(storage.load_dataset(did), d.profile or {}, body.question, body.spec)
    except AskError as exc:
        raise HTTPException(422, str(exc)) from None
    q = AskQuery(owner_id=user.id, dataset_id=did, question=(body.question or res["interpretation"])[:500], spec=res["spec"], headline=res.get("headline", "")[:500])
    db.add(q)
    db.commit()
    return {"id": q.id, **res}


@app.get("/api/datasets/{did}/ask/suggestions")
def ask_suggestions(did: str, db: Session = Depends(get_session), user: User = Depends(current_user)):
    from .ask import Schema, suggestions
    d = get_or_404(db, Dataset, did, user)
    s = Schema(storage.load_dataset(did), d.profile or {})
    return {"suggestions": suggestions(s), "llm": llm.available(),
            "schema": {"columns": s.cols, "numeric": s.numeric, "dates": s.dates, "categorical": s.categorical}}


@app.get("/api/datasets/{did}/ask/history")
def ask_history(did: str, db: Session = Depends(get_session), user: User = Depends(current_user)):
    get_or_404(db, Dataset, did, user)
    rows = db.scalars(select(AskQuery).where(AskQuery.owner_id == user.id, AskQuery.dataset_id == did)
                      .order_by(AskQuery.pinned.desc(), AskQuery.created_at.desc()).limit(50)).all()
    return [{"id": r.id, "question": r.question, "spec": r.spec, "headline": r.headline, "pinned": r.pinned, "created_at": r.created_at} for r in rows]


@app.post("/api/ask/{qid}/pin")
def ask_pin(qid: str, pinned: bool = True, db: Session = Depends(get_session), user: User = Depends(current_user)):
    q = db.get(AskQuery, qid)
    if not q or q.owner_id != user.id:
        raise HTTPException(404, "Not found")
    q.pinned = pinned
    db.commit()
    return {"id": qid, "pinned": pinned}


@app.delete("/api/ask/{qid}")
def ask_delete(qid: str, db: Session = Depends(get_session), user: User = Depends(current_user)):
    q = db.get(AskQuery, qid)
    if not q or q.owner_id != user.id:
        raise HTTPException(404, "Not found")
    db.delete(q)
    db.commit()
    return {"deleted": qid}


class AutoMLIn(BaseModel):
    target: str
    features: list[str] | None = None
    task: str | None = Field(default=None, pattern="^(classification|regression)$")
    split: str = Field(default="random", pattern="^(random|time)$")
    date_col: str | None = None
    positive_class: str | None = None


def _model_dict(m: ModelRun, full: bool = True) -> dict[str, Any]:
    out = {"id": m.id, "dataset_id": m.dataset_id, "target": m.target, "config": m.config, "status": m.status, "progress": m.progress,
           "error": m.error, "created_at": m.created_at, "finished_at": m.finished_at}
    if full:
        out["result"] = m.result
    elif m.result:
        r = m.result
        out["summary"] = {"task": r["task"], "best_model": r["best_model"], "primary_metric": r["primary_metric"],
                          "score": r["test_metrics"].get(r["primary_metric"])}
    return out


def _run_automl(mid: str) -> None:
    from .automl import AutoMLError, train
    from .db import SessionLocal
    with SessionLocal() as db:
        m = db.get(ModelRun, mid)
        d = db.get(Dataset, m.dataset_id)
        m.status = "running"
        db.commit()

        def progress(msg: str) -> None:
            m.progress = msg[:255]
            db.commit()
        try:
            cfg = m.config or {}
            max_rows = 20_000 if settings.sandbox_memory_mb <= 512 else 100_000
            result, blob = train(storage.load_dataset(d.id), d.profile or {}, m.target, cfg.get("features"), cfg.get("task"), cfg.get("split", "random"),
                                 cfg.get("date_col"), cfg.get("positive_class"), max_rows=max_rows, progress=progress)
            m.result, m.model_bytes, m.status, m.progress = result, blob, "succeeded", "Done"
        except AutoMLError as exc:
            m.status, m.error = "failed", str(exc)
        except Exception as exc:  # noqa: BLE001
            log.exception("AutoML run %s failed", mid)
            m.status, m.error = "failed", f"Training failed ({type(exc).__name__}: {str(exc)[:300]})"
        m.finished_at = utcnow()
        db.commit()


@app.post("/api/datasets/{did}/automl")
def start_automl(did: str, body: AutoMLIn, db: Session = Depends(get_session), user: User = Depends(current_user)):
    d = get_or_404(db, Dataset, did, user)
    cols = [c["name"] for c in (d.profile or {}).get("columns", [])]
    if body.target not in cols:
        raise HTTPException(422, f"{body.target} is not a column of this dataset.")
    if body.features and any(f not in cols for f in body.features):
        raise HTTPException(422, "Unknown feature column.")
    busy = db.scalar(select(func.count()).select_from(ModelRun).where(ModelRun.owner_id == user.id, ModelRun.status.in_(["queued", "running"])))
    if busy:
        raise HTTPException(429, "A model is already training for your account. Wait for it to finish.")
    m = ModelRun(owner_id=user.id, dataset_id=did, target=body.target, config=body.model_dump(exclude={"target"}))
    db.add(m)
    db.commit()
    pool.submit(_run_automl, m.id)
    return _model_dict(m)


@app.get("/api/datasets/{did}/models")
def list_models(did: str, db: Session = Depends(get_session), user: User = Depends(current_user)):
    get_or_404(db, Dataset, did, user)
    rows = db.scalars(select(ModelRun).where(ModelRun.owner_id == user.id, ModelRun.dataset_id == did).order_by(ModelRun.created_at.desc()).limit(30)).all()
    return [_model_dict(m, full=False) for m in rows]


@app.get("/api/models/{mid}")
def get_model(mid: str, db: Session = Depends(get_session), user: User = Depends(current_user)):
    return _model_dict(get_or_404(db, ModelRun, mid, user))


class PredictIn(BaseModel):
    rows: list[dict[str, Any]] = Field(min_length=1, max_length=20)
    explain: bool = True


@app.post("/api/models/{mid}/predict")
def model_predict(mid: str, body: PredictIn, db: Session = Depends(get_session), user: User = Depends(current_user)):
    from .automl import predict_rows
    m = get_or_404(db, ModelRun, mid, user)
    if m.status != "succeeded" or not m.model_bytes:
        raise HTTPException(409, "This model has not finished training.")
    return {"predictions": predict_rows(m.model_bytes, body.rows, body.explain)}


class ScenarioIn(BaseModel):
    changes: list[dict[str, Any]] = Field(min_length=1, max_length=10)
    filters: list[dict[str, Any]] | None = Field(default=None, max_length=10)


@app.post("/api/models/{mid}/scenario")
def model_scenario(mid: str, body: ScenarioIn, db: Session = Depends(get_session), user: User = Depends(current_user)):
    from .automl import AutoMLError, run_scenario
    m = get_or_404(db, ModelRun, mid, user)
    if m.status != "succeeded" or not m.model_bytes:
        raise HTTPException(409, "This model has not finished training.")
    get_or_404(db, Dataset, m.dataset_id, user)
    try:
        return run_scenario(m.model_bytes, storage.load_dataset(m.dataset_id), body.changes, body.filters)
    except AutoMLError as exc:
        raise HTTPException(422, str(exc)) from None


@app.delete("/api/models/{mid}")
def delete_model(mid: str, db: Session = Depends(get_session), user: User = Depends(current_user)):
    m = get_or_404(db, ModelRun, mid, user)
    db.delete(m)
    db.commit()
    return {"deleted": mid}


@app.get("/api/compare/datasets")
def compare_datasets(a: str, b: str, db: Session = Depends(get_session), user: User = Depends(current_user)):
    from .compare import compare
    da, dbb = get_or_404(db, Dataset, a, user), get_or_404(db, Dataset, b, user)
    if a == b:
        raise HTTPException(400, "Choose two different datasets.")
    return compare(storage.load_dataset(a), storage.load_dataset(b), da.name, dbb.name if dbb.name != da.name else f"{dbb.name} (2)")


def _dataset_eda(d: Dataset) -> dict[str, Any]:
    from .eda import run_eda
    key = f"{d.id}:{d.sha256}"
    if key not in _eda_cache:
        if len(_eda_cache) > 16:
            _eda_cache.pop(next(iter(_eda_cache)))
        _eda_cache[key] = run_eda(storage.load_dataset(d.id), d.profile or {})
    return _eda_cache[key]


@app.get("/api/datasets/{did}/report")
def dataset_report(did: str, format: str = Query("html", pattern="^(html|pdf)$"), db: Session = Depends(get_session), user: User = Depends(current_user)):
    d = get_or_404(db, Dataset, did, user)
    qs = db.scalars(select(AskQuery).where(AskQuery.owner_id == user.id, AskQuery.dataset_id == did, AskQuery.pinned.is_(True)).order_by(AskQuery.created_at)).all()
    ms = db.scalars(select(ModelRun).where(ModelRun.owner_id == user.id, ModelRun.dataset_id == did, ModelRun.status == "succeeded")
                    .order_by(ModelRun.created_at.desc()).limit(2)).all()
    sec = reports.dataset_report_sections(ds_dict(d) | {"profile": d.profile, "cleaning_log": d.cleaning_log}, _dataset_eda(d),
                                          [{"question": q.question, "headline": q.headline} for q in qs], [{"result": m.result} for m in ms])
    stamp = utcnow().strftime("%Y-%m-%d %H:%M UTC")
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in d.name)[:60] or "dataset"
    if format == "pdf":
        return Response(reports.build_dataset_pdf(sec, stamp), media_type="application/pdf", headers={"content-disposition": f'attachment; filename="{safe}_report.pdf"'})
    return Response(reports.build_dataset_html(sec, stamp), media_type="text/html; charset=utf-8", headers={"content-disposition": f'attachment; filename="{safe}_report.html"'})


_pattern_cache: dict[str, Any] = {}


@app.get("/api/datasets/{did}/patterns/{kind}")
def dataset_patterns(did: str, kind: str, request: Request, db: Session = Depends(get_session), user: User = Depends(current_user)):
    """Anomalies, forecast or segments, computed from the stored file and cached per dataset version and parameters."""
    from . import patterns as pt
    d = get_or_404(db, Dataset, did, user)
    q = dict(request.query_params)
    key = f"{did}:{d.sha256}:{kind}:{sorted(q.items())}"
    if key in _pattern_cache:
        return _pattern_cache[key]
    df, prof = storage.load_dataset(did), d.profile or {}
    cols = [c for c in q.get("columns", "").split(",") if c] or None
    try:
        if kind == "anomalies":
            out = pt.anomalies(df, prof, cols, contamination=min(0.1, max(0.001, float(q.get("contamination", 0.01)))))
        elif kind == "forecast":
            h = q.get("horizon")
            out = pt.forecast(df, prof, q.get("date_col") or None, q.get("measure") if "measure" in q else None, q.get("grain", "month"),
                              q.get("agg", "sum") if q.get("agg") in ("sum", "mean", "count") else "sum", int(h) if h else None)
        elif kind == "segments":
            k = q.get("k")
            out = pt.segments(df, prof, cols, int(k) if k else None)
        else:
            raise HTTPException(404, "Unknown pattern type.")
    except pt.PatternError as exc:
        raise HTTPException(422, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(422, f"Invalid parameter: {exc}") from None
    if len(_pattern_cache) > 32:
        _pattern_cache.pop(next(iter(_pattern_cache)))
    _pattern_cache[key] = out
    return out


@app.post("/api/datasets/{did}/versions")
def upload_version(did: str, file: UploadFile = File(...), sheet: str | None = Form(None), db: Session = Depends(get_session), user: User = Depends(current_user)):
    """Upload newer data for the same dataset (e.g. next month's export). Dashboards and monitors follow the latest version."""
    from .dashboards import version_chain
    parent = get_or_404(db, Dataset, did, user)
    limit = settings.max_upload_mb * 1024 * 1024
    raw = file.file.read(limit + 1)
    if len(raw) > limit:
        raise HTTPException(413, f"File is larger than the {settings.max_upload_mb} MB limit.")
    if not raw:
        raise HTTPException(400, "The file is empty.")
    try:
        kind = storage.detect_type(file.filename or "", raw[:8192])
        df = storage.parse_bytes(raw, kind, sheet if sheet else 0)
    except storage.UploadError as exc:
        raise HTTPException(400, str(exc)) from None
    chain = version_chain(db, parent)
    latest = chain[-1]
    base = parent.name.split(" (cleaned")[0].split(" (version")[0]
    d = _create_dataset(db, user, raw, file.filename or "dataset.csv", kind, df, parent.project_id, synthetic=False, name=f"{base} (version {len(chain) + 1})")
    d.parent_id = latest.id
    old, new = set(latest.profile["columns"][i]["name"] for i in range(len(latest.profile["columns"]))), set(map(str, df.columns))
    d.cleaning_log = []
    db.commit()
    out = ds_dict(d, with_profile=True)
    out["schema_changes"] = {"added": sorted(new - old), "removed": sorted(old - new)}
    return out


@app.get("/api/datasets/{did}/pipeline")
def dataset_pipeline(did: str, db: Session = Depends(get_session), user: User = Depends(current_user)):
    """Everything derived from this dataset's lineage: versions, cleaning steps, questions, models, analyses and dashboards."""
    from .dashboards import version_chain
    d = get_or_404(db, Dataset, did, user)
    chain = version_chain(db, d)
    ids = [x.id for x in chain]
    nodes, edges = [], []
    for x in chain:
        kind = "upload" if not x.parent_id else ("cleaned" if x.cleaning_log and x.cleaning_log[-1].get("from_dataset") == x.parent_id else "new_data")
        ops = x.cleaning_log[-1]["operations"] if kind == "cleaned" else []
        nodes.append({"id": x.id, "type": "dataset", "label": x.name, "kind": kind, "rows": x.n_rows, "cols": x.n_cols, "created_at": x.created_at,
                      "sha256": x.sha256[:12], "steps": [o.get("label") or o.get("op") for o in ops], "current": x.id == did})
        if x.parent_id in ids:
            edges.append({"from": x.parent_id, "to": x.id, "label": f"{len(ops)} cleaning step(s)" if kind == "cleaned" else "new upload"})
    for q in db.scalars(select(AskQuery).where(AskQuery.owner_id == user.id, AskQuery.dataset_id.in_(ids)).order_by(AskQuery.created_at.desc()).limit(20)):
        nodes.append({"id": q.id, "type": "question", "label": q.question, "detail": q.headline, "created_at": q.created_at})
        edges.append({"from": q.dataset_id, "to": q.id})
    for m in db.scalars(select(ModelRun).where(ModelRun.owner_id == user.id, ModelRun.dataset_id.in_(ids)).order_by(ModelRun.created_at.desc()).limit(10)):
        nodes.append({"id": m.id, "type": "model", "label": f"Predict {m.target}", "detail": m.status if m.status != "succeeded" else (m.result or {}).get("best_model", ""), "created_at": m.created_at})
        edges.append({"from": m.dataset_id, "to": m.id})
    for a in db.scalars(select(Analysis).where(Analysis.owner_id == user.id, Analysis.dataset_id.in_(ids)).order_by(Analysis.created_at.desc()).limit(10)):
        nodes.append({"id": a.id, "type": "analysis", "label": a.question, "detail": a.status, "created_at": a.created_at})
        edges.append({"from": a.dataset_id, "to": a.id})
    for b in db.scalars(select(Dashboard).where(Dashboard.owner_id == user.id, Dashboard.dataset_id.in_(ids))):
        nodes.append({"id": b.id, "type": "dashboard", "label": b.name, "detail": f"{len(b.tiles)} tiles, follows latest version", "created_at": b.created_at})
        edges.append({"from": b.dataset_id, "to": b.id})
    return {"nodes": nodes, "edges": edges, "latest": chain[-1].id}


@app.get("/api/datasets/{did}/reproduce.zip")
def dataset_reproduce(did: str, db: Session = Depends(get_session), user: User = Depends(current_user)):
    """A bundle that rebuilds this dataset version from its uploaded source and re-runs saved questions, without InsightForge."""
    import io
    import json as _json
    import zipfile
    from .dashboards import version_chain
    d = get_or_404(db, Dataset, did, user)
    chain = version_chain(db, d)
    # walk back to the upload this version was cleaned from
    by_id = {x.id: x for x in chain}
    src = d
    while src.parent_id and src.cleaning_log and src.parent_id in by_id:
        src = by_id[src.parent_id]
    recipe = [{"op": o["op"], **({"column": o["column"]} if o.get("column") else {}), **(o.get("params") or {}), "reason": o.get("reason") or ""}
              for h in (d.cleaning_log or []) for o in h.get("operations", [])]
    cleaning_src = (Path(__file__).parent / "cleaning.py").read_text().replace(
        "from .profiler import _finite",
        "import math\n\n\ndef _finite(x):\n    if isinstance(x, (float, np.floating)):\n        return None if (math.isnan(x) or math.isinf(x)) else float(x)\n"
        "    if isinstance(x, np.integer):\n        return int(x)\n    return x")
    replay = """\"\"\"Rebuild the cleaned dataset from the original upload.\n\nUsage: python replay.py original.csv cleaned.csv\n\"\"\"
import json
import sys

import pandas as pd

from cleaning import run_operations

src, out = sys.argv[1], sys.argv[2]
df = pd.read_csv(src, sep=None, engine="python") if src.endswith(".csv") else pd.read_excel(src)
recipe = json.load(open("recipe.json"))
cleaned, log = run_operations(df, recipe["operations"])
for step in log:
    print(f"step {step['step']}: {step['label']}  rows {step['rows_before']} -> {step['rows_after']}")
cleaned.to_csv(out, index=False)
print(f"wrote {out}: {len(cleaned)} rows x {cleaned.shape[1]} columns (expected {recipe['expected_rows']} x {recipe['expected_columns']})")
"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("cleaning.py", cleaning_src)
        z.writestr("replay.py", replay)
        z.writestr("recipe.json", _json.dumps({"source_file": src.original_filename, "source_sha256": src.sha256, "operations": recipe,
                                               "expected_rows": d.n_rows, "expected_columns": d.n_cols, "dataset": d.name}, indent=2, default=str))
        qs = db.scalars(select(AskQuery).where(AskQuery.owner_id == user.id, AskQuery.dataset_id == did).order_by(AskQuery.created_at)).all()
        from .ask import compile_pandas
        for i, q in enumerate(qs, 1):
            try:
                code = compile_pandas(q.spec)
            except Exception:  # noqa: BLE001
                continue
            z.writestr(f"questions/q{i:02d}.py", f"# {q.question}\n# Answer at the time: {q.headline}\nimport sys\n\nimport numpy as np\nimport pandas as pd\n\n"
                                                 f"df = pd.read_csv(sys.argv[1])\n{code}\nprint(result.to_string())\n")
        z.writestr("README.md", f"# Reproduce: {d.name}\n\nOriginal file: `{src.original_filename}` (SHA-256 `{src.sha256}`). The data itself is not included.\n\n"
                   "    pip install pandas numpy openpyxl\n    python replay.py original.csv cleaned.csv\n    python questions/q01.py cleaned.csv\n\n"
                   f"`recipe.json` lists the {len(recipe)} cleaning step(s) in order, with the reason recorded for each. `cleaning.py` is the exact code InsightForge runs.\n")
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in d.name)[:60] or "dataset"
    return Response(buf.getvalue(), media_type="application/zip", headers={"content-disposition": f'attachment; filename="{safe}_reproduce.zip"'})


# ---------------- dashboards & monitoring ----------------

class DashboardIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    dataset_id: str
    project_id: str | None = None
    tiles: list[dict[str, Any]] = Field(default_factory=list, max_length=40)


class DashboardPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    tiles: list[dict[str, Any]] | None = Field(default=None, max_length=40)


def _board_dict(b: Dashboard) -> dict[str, Any]:
    return {"id": b.id, "name": b.name, "dataset_id": b.dataset_id, "project_id": b.project_id, "tiles": b.tiles, "created_at": b.created_at, "updated_at": b.updated_at}


def _valid_tiles(tiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from .ask import AskError
    from .dashboards import clean_tile
    try:
        return [clean_tile(t) for t in tiles]
    except (AskError, TypeError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from None


@app.get("/api/dashboards")
def list_dashboards(db: Session = Depends(get_session), user: User = Depends(current_user)):
    rows = db.scalars(select(Dashboard).where(Dashboard.owner_id == user.id).order_by(Dashboard.updated_at.desc())).all()
    names = {d.id: d.name for d in db.scalars(select(Dataset).where(Dataset.id.in_([r.dataset_id for r in rows])))}
    return [_board_dict(r) | {"dataset_name": names.get(r.dataset_id)} for r in rows]


@app.post("/api/dashboards")
def create_dashboard(body: DashboardIn, db: Session = Depends(get_session), user: User = Depends(current_user)):
    d = get_or_404(db, Dataset, body.dataset_id, user)
    if body.project_id:
        get_or_404(db, Project, body.project_id, user)
    b = Dashboard(owner_id=user.id, name=body.name, dataset_id=d.id, project_id=body.project_id or d.project_id, tiles=_valid_tiles(body.tiles))
    db.add(b)
    db.commit()
    return _board_dict(b)


@app.get("/api/dashboards/{bid}")
def get_dashboard(bid: str, db: Session = Depends(get_session), user: User = Depends(current_user)):
    from .dashboards import render
    b = get_or_404(db, Dashboard, bid, user)
    return _board_dict(b) | render(db, b)


@app.patch("/api/dashboards/{bid}")
def update_dashboard(bid: str, body: DashboardPatch, db: Session = Depends(get_session), user: User = Depends(current_user)):
    b = get_or_404(db, Dashboard, bid, user)
    if body.name is not None:
        b.name = body.name
    if body.tiles is not None:
        b.tiles = _valid_tiles(body.tiles)
    b.updated_at = utcnow()
    db.commit()
    return _board_dict(b)


@app.post("/api/dashboards/{bid}/tiles")
def add_tile(bid: str, tile: dict[str, Any], db: Session = Depends(get_session), user: User = Depends(current_user)):
    b = get_or_404(db, Dashboard, bid, user)
    if len(b.tiles) >= 40:
        raise HTTPException(400, "A dashboard can hold at most 40 tiles.")
    b.tiles = list(b.tiles) + _valid_tiles([tile])
    b.updated_at = utcnow()
    db.commit()
    return _board_dict(b)


@app.delete("/api/dashboards/{bid}")
def delete_dashboard(bid: str, db: Session = Depends(get_session), user: User = Depends(current_user)):
    b = get_or_404(db, Dashboard, bid, user)
    db.delete(b)
    db.commit()
    return {"deleted": bid}


@app.get("/api/alerts")
def list_alerts(db: Session = Depends(get_session), user: User = Depends(current_user)):
    """Rule breaches recorded when a KPI tile was evaluated against a dataset version. Nothing here is simulated."""
    evs = db.scalars(select(MonitorEvent).where(MonitorEvent.owner_id == user.id, MonitorEvent.status == "breach").order_by(MonitorEvent.created_at.desc()).limit(50)).all()
    boards = {b.id: b for b in db.scalars(select(Dashboard).where(Dashboard.id.in_({e.dashboard_id for e in evs})))}
    out = []
    for e in evs:
        b = boards.get(e.dashboard_id)
        tile = next((t for t in (b.tiles if b else []) if t["id"] == e.tile_id), None)
        out.append({"id": e.id, "dashboard_id": e.dashboard_id, "dashboard": b.name if b else None, "tile": (tile or {}).get("title") or (tile or {}).get("question"),
                    "value": e.value, "message": e.message.rsplit(" [", 1)[0], "dataset_id": e.dataset_id, "created_at": e.created_at})
    return out


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
    return {"id": u.id, "email": u.email, "name": u.name or u.email.split("@")[0], "is_admin": u.is_admin, "disabled": u.disabled,
            "is_guest": bool(u.is_guest), "created_at": _iso(u.created_at)}


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


@app.post("/api/auth/guest")
def guest(response: FResponse, request: Request, db: Session = Depends(get_session)):
    """One-click demo: a throwaway account (deleted after GUEST_TTL_HOURS) with the retail demo already loaded."""
    import secrets
    auth.check_rate(request, "guest")
    auth.record_fail(request, "guest")  # counts towards the per-address limit so guests cannot be minted in bulk
    u = User(email=f"guest-{secrets.token_hex(6)}@guest.insightforge", name="Guest", password_hash=auth.hash_password(secrets.token_urlsafe(24)),
             is_admin=False, is_guest=True)
    db.add(u)
    db.commit()
    fn, label = DEMOS["retail"]
    raw = (DEMO_DIR / fn).read_bytes()
    d = _create_dataset(db, u, raw, fn, "csv", storage.parse_bytes(raw, "csv"), None, synthetic=True, name=label)
    auth.start_session(db, response, u)
    return {**user_dict(u), "dataset_id": d.id}


def purge_guests(db: Session) -> int:
    cutoff = utcnow() - timedelta(hours=settings.guest_ttl_hours)
    old = db.scalars(select(User).where(User.is_guest.is_(True), User.created_at < cutoff)).all()
    for u in old:
        _wipe_user(db, u.id)
        db.delete(u)
    db.commit()
    return len(old)


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
