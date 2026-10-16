from app.memory import record_outcome


def _rec(db, ns, sha, outcome="succeeded", verified=True, n=0):
    return record_outcome(db, namespace=ns, task_type="comparison", strategy="mann_whitney", outcome=outcome,
                          conditions={"skew": "high"}, signature={}, experiment_id=f"exp{n}", analysis_id=None,
                          dataset_sha=sha, metric=None, verified=verified, detail="")


def test_single_dataset_stays_candidate(db):
    l = _rec(db, "t1", "a" * 16, n=1)
    l = _rec(db, "t1", "a" * 16, n=2)
    assert l.status == "candidate"


def test_promotion_requires_two_datasets(db):
    _rec(db, "t2", "a" * 16, n=1)
    l = _rec(db, "t2", "b" * 16, n=2)
    assert l.status == "validated"
    assert len(l.versions) >= 2


def test_unverified_evidence_does_not_promote(db):
    _rec(db, "t3", "a" * 16, verified=False, n=1)
    l = _rec(db, "t3", "b" * 16, verified=False, n=2)
    assert l.status == "candidate"


def test_contradictions_block_validation(db):
    _rec(db, "t4", "a" * 16, n=1)
    l = _rec(db, "t4", "b" * 16, n=2)
    for i in range(3):
        _rec(db, "t4", f"{i}" * 16, outcome="failed", n=10 + i)
    db.refresh(l)
    assert l.status != "validated"
