"""Experience memory: failure-aware, validated lessons with provenance and version history.

Lifecycle
---------
1. Every experiment (one strategy attempt) produces evidence for a lesson keyed
   by (task type, strategy, outcome, discrete conditions).
2. New lessons start as *candidates*.
3. A candidate is promoted to *validated* only when ALL of these hold:
   - at least `MIN_SUPPORT` supporting experiments on at least 2 distinct datasets,
   - every counted piece of evidence passed independent verification,
   - contradictions (opposite outcome under the same conditions) are < 25% of evidence.
4. Contradicting evidence lowers confidence and can demote a validated lesson.
5. Users can edit or reject lessons; every change creates a new version.

Retrieval scores lessons by task type, condition match and numeric
dataset-signature similarity. Lessons only *re-order* candidate strategies; the
chosen strategy is still executed and verified, so a lesson can never
substitute for an analysis result.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import Lesson, LessonUsage, LessonVersion, utcnow

MIN_SUPPORT = 2
SIM_THRESHOLD = 0.55
SIG_KEYS = ["log_rows", "n_cols", "frac_numeric", "frac_categorical", "missing_pct", "minority_share", "target_skew"]
SIG_SCALE = {"log_rows": 2.0, "n_cols": 30.0, "frac_numeric": 1.0, "frac_categorical": 1.0, "missing_pct": 0.3, "minority_share": 0.5, "target_skew": 4.0}


def signature_similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    """1 - mean scaled absolute difference over shared numeric keys (0..1)."""
    diffs = []
    for k in SIG_KEYS:
        x, y = a.get(k), b.get(k)
        if x is None or y is None:
            continue
        diffs.append(min(1.0, abs(float(x) - float(y)) / SIG_SCALE[k]))
    if a.get("target_type") and b.get("target_type"):
        diffs.append(0.0 if a["target_type"] == b["target_type"] else 1.0)
    return round(1 - (sum(diffs) / len(diffs) if diffs else 0.5), 3)


def condition_match(a: dict[str, str], b: dict[str, str]) -> float:
    keys = set(a) & set(b)
    if not keys:
        return 0.5 if not a and not b else 0.0
    return sum(1 for k in keys if a[k] == b[k]) / max(len(set(a) | set(b)), 1)


def _snapshot(lesson: Lesson) -> dict[str, Any]:
    return {k: getattr(lesson, k) for k in ("statement", "status", "confidence", "support_count", "contradiction_count", "conditions", "outcome", "strategy")}


def _confidence(lesson: Lesson) -> float:
    verified = sum(1 for e in lesson.evidence if e.get("verified") and not e.get("contradicts"))
    s, c = verified, lesson.contradiction_count
    return round((s + 1) / (s + c + 2), 3)


def _statement(task_type: str, strategy: str, outcome: str, conditions: dict[str, str], detail: str) -> str:
    cond = ", ".join(f"{k.replace('_', ' ')} = {v}" for k, v in sorted(conditions.items())) or "any conditions"
    verb = "worked" if outcome == "success" else "failed"
    return f"For {task_type.replace('_', ' ')} tasks with {cond}, the '{strategy}' strategy {verb}. {detail}".strip()


def record_outcome(db: Session, *, namespace: str, task_type: str, strategy: str, outcome: str, conditions: dict[str, str],
                   signature: dict[str, Any], experiment_id: str, analysis_id: str | None, dataset_sha: str, metric: tuple[str, float] | None,
                   verified: bool, detail: str) -> Lesson:
    """Add one experiment's evidence. Creates/updates the matching lesson and its contradicting twin."""
    lessons = db.scalars(select(Lesson).where(Lesson.namespace == namespace, Lesson.task_type == task_type, Lesson.strategy == strategy)).all()
    same = [l for l in lessons if l.conditions == conditions and l.outcome == outcome and l.status != "rejected"]
    opposite = [l for l in lessons if l.conditions == conditions and l.outcome != outcome and l.status != "rejected"]
    ev = {"experiment_id": experiment_id, "analysis_id": analysis_id, "dataset_sha": dataset_sha[:16], "verified": bool(verified),
          "metric": metric[0] if metric else None, "value": metric[1] if metric else None, "at": utcnow().isoformat()}
    if same:
        lesson = same[0]
        lesson.evidence = lesson.evidence + [ev]
        lesson.support_count = lesson.support_count + 1
        if detail:
            lesson.statement = _statement(task_type, strategy, outcome, conditions, detail)
        reason = "new supporting evidence"
    else:
        lesson = Lesson(namespace=namespace, task_type=task_type, strategy=strategy, outcome=outcome, conditions=conditions, signature=signature,
                        statement=_statement(task_type, strategy, outcome, conditions, detail), evidence=[ev], support_count=1,
                        source_experiment_id=experiment_id, status="candidate")
        db.add(lesson)
        db.flush()
        reason = "created from experiment"
    for o in opposite:
        o.contradiction_count = o.contradiction_count + 1
        o.evidence = o.evidence + [{**ev, "contradicts": True}]
        _reevaluate(db, o, "contradicting evidence")
    _reevaluate(db, lesson, reason)
    return lesson


