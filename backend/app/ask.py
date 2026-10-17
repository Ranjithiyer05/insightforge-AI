"""Ask your data: natural-language questions answered with real pandas code.

A question is parsed into a small, validated query spec (operation, measure,
aggregation, grouping, filters, time grain, limit). The spec is compiled into
pandas code, which is the exact code executed to produce the answer, plus an
equivalent SQL statement for reference. Every interpretation choice the parser
makes is reported as an assumption so the user can correct it.

An LLM, when configured, may only propose a spec (validated against the
schema like any other) and never computes numbers.
"""
from __future__ import annotations

import difflib
import re
from typing import Any

import numpy as np
import pandas as pd

from .eda import pick_date, pick_measure
from .profiler import _finite

AGGS = {"sum": "sum", "mean": "mean", "median": "median", "min": "min", "max": "max", "count": "count", "nunique": "nunique"}
OPS = ("aggregate", "trend", "correlation", "distribution", "rows", "distinct")
GRAINS = {"day": "D", "week": "W", "month": "M", "quarter": "Q", "year": "Y"}
FILTER_OPS = ("==", "!=", ">", ">=", "<", "<=", "contains")
MAX_RESULT_ROWS = 500

AGG_WORDS = [
    (r"\b(total|sum of|sum)\b", "sum"), (r"\b(average|avg|mean)\b", "mean"), (r"\bmedian\b", "median"),
    (r"\b(how many|number of|count of|count)\b", "count"), (r"\b(maximum|max|largest|biggest)\b", "max"),
    (r"\b(minimum|min|smallest)\b", "min"),
]
GRAIN_WORDS = [
    (r"\b(daily|per day|by day|each day)\b", "day"), (r"\b(weekly|per week|by week|each week)\b", "week"),
    (r"\b(monthly|per month|by month|each month)\b", "month"), (r"\b(quarterly|per quarter|by quarter)\b", "quarter"),
    (r"\b(yearly|annual|annually|per year|by year|each year)\b", "year"),
]
CMP_WORDS = [
    (r"(>=|at least|no less than)", ">="), (r"(<=|at most|no more than)", "<="),
    (r"(>|greater than|more than|above|over|exceeds?)", ">"), (r"(<|less than|fewer than|below|under)", "<"),
    (r"(!=|not equal to|is not)", "!="), (r"(==|=|equals?|is)", "=="),
]


class AskError(ValueError):
    pass


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s).lower()).strip()


def _num(v: Any) -> Any:
    v = _finite(v)
    if isinstance(v, float):
        return round(v, 6)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, pd.Timestamp):
        return v.isoformat()
    return v


class Schema:
    def __init__(self, df: pd.DataFrame, profile: dict[str, Any]):
        self.cols = [str(c) for c in df.columns]
        types = {c["name"]: c.get("semantic_type") for c in profile.get("columns", [])}
        self.types = types
        self.numeric = [c for c in self.cols if c in set(profile.get("numeric_columns", []))
                        or (types.get(c) == "categorical_numeric" and pd.to_numeric(df[c], errors="coerce").notna().mean() > 0.9)
                        or (c not in types and pd.api.types.is_numeric_dtype(df[c]))]
        self.boolean = [c for c in self.cols if types.get(c) == "boolean"]
        self.revenue_like = set(profile.get("roles", {}).get("revenue", []))
        self.dates = [c for c in profile.get("datetime_columns", []) if c in self.cols]
        ids = set(profile.get("identifier_columns", []))
        self.categorical = [c for c in self.cols if c not in self.numeric and c not in self.dates and c not in ids
                            and types.get(c) not in ("text", "empty")] + \
                           [c for c in self.numeric if types.get(c) == "categorical_numeric"]
        self.measure = pick_measure(profile) or (self.numeric[0] if self.numeric else None)
        self.date = pick_date(profile)
        # values of low-cardinality columns, for matching "in North" style filters
        self.values: dict[str, list[str]] = {}
        for c in self.categorical:
            vc = df[c].dropna().astype(str)
            if vc.nunique() <= 300:
                # longest first; among equal names the cleanly formatted spelling wins
                self.values[c] = sorted(vc.unique().tolist(), key=lambda v: (-len(v.strip()), v != v.strip(), not v[:1].isupper()))

    def find_columns(self, text: str) -> list[tuple[int, str]]:
        """Columns mentioned in text, as (position, column), longest names first."""
        t = f" {_norm(text)} "
        hits: list[tuple[int, str]] = []
        taken: list[tuple[int, int]] = []
        for c in sorted(self.cols, key=lambda x: len(_norm(x)), reverse=True):
            for form in {_norm(c), _norm(c).rstrip("s"), _norm(c) + "s"}:
                if not form:
                    continue
                m = re.search(rf"\b{re.escape(form)}\b", t)
                if m and not any(a <= m.start() < b for a, b in taken):
                    hits.append((m.start(), c))
                    taken.append((m.start(), m.end()))
                    break
        return sorted(hits)

    def match_column(self, phrase: str, pool: list[str] | None = None) -> str | None:
        pool = pool or self.cols
        p = _norm(phrase)
        if not p:
            return None
        exact = [c for c in pool if _norm(c) in (p, p.rstrip("s"))]
        if exact:
            return exact[0]
        normed = {_norm(c): c for c in pool}
        close = difflib.get_close_matches(p, list(normed), n=1, cutoff=0.75)
        if close:
            return normed[close[0]]
        part = [c for c in pool if p in _norm(c) or (_norm(c) in p and len(_norm(c)) > 2)]
        return part[0] if len(part) == 1 else None


