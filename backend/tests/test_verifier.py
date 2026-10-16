import pandas as pd

from app.verifier import Verifier, check_narrative


def test_recompute_and_mismatch():
    df = pd.DataFrame({"g": ["a", "a", "b"], "v": [1.0, 3.0, 10.0]})
    v = Verifier(df, {}, {})
    good = {"id": "c1", "statement": "mean a", "value": 2.0, "check": {"kind": "group_agg", "group": "g", "key": "a", "column": "v", "op": "mean"}}
    bad = {**good, "id": "c2", "value": 2.5}
    out = v.verify("descriptive", {"claims": [good, bad], "artifacts": {}}, [])
    status = {c["id"]: c["status"] for c in out["checks"]}
    assert status["claim:c1"] == "pass"
    assert status["claim:c2"] == "fail"


def test_narrative_flags_invented_numbers():
    assert check_narrative("Profit fell 18.6% to $74.4k", [18.6, 74400]) == []
    assert check_narrative("Profit fell 42%", [18.6]) == ["42%"]
