"""Dashboards and KPI monitoring.

Tiles store a validated Ask spec, never a stored number: rendering re-runs the
spec on the latest version of the dataset (following cleaning and uploaded
versions). A KPI tile may carry a rule (value above/below a threshold, or a
percentage change from the previous version). Each evaluation against a new
dataset version is recorded as a MonitorEvent; alerts are only those events,
so nothing is ever shown that was not computed from real data.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import storage
from .ask import AskError, answer
from .db import Dashboard, Dataset, MonitorEvent, new_id

RULE_OPS = (">", ">=", "<", "<=", "change_pct_above", "change_pct_below")


def version_chain(db: Session, d: Dataset) -> list[Dataset]:
    """All versions in d's lineage (root first, by creation time)."""
    root = d
    seen = {d.id}
    while root.parent_id and root.parent_id not in seen:
        parent = db.get(Dataset, root.parent_id)
        if parent is None or parent.owner_id != d.owner_id:
            break
        seen.add(parent.id)
        root = parent
    out, frontier = [root], [root.id]
    while frontier:
        kids = db.scalars(select(Dataset).where(Dataset.parent_id.in_(frontier), Dataset.owner_id == d.owner_id)).all()
        kids = [k for k in kids if k.id not in {o.id for o in out}]
        out += kids
        frontier = [k.id for k in kids]
    return sorted(out, key=lambda x: x.created_at)


def latest_version(db: Session, d: Dataset) -> Dataset:
    return version_chain(db, d)[-1]


def clean_tile(t: dict[str, Any]) -> dict[str, Any]:
    kind = t.get("kind", "ask")
    if kind not in ("ask", "kpi", "note"):
        raise AskError("Unknown tile type.")
    tile = {"id": t.get("id") or new_id("t"), "kind": kind, "title": str(t.get("title") or "")[:120], "size": "wide" if t.get("size") == "wide" else "normal"}
    if kind == "note":
        tile["text"] = str(t.get("text") or "")[:2000]
        return tile
    if not isinstance(t.get("spec"), dict):
        raise AskError("A tile needs a query spec.")
    tile["spec"] = t["spec"]
    tile["question"] = str(t.get("question") or "")[:500]
    rule = t.get("rule")
    if kind == "kpi" and rule:
        if rule.get("op") not in RULE_OPS:
            raise AskError("Unknown rule.")
        tile["rule"] = {"op": rule["op"], "threshold": float(rule["threshold"])}
    return tile


def _scalar(res: dict[str, Any]) -> float | None:
    if res.get("rows") and len(res["rows"]) == 1 and len(res["columns"]) == 1:
        v = res["rows"][0][res["columns"][0]]
        return float(v) if isinstance(v, (int, float)) else None
    return None


def _check(rule: dict[str, Any], value: float, previous: float | None) -> tuple[str, str]:
    op, th = rule["op"], rule["threshold"]
    if op in ("change_pct_above", "change_pct_below"):
        if previous in (None, 0):
            return "ok", "No earlier version to compare with yet."
        ch = (value - previous) / abs(previous) * 100
        bad = ch > th if op == "change_pct_above" else ch < th
        return ("breach" if bad else "ok"), f"Changed {ch:+.1f}% from the previous version (rule: {'above' if op == 'change_pct_above' else 'below'} {th:+g}%)."
    bad = {">": value > th, ">=": value >= th, "<": value < th, "<=": value <= th}[op]
    return ("breach" if bad else "ok"), f"Value {value:,.4g} {'meets' if bad else 'does not meet'} the alert rule {op} {th:,.4g}."


def render(db: Session, board: Dashboard) -> dict[str, Any]:
    base = db.get(Dataset, board.dataset_id)
    cur = latest_version(db, base)
    df = storage.load_dataset(cur.id)
    profile = cur.profile or {}
    tiles = []
    for t in board.tiles:
        out = dict(t)
        if t["kind"] == "note":
            tiles.append(out)
            continue
        try:
            res = answer(df, profile, t.get("question"), t["spec"])
            out["result"] = {k: res[k] for k in ("headline", "chart", "columns", "rows", "interpretation", "warnings", "code", "rows_used")}
            out["result"]["rows"] = res["rows"][:50]
            value = _scalar(res)
            out["value"] = value
            if t["kind"] == "kpi" and t.get("rule") and value is not None:
                out["monitor"] = _evaluate(db, board, t, cur, value)
        except AskError as exc:
            out["error"] = f"This tile no longer works on the latest data: {exc}"
        except storage.DatasetFileMissing:
            raise
        tiles.append(out)
    return {"dataset": {"id": cur.id, "name": cur.name, "n_rows": cur.n_rows, "created_at": cur.created_at, "sha256": cur.sha256,
                        "is_latest_of": base.id if cur.id != base.id else None},
            "versions": len(version_chain(db, base)), "tiles": tiles}


def _evaluate(db: Session, board: Dashboard, tile: dict[str, Any], ds: Dataset, value: float) -> dict[str, Any]:
    """Record one evaluation per (tile, dataset version); later renders reuse it."""
    events = db.scalars(select(MonitorEvent).where(MonitorEvent.dashboard_id == board.id, MonitorEvent.tile_id == tile["id"])
                        .order_by(MonitorEvent.created_at)).all()
    same = next((e for e in events if e.dataset_sha == ds.sha256 and e.dataset_id == ds.id), None)
    rule_key = f"{tile['rule']['op']}:{tile['rule']['threshold']}"
    if same and same.message.endswith(f"[{rule_key}]"):
        ev = same
    else:
        prev = next((e.value for e in reversed(events) if e.dataset_id != ds.id and e.value is not None), None)
        status, msg = _check(tile["rule"], value, prev)
        ev = MonitorEvent(owner_id=board.owner_id, dashboard_id=board.id, tile_id=tile["id"], dataset_id=ds.id, dataset_sha=ds.sha256,
                          value=value, status=status, message=f"{msg} [{rule_key}]")
        db.add(ev)
        db.commit()
    return {"status": ev.status, "message": ev.message.rsplit(" [", 1)[0], "evaluated_at": ev.created_at,
            "history": [{"value": e.value, "status": e.status, "at": e.created_at, "dataset_id": e.dataset_id} for e in events[-12:]] +
                       ([] if ev in events else [{"value": ev.value, "status": ev.status, "at": ev.created_at, "dataset_id": ev.dataset_id}])}