def parse(question: str, schema: Schema) -> dict[str, Any]:
    """Deterministic question -> spec. Returns spec with `assumptions` and `confidence`."""
    q = question.strip()
    low = q.lower()
    assumptions: list[str] = []
    spec: dict[str, Any] = {"op": "aggregate", "measure": None, "agg": None, "group_by": None, "filters": [],
                            "date_col": None, "grain": None, "limit": None, "sort": "desc", "columns": None}
    mentioned = [c for _, c in schema.find_columns(q)]
    confidence = 0.5 + (0.2 if mentioned else 0)

    # filters first, so the columns they use are not reused as measure/group
    used_in_filters: set[str] = set()
    for col in schema.cols:
        form = _norm(col)
        for pat, op in CMP_WORDS:
            m = re.search(rf"\b{re.escape(form)}s?\s+{pat}\s+(-?[\d,]*\.?\d+)", _norm_keep_ops(low))
            if m and col in schema.numeric:
                spec["filters"].append({"column": col, "op": op, "value": float(m.group(m.lastindex).replace(",", ""))})
                used_in_filters.add(col)
                break
    for col, vals in schema.values.items():
        for v in vals:
            nv = _norm(v)
            if len(nv) < 2 or nv.isdigit():
                continue
            if re.search(rf"\b(in|for|from|where|only|of|at|is|=)\s+(the\s+)?{re.escape(nv)}\b", _norm(low)) or \
                    re.search(rf"\b{re.escape(_norm(col))}\s+(is\s+|equals?\s+|=\s+)?{re.escape(nv)}\b", _norm(low)):
                neg = re.search(rf"\b(not|except|excluding|other than)\s+(in\s+)?{re.escape(nv)}\b", _norm(low))
                spec["filters"].append({"column": col, "op": "!=" if neg else "==", "value": v})
                used_in_filters.add(col)
                assumptions.append(f"Read “{v}” as a value of {col}.")
                break

    for col in schema.boolean:
        form = _norm(col)
        if col not in used_in_filters and re.search(rf"\b{re.escape(form)}\b", _norm(low)) and \
                re.search(r"\b(how many|number of|count)\b", low) and not re.search(rf"\bby\s+{re.escape(form)}\b", _norm(low)):
            truthy = next((v for v in schema.values.get(col, []) if _norm(v) in ("true", "1", "yes", "y")), None)
            if truthy is not None:
                neg = re.search(rf"\b(not|non|never)\s+{re.escape(form)}\b", _norm(low))
                spec["filters"].append({"column": col, "op": "!=" if neg else "==", "value": truthy})
                used_in_filters.add(col)
                assumptions.append(f"Counted rows where {col} is {truthy}" + (" (negated)." if neg else "."))

    # operation
    if re.search(r"\b(correlat\w*|relationship|relate|associated|association)\b", low):
        spec["op"] = "correlation"
        nums = [c for c in mentioned if c in schema.numeric and c not in used_in_filters]
        spec["columns"] = nums[:2]
        if len(nums) < 2:
            raise AskError("A correlation needs two numeric columns. Name both, for example “correlation between price and quantity”.")
        return _finish(spec, assumptions, 0.9)
    if re.search(r"\b(distinct|unique)\b", low) and not re.search(r"\b(how many|number of|count)\b", low):
        col = next((c for c in mentioned if c not in used_in_filters), None)
        if not col:
            raise AskError("Say which column to list unique values for.")
        spec.update(op="distinct", columns=[col])
        return _finish(spec, assumptions, 0.85)
    if re.search(r"\b(distribution|histogram|spread|describe|summary of|summari[sz]e)\b", low):
        col = next((c for c in mentioned if c in schema.numeric and c not in used_in_filters), None)
        if col:
            spec.update(op="distribution", columns=[col])
            return _finish(spec, assumptions, 0.85)
    if re.search(r"^\s*(show|list|give me|display|find)\b.*\b(rows|records|orders|transactions|entries)\b", low) or \
            re.search(r"\b(rows|records) (where|with)\b", low):
        spec.update(op="rows")
        m = re.search(r"\b(?:top|first|last|bottom)\s+(\d+)\b", low)
        spec["limit"] = int(m.group(1)) if m else 50
        sort_col = next((c for c in mentioned if c in schema.numeric and c not in used_in_filters), None)
        if sort_col and re.search(r"\b(top|highest|largest|biggest|most)\b", low):
            spec["columns"], spec["sort"] = [sort_col], "desc"
        elif sort_col and re.search(r"\b(bottom|lowest|smallest|least)\b", low):
            spec["columns"], spec["sort"] = [sort_col], "asc"
        return _finish(spec, assumptions, 0.75)

    # aggregation word
    for pat, agg in AGG_WORDS:
        if re.search(pat, low):
            spec["agg"] = agg
            break
    if re.search(r"\b(how many|number of|count)\b.*\b(unique|distinct|different)\b", low):
        spec["agg"] = "nunique"

    # grouping: "by X", "per X", "for each X", "across X", "which X"
    group = None
    tn = re.search(r"\b(?:top|bottom|best|worst)\s+\d+\s+([a-z0-9_ ]{2,40}?)\s+(?:by|for|in terms of)\b", low)
    if tn:
        hit = [c for pos, c in schema.find_columns(tn.group(1)) if pos <= 2 and c not in used_in_filters]
        group = hit[0] if hit else None
    for m in ([] if group else re.finditer(r"\b(?:by|per|for each|for every|each|across|among|between|which|what)\s+([a-z0-9_ ]{2,40})", low)):
        phrase = m.group(1)
        hit = schema.find_columns(phrase)
        cand = [c for pos, c in hit if pos <= 2 and c not in used_in_filters and (c not in schema.numeric or c in schema.categorical)]
        if cand:
            group = cand[0]
            break
    grain = next((g for pat, g in GRAIN_WORDS if re.search(pat, low)), None)
    trendish = re.search(r"\b(over time|trend|trends|trending|grow|growth|change over|timeline|history)\b", low)
    if group in schema.dates:
        grain = grain or "month"
        spec["date_col"], group = group, None
    if grain or trendish:
        if not schema.dates:
            raise AskError("This dataset has no date column, so a trend over time cannot be computed.")
        spec["op"] = "trend"
        spec["date_col"] = spec["date_col"] or next((c for c in mentioned if c in schema.dates), schema.date)
        if not grain:
            assumptions.append("No time grain given; using months.")
        spec["grain"] = grain or "month"

    # measure: first mentioned numeric column not used as group/filter
    measure = next((c for c in mentioned if c in schema.numeric and c not in (group,) and c not in used_in_filters), None)
    if not measure:
        # a word after an aggregation or superlative that names no column: say so rather than guess
        w = re.search(r"\b(?:total|average|avg|mean|median|sum of|highest|lowest|most|least|max|min|maximum|minimum)\s+(?:the\s+)?([a-z][a-z_]{2,})", low)
        word = w.group(1) if w else None
        if word and word not in ("rows", "number", "count", "records", "amount", "value", "sales", "revenue", "spend", "income", "of", "per", "by", "in"):
            measure = schema.match_column(word, schema.numeric)
            if measure:
                assumptions.append(f"Matched “{word}” to the column {measure}.")
            elif not schema.match_column(word):
                raise AskError(f"No column matches “{word}”. Numeric columns are: {', '.join(schema.numeric[:12])}.")
    if spec["agg"] in ("count",) and not measure:
        spec["measure"] = None
    elif spec["agg"] == "nunique":
        target = next((c for c in mentioned if c != group and c not in used_in_filters), None)
        if not target:
            w = re.search(r"\b(?:unique|distinct|different)\s+([a-z][a-z_ ]{2,30})", low)
            target = schema.match_column(w.group(1).split()[0]) if w else None
            if target:
                assumptions.append(f"Matched “{w.group(1).split()[0]}” to the column {target}.")
        if not target:
            raise AskError("Say which column to count distinct values of.")
        spec["measure"] = target
    else:
        if not measure:
            if re.search(r"\b(sales|revenue|amount|value|spend|income)\b", low) and schema.measure in schema.revenue_like:
                measure = schema.measure
                assumptions.append(f"Used {measure} as the measure for “{re.search(r'(sales|revenue|amount|value|spend|income)', low).group(1)}”.")
            elif re.search(r"\b(sales|revenue|spend|income)\b", low):
                raise AskError(f"This dataset has no revenue or sales column. Numeric columns are: {', '.join(schema.numeric[:12])}.")
            elif spec["agg"] is None and (group or spec["op"] == "trend"):
                spec["agg"] = "count"
                assumptions.append("No numeric column named; counting rows.")
            elif schema.measure:
                measure = schema.measure
                assumptions.append(f"No measure named; used {measure}.")
                confidence -= 0.2
        spec["measure"] = measure
    if spec["agg"] is None:
        spec["agg"] = "sum" if spec["measure"] else "count"
        if spec["measure"]:
            assumptions.append(f"No aggregation named; using the total (sum) of {spec['measure']}.")
    if spec["agg"] in ("sum", "mean", "median", "min", "max") and not spec["measure"]:
        raise AskError("Name the numeric column to aggregate, for example “average revenue by region”.")

    # top/bottom N and "which X has the highest"
    m = re.search(r"\b(top|bottom|best|worst|highest|lowest|first|last)\s+(\d+)\b", low)
    if m:
        spec["limit"] = int(m.group(2))
        spec["sort"] = "asc" if m.group(1) in ("bottom", "worst", "lowest") else "desc"
    elif re.search(r"\b(which|what)\b.*\b(highest|most|top|best|largest|biggest)\b", low) and group:
        spec["limit"], spec["sort"] = 1, "desc"
    elif re.search(r"\b(which|what)\b.*\b(lowest|least|worst|smallest|fewest)\b", low) and group:
        spec["limit"], spec["sort"] = 1, "asc"
    if spec["agg"] in ("max", "min") and group and re.search(r"\b(highest|lowest|largest|smallest)\b", low) and spec["limit"] == 1:
        # "which region has the highest revenue" means the highest total, not the highest single row
        spec["agg"] = "sum"
        assumptions.append("Compared groups by their total.")
    spec["group_by"] = group
    if group:
        confidence += 0.1
    return _finish(spec, assumptions, confidence)


