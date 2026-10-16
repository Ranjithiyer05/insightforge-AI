"""Question understanding and planning.

Turns a natural-language question into a structured, editable objective:
task type, columns, method parameters, strategy order and explicit steps.

The deterministic planner always runs. If an LLM is configured it may refine
the task type and column choices, but its output is validated against the
dataset schema and the method registry; anything invalid is discarded.
"""
from __future__ import annotations

import difflib
import re
from typing import Any

from . import llm
from .analyses import REGISTRY, get_method
from .analyses.hypothesis import HypothesisTestMethod

STOP = set("""a an the of in on for to and or is are was were be by with from at as that this these those what which who whom why how did do does
our my we us i you your their there it its last month week year quarter first most more less than vs versus between across per each any
should could would can will investigate products product analyze analyse show tell me give about over under into compare data dataset
there difference significant significantly predict likely""".split())

RULES: list[tuple[str, list[str]]] = [
    ("profit_change", [r"\bwhy\b.*\b(profit|margin|revenue|sales)\b", r"\b(profit|margin|revenue|sales)\b.*\b(declin|drop|fell|fall|decreas|down|change|increas|ros[e]|jump)",
                       r"\b(declin|drop|fall|decreas)\w*\b.*\b(profit|margin)\b"]),
    ("forecasting", [r"\bforecast", r"\bpredict\w*\b.*\bnext\b", r"\bnext (\d+ )?(day|week|month|quarter|year)s?\b", r"\bproject(ion|ed)?\b", r"\bfuture\b"]),
    ("segmentation", [r"\bsegment", r"\bcluster", r"\bpersona", r"\bgroup (our |the )?(customers|users|clients|students|employees)\b"]),
    ("anomaly_detection", [r"\banomal", r"\boutlier", r"\bunusual\b", r"\bsuspicious\b", r"\bodd (transactions|records|rows)"]),
    ("hypothesis_test", [r"\bsignifican", r"\bhypothes", r"\btest (whether|if)\b", r"\bstatistical", r"\bp-?value", r"\bcorrelat",
                         r"\bis there (a |any )?(real |significant )?(difference|relationship|association|link)"]),
    ("classification", [r"\b(churn|default|attrition|turnover|fraud|convert|leave|quit|pass|fail)\w*\b.*\b(predict|likely|risk|probability|who|which)\b",
                        r"\b(predict|likely|risk|probability)\w*\b.*\b(churn|default|attrition|turnover|fraud|convert|leave|quit|pass|fail)",
                        r"\bwhich (customers|employees|students|loans|borrowers)\b.*\b(will|likely|at risk)\b"]),
    ("regression", [r"\bpredict\w*\b", r"\bwhat (drives|affects|influences|determines)\b", r"\b(drivers|factors|determinants) (of|behind|affecting)\b", r"\bestimate\b"]),
    ("comparison", [r"\bcompare\b", r"\bvs\.?\b", r"\bversus\b", r"\bacross\b", r"\b(by|per) (region|product|category|channel|store|segment|month|team|department|class|campaign)",
                    r"\b(highest|lowest|best|worst|top|bottom)\b", r"\bdiffer"]),
    ("descriptive", [r"\b(summar|overview|describe|explore|eda|profile|distribution)"]),
]

TASK_LABELS = {
    "descriptive": "Descriptive analysis", "comparison": "Comparison", "hypothesis_test": "Hypothesis test", "classification": "Classification",
    "regression": "Regression", "forecasting": "Forecasting", "segmentation": "Segmentation", "anomaly_detection": "Anomaly detection",
    "profit_change": "Diagnostic: profit change",
}

SYNONYMS = {"sales": ["revenue", "sales", "amount"], "profit": ["profit", "margin"], "cost": ["cost", "cogs"], "churn": ["churn", "churned", "attrition", "left"],
            "default": ["default", "defaulted"], "price": ["price"], "discount": ["discount", "promo"], "tenure": ["tenure"], "salary": ["salary", "income", "pay"],
            "score": ["score", "grade", "mark"], "turnover": ["left", "attrition", "turnover", "quit"]}