def _reevaluate(db: Session, lesson: Lesson, reason: str) -> None:
    prev = _snapshot(lesson)
    supporting = [e for e in lesson.evidence if not e.get("contradicts")]
    verified = [e for e in supporting if e.get("verified")]
    datasets = {e["dataset_sha"] for e in verified}
    total = len(supporting) + lesson.contradiction_count
    contra_rate = lesson.contradiction_count / total if total else 0
    lesson.confidence = _confidence(lesson)
    if lesson.status != "rejected" and not lesson.user_edited:
        if len(verified) >= MIN_SUPPORT and len(datasets) >= 2 and len(verified) == len(supporting) and contra_rate < 0.25:
            lesson.status = "validated"
        elif lesson.status == "validated" and (contra_rate >= 0.25 or len(verified) < len(supporting)):
            lesson.status = "candidate"
    snap = _snapshot(lesson)
    if not lesson.versions:
        lesson.version = 1
        lesson.versions.append(LessonVersion(version=1, snapshot=snap, changed_by="agent", reason=reason))
    elif snap != prev:
        lesson.version = (lesson.version or 1) + 1
        lesson.versions.append(LessonVersion(version=lesson.version, snapshot=snap, changed_by="agent", reason=reason))


def retrieve(db: Session, *, namespace: str, task_type: str, conditions: dict[str, str], signature: dict[str, Any], mode: str,
             limit: int = 8) -> list[dict[str, Any]]:
    """mode: 'ordinary' (any success lesson for the task type) or 'validated' (failure-aware, validated, condition-matched)."""
    q = select(Lesson).where(Lesson.namespace == namespace, Lesson.task_type == task_type, Lesson.status != "rejected")
    rows = db.scalars(q).all()
    out = []
    for l in rows:
        sim = signature_similarity(signature, l.signature or {})
        cm = condition_match(conditions, l.conditions or {})
        if mode == "ordinary":
            if l.outcome != "success":
                continue
            score = sim
        else:
            if l.status != "validated" or cm < 0.99 or sim < SIM_THRESHOLD:
                continue
            score = sim * l.confidence
        out.append({"lesson": l, "similarity": sim, "condition_match": cm, "score": round(score, 3)})
    out.sort(key=lambda r: (-r["score"], -(r["lesson"].support_count)))
    return out[:limit]