def _norm_keep_ops(s: str) -> str:
    return re.sub(r"[^a-z0-9<>=!.,\- ]+", " ", s.replace("_", " ")).strip()


def _finish(spec: dict[str, Any], assumptions: list[str], confidence: float) -> dict[str, Any]:
    spec["assumptions"] = assumptions
    spec["confidence"] = round(max(0.1, min(0.95, confidence)), 2)
    return spec


def validate(spec: dict[str, Any], schema: Schema) -> dict[str, Any]:
    """Check a spec (from the parser, the UI editor or an LLM) against the schema."""
    s = {k: spec.get(k) for k in ("op", "measure", "agg", "group_by", "filters", "date_col", "grain", "limit", "sort", "columns")}
    if s["op"] not in OPS:
        raise AskError(f"Unknown operation {s['op']!r}.")
    for k in ("measure", "group_by", "date_col"):
        if s[k] is not None and s[k] not in schema.cols:
            raise AskError(f"Column {s[k]!r} is not in this dataset.")
    s["columns"] = [c for c in (s["columns"] or []) if c in schema.cols]
    if s["agg"] is not None and s["agg"] not in AGGS:
        raise AskError(f"Unknown aggregation {s['agg']!r}.")
    if s["agg"] in ("sum", "mean", "median") and s["measure"] not in schema.numeric:
        raise AskError(f"{s['measure']} is not numeric, so it cannot be summed or averaged.")
    if s["op"] == "trend" and (s["date_col"] not in schema.dates or s["grain"] not in GRAINS):
        raise AskError("A trend needs a date column and a grain (day, week, month, quarter or year).")
    if s["op"] == "correlation" and (len(s["columns"]) != 2 or any(c not in schema.numeric for c in s["columns"])):
        raise AskError("A correlation needs exactly two numeric columns.")
    filters = []
    for f in s["filters"] or []:
        if f.get("column") not in schema.cols or f.get("op") not in FILTER_OPS:
            raise AskError(f"Invalid filter {f!r}.")
        filters.append({"column": f["column"], "op": f["op"], "value": f.get("value")})
    s["filters"] = filters
    s["limit"] = int(s["limit"]) if s["limit"] else None
    if s["limit"] is not None and not 1 <= s["limit"] <= MAX_RESULT_ROWS:
        raise AskError(f"Limit must be between 1 and {MAX_RESULT_ROWS}.")
    s["sort"] = "asc" if s["sort"] == "asc" else "desc"
    return s