def classify(question: str, profile: dict[str, Any]) -> tuple[str, float, list[str]]:
    q = question.lower()
    hits: list[tuple[str, int]] = []
    for task, pats in RULES:
        n = sum(1 for p in pats if re.search(p, q))
        if n:
            hits.append((task, n))
    if not hits:
        return "descriptive", 0.4, ["No specific analytical intent detected; defaulting to exploratory analysis."]
    task, n = hits[0]  # RULES are ordered by specificity
    reasons = [f"Matched {TASK_LABELS[task].lower()} intent ({n} pattern{'s' if n > 1 else ''})."]
    if task == "profit_change" and not profile.get("datetime_columns"):
        reasons.append("Profit-change diagnosis needs a date column, which was not found; falling back.")
        task = hits[1][0] if len(hits) > 1 else "comparison"
    if task == "regression":
        # "predict churn" with a binary target is classification
        mentioned = mentioned_columns(question, profile)
        for c in mentioned:
            col = _col(profile, c)
            if col and col["semantic_type"] in ("boolean", "categorical", "categorical_numeric") and col["unique"] <= 10:
                reasons.append(f"'{c}' is categorical, so this is classification rather than regression.")
                task = "classification"
                break
    conf = min(0.95, 0.55 + 0.15 * n + (0.1 if len(hits) == 1 else 0))
    return task, round(conf, 2), reasons


def _col(profile: dict[str, Any], name: str) -> dict[str, Any] | None:
    return next((c for c in profile["columns"] if c["name"] == name), None)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def mentioned_columns(question: str, profile: dict[str, Any]) -> list[str]:
    q = " " + _norm(question) + " "
    words = [w for w in q.split() if w not in STOP and len(w) > 2]
    found: list[tuple[int, str]] = []
    for c in profile["columns"]:
        name = _norm(c["name"])
        pos = q.find(" " + name + " ")
        if pos >= 0:
            found.append((pos, c["name"]))
            continue
        toks = [t for t in name.split() if len(t) > 2 and t not in STOP and t not in ("pct", "num", "avg", "total")]
        best = None
        for t in toks:
            for w in words:
                stem_match = w.rstrip("s") == t.rstrip("s") or (len(t) > 4 and len(w) > 4 and (w.startswith(t[:6]) or t.startswith(w[:6])))
                if stem_match or difflib.SequenceMatcher(None, w, t).ratio() > 0.88:
                    p = q.find(" " + w)
                    best = p if best is None else min(best, p)
            for key, syns in SYNONYMS.items():
                if t in syns and any(w.startswith(key) for w in words):
                    p = next(q.find(" " + w) for w in words if w.startswith(key))
                    best = p if best is None else min(best, p)
        if best is not None:
            found.append((best, c["name"]))
    found.sort()
    seen, out = set(), []
    for _, n in found:
        if n not in seen:
            out.append(n)
            seen.add(n)
    return out


def mentioned_values(question: str, profile: dict[str, Any], col: str) -> list[str]:
    c = _col(profile, col)
    if not c:
        return []
    q = " " + _norm(question) + " "
    vals = [v["value"] for v in c.get("top_values", [])]
    return [v for v in vals if " " + _norm(v) + " " in q]


def _types(profile: dict[str, Any], names: list[str], kinds: tuple[str, ...]) -> list[str]:
    return [n for n in names if (_col(profile, n) or {}).get("semantic_type") in kinds]


NUMERIC = ("numeric", "integer")
CATEG = ("categorical", "boolean", "categorical_numeric")


def _features(profile: dict[str, Any], target: str) -> tuple[list[str], list[str]]:
    leaks = {h["feature"] for h in profile.get("leakage_hints", []) if h.get("target") == target}
    feats, excluded = [], []
    for c in profile["columns"]:
        n = c["name"]
        if n == target:
            continue
        if n in leaks or "id" in c["roles"] or c["semantic_type"] in ("identifier", "text", "empty", "datetime"):
            excluded.append(n)
            continue
        if c["semantic_type"] == "categorical" and c["unique"] > 50:
            excluded.append(n)
            continue
        feats.append(n)
    return feats, excluded


