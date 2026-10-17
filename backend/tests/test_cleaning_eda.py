import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.cleaning import CleaningError, run_operations, side_by_side
from app.eda import bh_adjust, run_eda, summary_stats
from app.main import app
from app.profiler import profile_dataframe


def frame():
    return pd.DataFrame({
        "id": range(1, 9),
        "price": ["$1,000", "200", "300", "x", "500", "600", "700", "800"],
        "city": [" Pune", "pune", "Mumbai ", "Mumbai", "Delhi", "delhi", "Delhi", None],
        "qty": [1, 2, 2, 3, 100, 2, 1, 2],
        "when": ["2024-01-05", "05/02/2024", "2024-03-01", "bad", "2024-05-01", "2024-06-01", "2024-07-01", "2024-08-01"],
    })


def test_convert_type_reports_unconvertible_values():
    out, log = run_operations(frame(), [{"op": "convert_type", "column": "price", "to": "numeric", "reason": "stored as text"}])
    assert out["price"].tolist()[:3] == [1000, 200, 300]
    assert pd.isna(out["price"][3])
    assert log[0]["values_not_convertible"] == 1 and log[0]["warnings"]
    assert log[0]["reason"] == "stored as text" and log[0]["after"]["dtype"] != log[0]["before"]["dtype"]


def test_parse_dates_keeps_unparsed_values():
    out, log = run_operations(frame(), [{"op": "parse_dates", "column": "when"}])
    assert out["when"][0] == "2024-01-05" and out["when"][3] == "bad"  # never silently discarded
    assert log[0]["unparsed"] == 1


def test_text_and_categories_then_cap_and_remove_outliers():
    df = frame()
    out, log = run_operations(df, [{"op": "normalize_text", "column": "city", "case": "title"},
                                   {"op": "cap_outliers", "column": "qty", "k": 1.5}])
    assert set(out["city"].dropna()) == {"Pune", "Mumbai", "Delhi"}
    assert out["qty"].max() < 100 and log[1]["values_capped"] == 1
    assert len(df) == len(out)  # original untouched, no rows lost
    out2, log2 = run_operations(df, [{"op": "remove_outliers", "column": "qty", "k": 1.5}])
    assert len(out2) == 7 and log2[0]["rows_removed"] == 1


def test_rename_drop_fill_replace_and_errors():
    out, log = run_operations(frame(), [{"op": "rename_column", "column": "qty", "new_name": "units"},
                                        {"op": "fill_missing", "column": "city", "method": "constant", "value": "Unknown"},
                                        {"op": "replace_value", "column": "units", "old": "100", "new": ""},
                                        {"op": "drop_column", "column": "id"}])
    assert "units" in out and "id" not in out and out["city"].isna().sum() == 0 and out["units"].isna().sum() == 1
    with pytest.raises(CleaningError):
        run_operations(frame(), [{"op": "rename_column", "column": "qty", "new_name": "city"}])
    with pytest.raises(CleaningError):
        run_operations(frame(), [{"op": "nope"}])


def test_side_by_side_shows_changed_rows():
    df = frame()
    out, log = run_operations(df, [{"op": "normalize_text", "column": "city", "case": "lower"}])
    sbs = side_by_side(df, out, log)
    assert sbs["aligned"] and sbs["changed_rows"] == 5


def test_profiler_flags_text_numbers_constant_and_redundant():
    df = frame().assign(const=1, qty2=lambda d: d["qty"] * 2)
    df = pd.concat([df] * 5, ignore_index=True)
    kinds = {(i["kind"], i["column"]) for i in profile_dataframe(df)["issues"]}
    assert ("numeric_as_text", "price") in kinds
    assert ("constant_column", "const") in kinds
    assert ("redundant_column", "qty2") in kinds
    assert ("whitespace", "city") in kinds


def test_summary_stats_known_values():
    df = pd.DataFrame({"x": [1, 2, 2, 3, 4, 100]})
    r = summary_stats(df, ["x"])[0]
    assert r["mean"] == pytest.approx(112 / 6) and r["median"] == 2.5 and r["mode"] == 2
    assert r["variance"] == pytest.approx(np.var([1, 2, 2, 3, 4, 100], ddof=1))
    assert r["outliers_iqr"] == 1


def test_bh_adjust_matches_definition():
    q = bh_adjust([0.01, 0.04, 0.03, 0.5])
    assert q == pytest.approx([0.04, 0.0533333, 0.0533333, 0.5], rel=1e-4)


def test_eda_finds_planted_patterns():
    rng = np.random.default_rng(0)
    n = 600
    g = rng.choice(["A", "B", "C"], n)
    sales = np.where(g == "A", 300, 100) + rng.normal(0, 20, n)
    df = pd.DataFrame({"date": pd.date_range("2023-01-01", periods=n, freq="D").strftime("%Y-%m-%d"), "region": g,
                       "sales": sales + np.arange(n) * 0.5, "noise": rng.normal(size=n)})
    res = run_eda(df, profile_dataframe(df))
    kinds = {i["kind"] for i in res["insights"]}
    assert "group_difference" in kinds and "trend" in kinds
    gd = next(i for i in res["insights"] if i["kind"] == "group_difference")
    assert "A" in gd["detail"] and gd["evidence"]["q_value"] < 0.001
    assert res["trend"]["trend"]["rho"] > 0.5
    # nothing claims the random column is related to sales
    assert not any("noise" in i["title"] for i in res["insights"] if i["kind"] == "correlation")


def test_clean_endpoints_create_version_and_keep_original():
    c = TestClient(app)
    c.post("/api/auth/register", json={"email": "clean@x.com", "password": "secretpass1"})
    ds = c.post("/api/datasets/demo/retail").json()
    ops = [{"op": "drop_duplicates", "reason": "exact repeats"}, {"op": "normalize_categories", "column": "region"}]
    pv = c.post(f"/api/datasets/{ds['id']}/clean/preview", json={"operations": ops}).json()
    assert pv["rows_after"] == ds["n_rows"] - 18 and pv["log"][1]["values_changed"] > 0
    assert c.post(f"/api/datasets/{ds['id']}/clean", json={"operations": ops}).status_code == 400  # needs confirm
    nd = c.post(f"/api/datasets/{ds['id']}/clean", json={"operations": ops, "confirm": True}).json()
    assert nd["parent_id"] == ds["id"] and nd["n_rows"] == ds["n_rows"] - 18
    lin = c.get(f"/api/datasets/{nd['id']}/lineage").json()
    assert [x["id"] for x in lin["chain"]] == [ds["id"], nd["id"]] and lin["history"][0]["operations"][0]["reason"] == "exact repeats"
    assert c.get(f"/api/datasets/{ds['id']}").json()["n_rows"] == ds["n_rows"]  # original preserved
    csv = c.get(f"/api/datasets/{nd['id']}/download?format=csv")
    assert csv.status_code == 200 and csv.text.count("\n") == nd["n_rows"] + 1
    assert c.get(f"/api/datasets/{nd['id']}/download?format=xlsx").content[:2] == b"PK"
    eda = c.get(f"/api/datasets/{nd['id']}/eda").json()
    assert eda["measure"] == "revenue" and eda["insights"] and eda["kpis"][0]["value"] == nd["n_rows"]