def _lit(v: Any) -> str:
    return repr(v)


def compile_pandas(s: dict[str, Any]) -> str:
    """Pandas code for a validated spec. This exact code is executed."""
    L = ["# df is the stored dataset (pandas DataFrame)", "d = df"]
    for f in s["filters"]:
        c = _lit(f["column"])
        if f["op"] == "contains":
            L.append(f"d = d[d[{c}].astype(str).str.contains({_lit(str(f['value']))}, case=False, na=False)]")
        elif isinstance(f["value"], (int, float)):
            L.append(f"d = d[pd.to_numeric(d[{c}], errors='coerce') {f['op']} {f['value']!r}]")
        else:
            L.append(f"d = d[d[{c}].astype(str) {f['op']} {_lit(str(f['value']))}]")
    op, m, agg, g = s["op"], s["measure"], s["agg"], s["group_by"]
    asc = s["sort"] == "asc"
    if op == "aggregate":
        if agg == "count" and not m:
            if g:
                L.append(f"result = d.groupby({_lit(g)}, dropna=False).size().rename('rows').reset_index()")
                L.append(f"result = result.sort_values('rows', ascending={asc})")
            else:
                L.append("result = pd.DataFrame({'rows': [len(d)]})")
        else:
            val = f"pd.to_numeric(d[{_lit(m)}], errors='coerce')" if agg not in ("count", "nunique") else f"d[{_lit(m)}]"
            name = f"{agg}_{m}"
            if g:
                L.append(f"result = {val}.groupby(d[{_lit(g)}], dropna=False).agg({_lit(agg)}).rename({_lit(name)}).reset_index()")
                L.append(f"result = result.sort_values({_lit(name)}, ascending={asc})")
            else:
                L.append(f"result = pd.DataFrame({{{_lit(name)}: [{val}.agg({_lit(agg)})]}})")
        if s["limit"] and g:
            L.append(f"result = result.head({s['limit']})")
    elif op == "trend":
        dc = _lit(s["date_col"])
        L.append(f"when = pd.to_datetime(d[{dc}], errors='coerce')")
        L.append(f"period = when.dt.to_period({_lit(GRAINS[s['grain']])}).astype(str)")
        L.append("keep = when.notna()")
        gk = "[period[keep]]" if not g else f"[period[keep], d[{_lit(g)}][keep]]"
        if agg == "count" and not m:
            L.append(f"result = d[keep].groupby({gk}).size().rename('rows').reset_index()")
        else:
            val = f"pd.to_numeric(d[{_lit(m)}], errors='coerce')" if agg not in ("count", "nunique") else f"d[{_lit(m)}]"
            L.append(f"result = {val}[keep].groupby({gk}).agg({_lit(agg)}).rename({_lit(f'{agg}_{m}')}).reset_index()")
        L.append("result = result.rename(columns={result.columns[0]: 'period'}).sort_values('period')")
    elif op == "correlation":
        a, b = (_lit(c) for c in s["columns"])
        L.append(f"x = pd.to_numeric(d[{a}], errors='coerce'); y = pd.to_numeric(d[{b}], errors='coerce')")
        L.append("ok = x.notna() & y.notna()")
        L.append("from scipy import stats")
        L.append("pr, pp = stats.pearsonr(x[ok], y[ok]); sr, sp = stats.spearmanr(x[ok], y[ok])")
        L.append("result = pd.DataFrame({'method': ['Pearson', 'Spearman'], 'coefficient': [pr, sr], 'p_value': [pp, sp], 'n': [int(ok.sum())] * 2})")
        L.append(f"points = d.loc[ok, [{a}, {b}]].sample(min(int(ok.sum()), 800), random_state=0)")
    elif op == "distribution":
        c = _lit(s["columns"][0])
        L.append(f"x = pd.to_numeric(d[{c}], errors='coerce').dropna()")
        L.append("result = x.describe(percentiles=[.05, .25, .5, .75, .95]).rename('value').reset_index().rename(columns={'index': 'statistic'})")
        L.append("counts, edges = np.histogram(x, bins=min(30, max(5, int(np.sqrt(len(x)))))) if len(x) else ([], [0])")
    elif op == "distinct":
        c = _lit(s["columns"][0])
        L.append(f"result = d[{c}].value_counts(dropna=False).rename('rows').reset_index()")
        if s["limit"]:
            L.append(f"result = result.head({s['limit']})")
    elif op == "rows":
        if s["columns"]:
            L.append(f"d = d.assign(_k=pd.to_numeric(d[{_lit(s['columns'][0])}], errors='coerce')).sort_values('_k', ascending={asc}).drop(columns='_k')")
        L.append(f"result = d.head({s['limit'] or 50})")
    return "\n".join(L)