def build_params(task: str, question: str, profile: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    roles = profile.get("roles", {})
    mentioned = mentioned_columns(question, profile)
    num_m = _types(profile, mentioned, NUMERIC)
    cat_m = _types(profile, mentioned, CATEG)
    notes: list[str] = []
    first = lambda role: (roles.get(role) or [None])[0]  # noqa: E731
    q = question.lower()

    if task == "profit_change":
        cost_cols = roles.get("cost", [])
        unit_cost = next((c for c in cost_cols if "unit" in c.lower()), None)
        total_cost = next((c for c in cost_cols if c != unit_cost), None)
        prod = next((c for c in roles.get("product", []) if "product" in c.lower() or "sku" in c.lower() or "item" in c.lower()), first("product"))
        p = {"date_col": first("date") or (profile.get("datetime_columns") or [None])[0], "revenue_col": first("revenue"),
             "cost_col": total_cost, "unit_cost_col": unit_cost if not total_cost else None, "profit_col": first("profit"),
             "product_col": prod, "quantity_col": first("quantity"), "discount_col": first("discount"),
             "unit_price_col": next((c for c in roles.get("price", []) if "unit" in c.lower() or c.lower() == "price"), None)}
        notes.append("Compares the latest complete month with the month before it (change 'current_period' to compare a different month).")
        return p, notes
    if task == "forecasting":
        value = (num_m or [first("revenue")] or profile.get("numeric_columns", [None]))[0] or (profile.get("numeric_columns") or [None])[0]
        freq = "W" if "week" in q else "D" if re.search(r"\bdai|\bday", q) else "QS" if "quarter" in q else "MS"
        m = re.search(r"next (\d+)", q)
        return {"date_col": first("date") or (profile.get("datetime_columns") or [None])[0], "value_col": value, "freq": freq,
                "horizon": int(m.group(1)) if m else None, "agg": "sum"}, notes
    if task in ("classification", "regression"):
        target = None
        want = CATEG if task == "classification" else NUMERIC
        cands = _types(profile, mentioned, want)
        if cands:
            target = cands[0]
        else:
            ct = [t for t in profile.get("candidate_targets", []) if t["task"] == task]
            if ct:
                target = ct[0]["column"]
                notes.append(f"No target column was named; using '{target}' ({ct[0]['reason']}). Edit the plan if this is wrong.")
        feats, excluded = _features(profile, target) if target else ([], [])
        return {"target": target, "features": feats, "excluded_features": excluded}, notes
    if task == "hypothesis_test":
        if len(num_m) >= 2 and not cat_m:
            return {"design": "numeric_numeric", "outcome": num_m[1], "group": num_m[0]}, notes
        if num_m and (cat_m or profile.get("candidate_targets")):
            group = cat_m[0] if cat_m else next((t["column"] for t in profile["candidate_targets"] if t["task"] == "classification"), None)
            groups = mentioned_values(question, profile, group) if group else []
            if not groups and group and (_col(profile, group) or {}).get("unique", 0) > 2:
                groups = []
            return {"design": "numeric_categorical", "outcome": num_m[0], "group": group, "groups": groups if len(groups) >= 2 else None}, notes
        if len(cat_m) >= 2:
            tgt = next((c for c in cat_m if any(t["column"] == c and t["score"] >= 0.8 for t in profile.get("candidate_targets", []))), cat_m[-1])
            other = next(c for c in cat_m if c != tgt)
            return {"design": "categorical_categorical", "outcome": tgt, "group": other}, notes
        return {"design": "numeric_categorical", "outcome": num_m[0] if num_m else None, "group": cat_m[0] if cat_m else None}, notes
    if task == "comparison":
        binary_m = [c for c in cat_m if (_col(profile, c) or {}).get("unique") == 2 and (_col(profile, c) or {}).get("semantic_type") in ("boolean", "categorical_numeric")]
        if not num_m and binary_m:
            num_m = binary_m[:1]
            cat_m = [c for c in cat_m if c != binary_m[0]]
            notes.append(f"'{binary_m[0]}' is a yes/no column, so its group mean is the rate per group.")
        value = num_m[0] if num_m else (first("profit") or first("revenue") or (profile.get("numeric_columns") or [None])[0])
        if not num_m and value:
            notes.append(f"No measure was named; comparing '{value}'.")
        bym = re.search(r"\b(?:by|per|across|between) (\w+)", q)
        group = cat_m[0] if cat_m else None
        if not group and bym:
            group = next((c["name"] for c in profile["columns"] if _norm(c["name"]).startswith(bym.group(1).rstrip("s"))), None)
        if not group:
            group = (profile.get("categorical_columns") or [None])[0]
            notes.append(f"No grouping column was named; grouping by '{group}'.")
        return {"value_col": value, "group": group}, notes
    if task == "segmentation":
        feats = num_m if len(num_m) >= 2 else [c for c in profile.get("numeric_columns", []) if "id" not in (_col(profile, c) or {}).get("roles", [])][:8]
        return {"features": feats}, notes
    if task == "anomaly_detection":
        feats = num_m or [c for c in profile.get("numeric_columns", []) if "id" not in (_col(profile, c) or {}).get("roles", [])][:8]
        return {"features": feats}, notes
    return {"numeric": (num_m or profile.get("numeric_columns", []))[:8], "categorical": (cat_m or profile.get("categorical_columns", []))[:5],
            "date_col": first("date"), "value_col": first("revenue") or (num_m[0] if num_m else None)}, notes


def strategy_order(task: str, params: dict[str, Any]) -> list[str]:
    if task == "hypothesis_test":
        return HypothesisTestMethod.default_order(params)
    return list(get_method(task).strategies)


def make_plan(question: str, profile: dict[str, Any], task_override: str | None = None, params_override: dict[str, Any] | None = None) -> dict[str, Any]:
    task, confidence, reasons = classify(question, profile)
    if task_override:
        task, confidence, reasons = task_override, 1.0, ["Task type set by the user."]
    params, notes = build_params(task, question, profile)
    if params_override:
        params.update({k: v for k, v in params_override.items() if k in params or k in ("current_period", "groups", "positive_class", "alpha")})
    planner = {"kind": "deterministic", "detail": "Rule-based intent classification and schema matching."}
    if llm.available() and not task_override:
        refined = _llm_refine(question, profile, task, params)
        if refined:
            task, params, llm_notes, usage = refined
            notes += llm_notes
            planner = {"kind": "llm", "detail": f"{usage['provider']}:{usage['model']} refined the deterministic plan; output validated against the schema.", "usage": usage}
    return finalize_plan(question, profile, task, params, confidence, reasons, notes, planner)


def finalize_plan(question, profile, task, params, confidence, reasons, notes, planner, strategies=None, retry_budget=None) -> dict[str, Any]:
    from .config import settings
    method = get_method(task)
    missing = method.requirements(profile, params)
    for k in ("target", "outcome", "group", "value_col", "date_col", "product_col", "revenue_col", "cost_col"):
        v = params.get(k)
        if v and not _col(profile, v):
            missing.append(f"column '{v}' does not exist in the dataset")
    strategies = strategies or strategy_order(task, params)
    stages = method.stages(params, strategies[0]) if not missing else []
    steps = [{"key": "profile", "title": "Inspect dataset and data quality", "kind": "profile", "description": "Re-check types, missing values and leakage hints for the selected columns."},
             {"key": "memory", "title": "Retrieve relevant past experience", "kind": "memory", "description": "Look up validated lessons from similar tasks and datasets."}]
    steps += [{"key": s.key, "title": s.title, "kind": s.kind, "description": s.rationale} for s in stages]
    steps += [{"key": "verify", "title": "Independently verify results", "kind": "verify", "description": "Recompute key numbers from raw data, check assumptions, leakage and evidence links."},
              {"key": "learn", "title": "Record experiment and update memory", "kind": "memory", "description": "Store the outcome as evidence; promote lessons only after verification."},
              {"key": "report", "title": "Compose report", "kind": "report", "description": "Assemble findings, charts, limitations and recommendations from verified results."}]
    columns = sorted({v for k, v in params.items() if isinstance(v, str) and _col(profile, v)} |
                     {c for k, v in params.items() if isinstance(v, list) for c in v if isinstance(c, str) and _col(profile, c) and k != "excluded_features"})
    return {
        "question": question,
        "objective": objective_text(task, params),
        "task_type": task,
        "task_label": TASK_LABELS[task],
        "confidence": confidence,
        "reasons": reasons,
        "params": params,
        "strategies": strategies,
        "available_strategies": method.strategies,
        "retry_budget": settings.retry_budget if retry_budget is None else retry_budget,
        "required_columns": columns,
        "feasible": not missing,
        "missing_requirements": missing,
        "assumptions": notes,
        "steps": steps,
        "estimated_sandbox_runs": {"min": len(stages), "max": len(stages) * (1 + (settings.retry_budget if retry_budget is None else retry_budget))},
        "planner": planner,
    }


def objective_text(task: str, p: dict[str, Any]) -> str:
    return {
        "profit_change": f"Explain the change in profit between the two most recent complete months and identify which products ({p.get('product_col')}) drove it.",
        "forecasting": f"Forecast {p.get('value_col')} per period and check the forecast beats naive baselines.",
        "classification": f"Predict {p.get('target')} from {len(p.get('features') or [])} features and evaluate on held-out data.",
        "regression": f"Model {p.get('target')} from {len(p.get('features') or [])} features and identify the most predictive ones.",
        "hypothesis_test": f"Test whether {p.get('outcome')} differs by / relates to {p.get('group')}" + (f" (groups: {', '.join(p['groups'])})" if p.get("groups") else "") + ".",
        "comparison": f"Compare {p.get('value_col')} across {p.get('group')} with confidence intervals.",
        "segmentation": f"Find natural segments using {', '.join((p.get('features') or [])[:5])}.",
        "anomaly_detection": f"Flag unusual records based on {', '.join((p.get('features') or [])[:5])}.",
        "descriptive": "Summarise the dataset's distributions, categories and relationships.",
    }[task]


def _llm_refine(question: str, profile: dict[str, Any], task: str, params: dict[str, Any]):
    cols = [{"name": c["name"], "type": c["semantic_type"], "roles": c["roles"], "unique": c["unique"]} for c in profile["columns"]]
    schema = {"type": "object", "properties": {
        "task_type": {"type": "string", "enum": list(REGISTRY)},
        "params": {"type": "object", "description": "Same keys as the draft params; values must be column names from the schema."},
        "notes": {"type": "array", "items": {"type": "string"}},
        "answerable": {"type": "boolean"}, "unanswerable_reason": {"type": "string"}}, "required": ["task_type", "params", "answerable"]}
    prompt = (f"Question: {question}\nColumns: {cols}\nDraft plan: task_type={task}, params={params}\n"
              "Correct the task type and column choices if the draft is wrong. Use only listed column names. Do not invent data.")
    try:
        out, usage = llm.structured("You are a careful data-science planner. Output only the structured plan.", prompt, schema, "submit_plan")
    except llm.LLMError:
        return None
    t = out.get("task_type")
    if t not in REGISTRY:
        return None
    names = {c["name"] for c in profile["columns"]}
    p2 = build_params(t, question, profile)[0] if t != task else dict(params)
    for k, v in (out.get("params") or {}).items():
        if k in p2 and (v is None or (isinstance(v, str) and v in names) or (isinstance(v, list) and all(isinstance(x, str) and x in names for x in v))):
            p2[k] = v
    notes = [f"LLM note: {n}" for n in (out.get("notes") or [])[:3]]
    if out.get("answerable") is False and out.get("unanswerable_reason"):
        notes.append(f"LLM flagged a possible gap: {out['unanswerable_reason']}")
    return t, p2, notes, usage