def rank_strategies(default_order: list[str], retrieved: list[dict[str, Any]], mode: str) -> tuple[list[str], list[str]]:
    """Return (ordered strategies, human-readable explanations)."""
    if not retrieved:
        return default_order, []
    notes = []
    if mode == "ordinary":
        # Ordinary retrieval: reuse the most similar previously successful strategy first.
        best = retrieved[0]["lesson"].strategy
        if best in default_order:
            notes.append(f"Reusing '{best}', which succeeded on the most similar past dataset (similarity {retrieved[0]['similarity']:.2f}).")
            return [best] + [s for s in default_order if s != best], notes
        return default_order, notes
    score = {s: 0.0 for s in default_order}
    for r in retrieved:
        l = r["lesson"]
        if l.strategy not in score:
            continue
        w = r["score"]
        score[l.strategy] += w if l.outcome == "success" else -w
        notes.append(f"{'Prefer' if l.outcome == 'success' else 'Avoid'} '{l.strategy}': validated lesson (confidence {l.confidence:.2f}, "
                     f"{l.support_count} supporting experiments, similarity {r['similarity']:.2f}).")
    ordered = sorted(default_order, key=lambda s: (-score[s], default_order.index(s)))
    return ordered, notes


def log_usage(db: Session, retrieved: list[dict[str, Any]], analysis_id: str | None, effect: str) -> None:
    for r in retrieved:
        l = r["lesson"]
        l.reuse_count = (l.reuse_count or 0) + 1
        db.add(LessonUsage(lesson_id=l.id, analysis_id=analysis_id, similarity=r["similarity"], effect=effect))


def user_update(db: Session, lesson: Lesson, changes: dict[str, Any], reason: str) -> Lesson:
    for k in ("statement", "status", "conditions"):
        if k in changes and changes[k] is not None:
            if k == "status" and changes[k] not in ("candidate", "validated", "rejected"):
                raise ValueError("status must be candidate, validated or rejected")
            setattr(lesson, k, changes[k])
    lesson.user_edited = True
    lesson.version = (lesson.version or 1) + 1
    lesson.versions.append(LessonVersion(version=lesson.version, snapshot=_snapshot(lesson), changed_by="user", reason=reason or "edited by user"))
    return lesson


def lesson_dict(l: Lesson, full: bool = False) -> dict[str, Any]:
    d = {
        "id": l.id, "task_type": l.task_type, "strategy": l.strategy, "outcome": l.outcome, "statement": l.statement,
        "conditions": l.conditions, "confidence": l.confidence, "status": l.status, "support_count": l.support_count,
        "contradiction_count": l.contradiction_count, "reuse_count": l.reuse_count, "version": l.version, "user_edited": l.user_edited,
        "source_experiment_id": l.source_experiment_id, "created_at": l.created_at.isoformat() if l.created_at else None,
        "updated_at": l.updated_at.isoformat() if l.updated_at else None,
        "verified_evidence": sum(1 for e in l.evidence if e.get("verified") and not e.get("contradicts")),
        "distinct_datasets": len({e["dataset_sha"] for e in l.evidence if not e.get("contradicts")}),
        "trust_reason": trust_reason(l),
    }
    if full:
        d["evidence"] = l.evidence
        d["signature"] = l.signature
        d["versions"] = [{"version": v.version, "changed_by": v.changed_by, "reason": v.reason, "snapshot": v.snapshot,
                          "created_at": v.created_at.isoformat()} for v in l.versions]
        d["usages"] = [{"analysis_id": u.analysis_id, "similarity": u.similarity, "effect": u.effect, "created_at": u.created_at.isoformat()} for u in l.usages]
    return d


def trust_reason(l: Lesson) -> str:
    sup = [e for e in l.evidence if not e.get("contradicts")]
    ver = [e for e in sup if e.get("verified")]
    ds = len({e["dataset_sha"] for e in ver})
    if l.status == "rejected":
        return "Rejected; never used for planning."
    if l.status == "validated":
        return (f"Validated: {len(ver)} independently verified experiments on {ds} datasets, "
                f"{l.contradiction_count} contradictions." + (" Status set by a user." if l.user_edited else ""))
    need = []
    if len(ver) < MIN_SUPPORT:
        need.append(f"{MIN_SUPPORT - len(ver)} more verified experiment(s)")
    if ds < 2:
        need.append("evidence from a second dataset")
    if len(ver) < len(sup):
        need.append("all evidence to pass verification")
    return "Candidate: needs " + (", ".join(need) if need else "lower contradiction rate") + " before it is used for planning."