def compile_sql(s: dict[str, Any]) -> str | None:
    """Equivalent SQL for reference (table name `data`). Not executed."""
    def q(c: str) -> str:
        return '"' + c.replace('"', '""') + '"'

    def lit(v: Any) -> str:
        return repr(v) if isinstance(v, (int, float)) else "'" + str(v).replace("'", "''") + "'"
    where = []
    for f in s["filters"]:
        if f["op"] == "contains":
            where.append(f"LOWER({q(f['column'])}) LIKE {lit('%' + str(f['value']).lower() + '%')}")
        else:
            where.append(f"{q(f['column'])} {'=' if f['op'] == '==' else '<>' if f['op'] == '!=' else f['op']} {lit(f['value'])}")
    w = f"\nWHERE {' AND '.join(where)}" if where else ""
    order = "ASC" if s["sort"] == "asc" else "DESC"
    agg_sql = {"sum": "SUM", "mean": "AVG", "median": "MEDIAN", "min": "MIN", "max": "MAX", "count": "COUNT", "nunique": "COUNT(DISTINCT"}
    op, m, agg, g = s["op"], s["measure"], s["agg"], s["group_by"]
    if op in ("aggregate", "trend"):
        if agg == "count" and not m:
            expr, alias = "COUNT(*)", "rows"
        elif agg == "nunique":
            expr, alias = f"COUNT(DISTINCT {q(m)})", f"nunique_{m}"
        else:
            expr, alias = f"{agg_sql[agg]}({q(m)})", f"{agg}_{m}"
        keys = []
        if op == "trend":
            fmt = {"day": "%Y-%m-%d", "week": "%Y-%W", "month": "%Y-%m", "quarter": "%Y-Q", "year": "%Y"}[s["grain"]]
            keys.append(f"STRFTIME('{fmt}', {q(s['date_col'])})")
        if g:
            keys.append(q(g))
        sel = ", ".join([f"{keys[0]} AS period" if op == "trend" else keys[0]] + keys[1:]) + ", " if keys else ""
        sql = f"SELECT {sel}{expr} AS {q(alias)}\nFROM data{w}"
        if keys:
            sql += f"\nGROUP BY {', '.join(keys)}"
            sql += "\nORDER BY period" if op == "trend" else f"\nORDER BY {q(alias)} {order}"
        if s["limit"] and g and op == "aggregate":
            sql += f"\nLIMIT {s['limit']}"
        return sql
    if op == "distinct":
        c = q(s["columns"][0])
        return f"SELECT {c}, COUNT(*) AS rows\nFROM data{w}\nGROUP BY {c}\nORDER BY rows DESC" + (f"\nLIMIT {s['limit']}" if s["limit"] else "")
    if op == "rows":
        o = f"\nORDER BY {q(s['columns'][0])} {order}" if s["columns"] else ""
        return f"SELECT *\nFROM data{w}{o}\nLIMIT {s['limit'] or 50}"
    if op == "correlation":
        a, b = (q(c) for c in s["columns"])
        return f"SELECT CORR({a}, {b}) AS pearson\nFROM data{w}  -- Spearman is computed in pandas/SciPy"
    return None


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return [{str(k): _num(v) for k, v in row.items()} for row in df.head(MAX_RESULT_ROWS).to_dict("records")]


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:,.2f}" if abs(v) < 1e15 else f"{v:.3g}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def execute(df: pd.DataFrame, s: dict[str, Any]) -> dict[str, Any]:
    code = compile_pandas(s)
    ns: dict[str, Any] = {"df": df, "pd": pd, "np": np}
    with np.errstate(all="ignore"):
        exec(compile(code, "<ask>", "exec"), {"__builtins__": __builtins__}, ns)  # code is generated from a validated spec only
    result: pd.DataFrame = ns["result"]
    filtered_rows = int(len(ns["d"]))
    out: dict[str, Any] = {"code": code, "sql": compile_sql(s), "rows_used": filtered_rows, "rows_total": int(len(df)),
                           "columns": [str(c) for c in result.columns], "rows": _records(result), "truncated": len(result) > MAX_RESULT_ROWS,
                           "chart": None, "warnings": []}
    op, m, agg, g = s["op"], s["measure"], s["agg"], s["group_by"]
    if s["filters"] and filtered_rows == 0:
        out["headline"] = "No rows match these filters."
        return out
    vcol = out["columns"][-1] if out["columns"] else None
    agg_word = {"sum": "Total", "mean": "Average", "median": "Median", "min": "Minimum", "max": "Maximum", "count": "Count of", "nunique": "Distinct"}.get(agg or "", "")
    label = f"{agg_word} {m}" if m else "Rows"
    if m and agg not in ("count", "nunique") and op in ("aggregate", "trend"):
        miss = int(pd.to_numeric(ns["d"][m], errors="coerce").isna().sum())
        if miss:
            out["warnings"].append(f"{miss:,} rows with a missing or non-numeric {m} were left out of the {agg}.")
    if op == "aggregate":
        if g and len(result):
            top = result.iloc[0]
            out["headline"] = f"{top[g]} has the {'lowest' if s['sort'] == 'asc' else 'highest'} {label.lower()}: {_fmt(_num(top[vcol]))}" + \
                              (f" (of {result[g].nunique() if not s['limit'] else 'the groups shown'})." if len(result) > 1 else ".")
            if len(result) == 1 and s["limit"] == 1:
                out["headline"] = f"{top[g]} has the {'lowest' if s['sort'] == 'asc' else 'highest'} {label.lower()}: {_fmt(_num(top[vcol]))}."
            out["chart"] = {"id": "ask", "kind": "bar", "title": f"{label} by {g}", "data": out["rows"][:40], "x": str(g),
                            "series": [{"key": vcol, "label": label}], "layout": "horizontal" if len(result) > 6 else None}
            sizes = ns["d"].groupby(g, dropna=False).size()
            small = int((sizes < 5).sum())
            if small and agg in ("mean", "median", "max", "min"):
                out["warnings"].append(f"{small} group(s) have fewer than 5 rows, so their {agg} is unstable.")
        else:
            out["headline"] = f"{label}: {_fmt(_num(result.iloc[0, 0]))}" + (f" across {filtered_rows:,} rows." if s["filters"] and m else ".")
    elif op == "trend":
        series = [vcol] if not g else []
        data = out["rows"]
        if g:
            wide = result.pivot_table(index="period", columns=g, values=vcol, aggfunc="sum").reset_index()
            keep = list(result.groupby(g)[vcol].sum().sort_values(ascending=False).index[:6])
            wide = wide[["period"] + keep]
            wide.columns = [str(c) for c in wide.columns]
            data, series = _records(wide), [str(k) for k in keep]
        out["chart"] = {"id": "ask", "kind": "line", "title": f"{label} per {s['grain']}" + (f" by {g}" if g else ""), "data": data,
                        "x": "period", "series": [{"key": k, "label": k} for k in series]}
        if not g and len(result) >= 2:
            a, b = result[vcol].iloc[-2], result[vcol].iloc[-1]
            chg = f", {'up' if b > a else 'down'} {abs(b - a) / abs(a) * 100:.1f}% on the previous {s['grain']}" if a else ""
            out["headline"] = f"{label} was {_fmt(_num(b))} in {result['period'].iloc[-1]}{chg}. Range covers {result['period'].iloc[0]} to {result['period'].iloc[-1]}."
            out["warnings"].append("The latest period may be incomplete if data collection is ongoing.")
        else:
            out["headline"] = f"{label} per {s['grain']} across {result['period'].nunique()} periods."
    elif op == "correlation":
        pr, sr, n = float(result.iloc[0, 1]), float(result.iloc[1, 1]), int(result.iloc[0, 3])
        strength = "strong" if abs(sr) >= 0.6 else "moderate" if abs(sr) >= 0.3 else "weak" if abs(sr) >= 0.1 else "no meaningful"
        a, b = s["columns"]
        out["headline"] = f"{strength.capitalize()} {'positive' if sr > 0 else 'negative'} association between {a} and {b} (Spearman {sr:.2f}, Pearson {pr:.2f}, n = {n:,})." \
            if strength != "no meaningful" else f"No meaningful association between {a} and {b} (Spearman {sr:.2f}, n = {n:,})."
        out["warnings"].append("Correlation is not causation; a third factor may drive both.")
        pts = ns["points"].set_axis(["x", "y"], axis=1).apply(pd.to_numeric, errors="coerce")
        out["chart"] = {"id": "ask", "kind": "scatter", "title": f"{b} vs {a}", "data": _records(pts), "x": "x", "series": [{"key": "y", "label": b}],
                        "x_label": a, "y_label": b}
    elif op == "distribution":
        counts, edges = ns["counts"], ns["edges"]
        hist = [{"bin": f"{edges[i]:.4g}–{edges[i + 1]:.4g}", "count": int(counts[i])} for i in range(len(counts))]
        stats_ = dict(zip(result["statistic"], result["value"]))
        out["headline"] = f"{s['columns'][0]}: median {_fmt(_num(stats_.get('50%')))}, middle 50% between {_fmt(_num(stats_.get('25%')))} and {_fmt(_num(stats_.get('75%')))} (n = {int(stats_.get('count', 0)):,})."
        out["chart"] = {"id": "ask", "kind": "bar", "title": f"Distribution of {s['columns'][0]}", "data": hist, "x": "bin", "series": [{"key": "count", "label": "Rows"}]}
    elif op == "distinct":
        n = int(ns["d"][s["columns"][0]].nunique(dropna=True))
        out["headline"] = f"{s['columns'][0]} has {n:,} distinct values" + (f"; the most common is {result.iloc[0, 0]} ({int(result.iloc[0, 1]):,} rows)." if len(result) else ".")
        out["chart"] = {"id": "ask", "kind": "bar", "title": f"Rows by {s['columns'][0]}", "data": out["rows"][:25], "x": out["columns"][0],
                        "series": [{"key": "rows", "label": "Rows"}], "layout": "horizontal"}
    elif op == "rows":
        out["headline"] = f"{filtered_rows:,} rows match; showing {len(result):,}."
    return out


