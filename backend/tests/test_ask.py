import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.ask import AskError, answer
from app.main import app
from app.profiler import profile_dataframe


def sales():
    return pd.DataFrame({
        "order_date": pd.date_range("2024-01-01", periods=120, freq="D").astype(str),
        "region": (["North", "South", "East"] * 40),
        "revenue": [float(i % 7 + 1) * 10 for i in range(120)],
        "quantity": [i % 4 + 1 for i in range(120)],
        "returned": ["yes" if i % 10 == 0 else "no" for i in range(120)],
    })


def ask(q, df=None):
    df = sales() if df is None else df
    return answer(df, profile_dataframe(df), q)


def test_total_by_group_matches_pandas():
    df = sales()
    r = ask("total revenue by region", df)
    expected = df.groupby("region")["revenue"].sum().sort_values(ascending=False)
    assert r["spec"]["agg"] == "sum" and r["spec"]["group_by"] == "region"
    assert [row["sum_revenue"] for row in r["rows"]] == pytest.approx(expected.tolist())
    assert r["chart"]["kind"] == "bar" and "groupby" in r["code"] and "GROUP BY" in r["sql"]


def test_filter_value_and_numeric_filter():
    df = sales()
    r = ask("average revenue in North where quantity > 2", df)
    m = df[(df.region == "North") & (df.quantity > 2)]["revenue"].mean()
    assert r["rows"][0]["mean_revenue"] == pytest.approx(m)
    assert r["rows_used"] == len(df[(df.region == "North") & (df.quantity > 2)])


def test_which_group_highest_uses_total_and_limit():
    r = ask("which region has the highest revenue")
    assert r["spec"]["limit"] == 1 and len(r["rows"]) == 1 and r["headline"].startswith(r["rows"][0]["region"])


def test_trend_by_month():
    r = ask("revenue by month")
    assert r["spec"]["op"] == "trend" and r["spec"]["grain"] == "month"
    assert [row["period"] for row in r["rows"]] == ["2024-01", "2024-02", "2024-03", "2024-04"]
    assert r["chart"]["kind"] == "line"


def test_correlation_distribution_rows_and_distinct():
    assert ask("correlation between revenue and quantity")["spec"]["op"] == "correlation"
    assert ask("distribution of revenue")["chart"]["kind"] == "bar"
    rows = ask("show top 3 orders by revenue")
    assert len(rows["rows"]) == 3 and rows["rows"][0]["revenue"] == 70.0
    assert ask("unique values of region")["rows"][0]["rows"] == 40


def test_boolean_count_and_unknown_column_errors():
    r = ask("how many returned orders")
    assert r["rows"][0]["rows"] == 12
    with pytest.raises(AskError):
        ask("which region has the lowest profit")
    with pytest.raises(AskError):
        ask("correlation between revenue and region")


def test_edited_spec_is_validated_and_code_is_what_runs():
    df = sales()
    prof = profile_dataframe(df)
    r = answer(df, prof, spec={"op": "aggregate", "measure": "revenue", "agg": "median", "group_by": "region", "filters": []})
    ns = {"df": df, "pd": pd}
    exec(r["code"], {}, ns)
    assert ns["result"].iloc[:, -1].tolist() == [row["median_revenue"] for row in r["rows"]]
    with pytest.raises(AskError):
        answer(df, prof, spec={"op": "aggregate", "measure": "nope", "agg": "sum"})
    with pytest.raises(AskError):
        answer(df, prof, spec={"op": "aggregate", "measure": "revenue", "agg": "sum", "filters": [{"column": "region", "op": "__import__", "value": 1}]})


def test_ask_api_history_and_privacy():
    c = TestClient(app)
    c.post("/api/auth/register", json={"email": "ask@x.com", "password": "secretpass1"})
    ds = c.post("/api/datasets/demo/retail").json()
    sug = c.get(f"/api/datasets/{ds['id']}/ask/suggestions").json()["suggestions"]
    assert sug
    r = c.post(f"/api/datasets/{ds['id']}/ask", json={"question": sug[0]})
    assert r.status_code == 200 and r.json()["rows"]
    assert c.post(f"/api/datasets/{ds['id']}/ask", json={"question": "total profit by region"}).status_code == 422
    hist = c.get(f"/api/datasets/{ds['id']}/ask/history").json()
    assert len(hist) == 1 and hist[0]["question"] == sug[0]
    assert c.post(f"/api/ask/{hist[0]['id']}/pin").json()["pinned"] is True
    other = TestClient(app)
    other.post("/api/auth/register", json={"email": "ask2@x.com", "password": "secretpass1"})
    assert other.post(f"/api/datasets/{ds['id']}/ask", json={"question": "total revenue"}).status_code == 404
    assert other.delete(f"/api/ask/{hist[0]['id']}").status_code == 404