def describe_spec(s: dict[str, Any]) -> str:
    parts = []
    if s["op"] in ("aggregate", "trend"):
        parts.append(f"{s['agg']} of {s['measure']}" if s["measure"] else "row count")
        if s["group_by"]:
            parts.append(f"grouped by {s['group_by']}")
        if s["op"] == "trend":
            parts.append(f"per {s['grain']} of {s['date_col']}")
    elif s["op"] == "correlation":
        parts.append(f"correlation of {s['columns'][0]} and {s['columns'][1]}")
    elif s["op"] == "distribution":
        parts.append(f"distribution of {s['columns'][0]}")
    elif s["op"] == "distinct":
        parts.append(f"distinct values of {s['columns'][0]}")
    else:
        parts.append("matching rows" + (f" sorted by {s['columns'][0]}" if s["columns"] else ""))
    for f in s["filters"]:
        parts.append(f"where {f['column']} {f['op']} {f['value']}")
    if s["limit"] and s["op"] == "aggregate" and s["group_by"]:
        parts.append(f"{'bottom' if s['sort'] == 'asc' else 'top'} {s['limit']}")
    return ", ".join(parts)


LLM_SCHEMA = {
    "type": "object", "required": ["op"],
    "properties": {
        "op": {"type": "string", "enum": list(OPS)}, "measure": {"type": ["string", "null"]}, "agg": {"type": ["string", "null"], "enum": list(AGGS) + [None]},
        "group_by": {"type": ["string", "null"]}, "date_col": {"type": ["string", "null"]}, "grain": {"type": ["string", "null"]},
        "limit": {"type": ["integer", "null"]}, "sort": {"type": "string", "enum": ["asc", "desc"]},
        "columns": {"type": "array", "items": {"type": "string"}},
        "filters": {"type": "array", "items": {"type": "object", "properties": {"column": {"type": "string"}, "op": {"type": "string", "enum": list(FILTER_OPS)}, "value": {}}}},
    },
}


def llm_parse(question: str, schema: Schema) -> dict[str, Any] | None:
    from . import llm
    if not llm.available():
        return None
    cols = [{"name": c, "type": schema.types.get(c), "numeric": c in schema.numeric, "date": c in schema.dates} for c in schema.cols]
    try:
        out, _ = llm.structured("Translate the analytics question into the query spec. Use only the listed column names. Do not compute anything.",
                                f"Columns: {cols}\nQuestion: {question}", LLM_SCHEMA, tool_name="query_spec", max_tokens=600)
    except llm.LLMError:
        return None
    out.setdefault("filters", [])
    return out


def suggestions(schema: Schema) -> list[str]:
    m, out = schema.measure, []
    cats = [c for c in schema.categorical if c in schema.values and 2 <= len(schema.values[c]) <= 40]
    if m and cats:
        out.append(f"Total {m} by {cats[0]}")
        out.append(f"Which {cats[0]} has the highest average {m}?")
    if m and schema.date:
        out.append(f"{m} by month")
    if m and len(cats) > 1:
        out.append(f"Top 5 {cats[1]} by {m}")
    nums = [c for c in schema.numeric if schema.types.get(c) != "categorical_numeric"]
    if len(nums) >= 2:
        out.append(f"Correlation between {nums[0]} and {nums[1]}")
    if m:
        out.append(f"Distribution of {m}")
    if cats:
        v = schema.values[cats[0]][-1]
        out.append(f"How many rows in {v}?" if not m else f"Average {m} in {v}")
    return out[:6] or [f"How many rows are there?"]


def answer(df: pd.DataFrame, profile: dict[str, Any], question: str | None = None, spec: dict[str, Any] | None = None) -> dict[str, Any]:
    schema = Schema(df, profile)
    source, assumptions, confidence = "edited", [], 0.95
    if spec is None:
        if not question:
            raise AskError("Ask a question.")
        try:
            parsed = parse(question, schema)
            source = "rules"
        except AskError as exc:
            parsed = llm_parse(question, schema)
            if not parsed:
                raise exc
            parsed.update(assumptions=["Interpreted by the language model; check the interpretation below."], confidence=0.6)
            source = "llm"
        if source == "rules" and parsed["confidence"] < 0.5:
            alt = llm_parse(question, schema)
            if alt:
                try:
                    validate(alt, schema)
                    parsed = {**alt, "assumptions": ["Interpreted by the language model; check the interpretation below."], "confidence": 0.65}
                    source = "llm"
                except AskError:
                    pass
        assumptions, confidence = parsed.pop("assumptions", []), parsed.pop("confidence", 0.5)
        spec = parsed
    s = validate(spec, schema)
    res = execute(df, s)
    return {"question": question, "spec": s, "interpretation": describe_spec(s), "assumptions": assumptions, "confidence": confidence,
            "parser": source, **res,
            "schema": {"columns": schema.cols, "numeric": schema.numeric, "dates": schema.dates, "categorical": schema.categorical}}
