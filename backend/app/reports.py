"""Report exports: PDF (reportlab), CSV tables (zip) and reproducible code bundles (zip)."""
from __future__ import annotations

import csv
import io
import json
import zipfile
from typing import Any

from reportlab.graphics.charts.barcharts import HorizontalBarChart, VerticalBarChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .sandbox.executor import HERE as SANDBOX_DIR
from .storage import csv_safe

ACCENT = colors.HexColor("#4F46E5")
SERIES = [colors.HexColor(c) for c in ("#4F46E5", "#0EA5A4", "#F59E0B", "#E11D48", "#64748B")]


def _esc(s: Any) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _chart_drawing(ch: dict[str, Any]) -> Drawing | None:
    data, x, series = ch.get("data") or [], ch.get("x"), ch.get("series") or []
    kind = ch.get("kind")
    if kind not in ("line", "bar", "stacked_bar") or not data or len(data) > 60:
        return None
    cats = [str(r.get(x, ""))[:18] for r in data]
    vals = [[float(r.get(s["key"]) or 0) for r in data] for s in series]
    d = Drawing(170 * mm, 70 * mm)
    horizontal = ch.get("layout") == "horizontal" and kind != "line"
    if kind == "line":
        c = HorizontalLineChart()
        for i in range(len(vals)):
            c.lines[i].strokeColor = SERIES[i % len(SERIES)]
            c.lines[i].strokeWidth = 1.5
    else:
        c = HorizontalBarChart() if horizontal else VerticalBarChart()
        for i in range(len(vals)):
            c.bars[i].fillColor = SERIES[i % len(SERIES)]
            c.bars[i].strokeColor = None
        if kind == "stacked_bar":
            c.categoryAxis.style = "stacked"
    c.x, c.y, c.width, c.height = 22 * mm if horizontal else 15 * mm, 12 * mm, 120 * mm if horizontal else 140 * mm, 50 * mm
    c.data = vals
    c.categoryAxis.categoryNames = cats
    c.categoryAxis.labels.fontSize = 6
    c.valueAxis.labels.fontSize = 6
    if not horizontal:
        c.categoryAxis.labels.angle = 45 if len(cats) > 8 else 0
        c.categoryAxis.labels.boxAnchor = "ne" if len(cats) > 8 else "n"
        if len(cats) > 20:
            step = max(1, len(cats) // 10)
            c.categoryAxis.categoryNames = [n if i % step == 0 else "" for i, n in enumerate(cats)]
    d.add(c)
    if len(series) > 1:
        lg = Legend()
        lg.x, lg.y = 150 * mm, 60 * mm
        lg.fontSize = 6
        lg.colorNamePairs = [(SERIES[i % len(SERIES)], s.get("label", s["key"])) for i, s in enumerate(series)]
        d.add(lg)
    d.add(String(0, 66 * mm, ch.get("title", "")[:100], fontSize=8, fillColor=colors.HexColor("#334155")))
    return d


def build_pdf(analysis: dict[str, Any], dataset: dict[str, Any]) -> bytes:
    rep = analysis["result"]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"InsightForge report: {rep.get('title', '')[:80]}")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontSize=16, textColor=colors.HexColor("#0F172A"), spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=12, textColor=ACCENT, spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=9, leading=12.5)
    small = ParagraphStyle("s", parent=body, fontSize=7.5, textColor=colors.HexColor("#475569"))
    el: list[Any] = [Paragraph("InsightForge AI · Analysis report", small), Paragraph(_esc(rep.get("title", "")), h1)]
    meta = f"Dataset: <b>{_esc(dataset.get('name'))}</b> ({dataset.get('n_rows', 0):,} rows) · Status: <b>{_esc(rep.get('status'))}</b> · Analysis {analysis['id']}"
    el.append(Paragraph(meta, small))
    if dataset.get("is_synthetic"):
        el.append(Paragraph("<b>SYNTHETIC DEMO DATA.</b> All records in this dataset are invented for demonstration.", ParagraphStyle("w", parent=body, textColor=colors.HexColor("#B45309"))))
    v = rep.get("verification") or {}
    vtxt = f"Independent verification: <b>{_esc(v.get('status', 'not run'))}</b>" + (f" ({v.get('counts', {}).get('pass', 0)} passed, {v.get('counts', {}).get('warn', 0)} warnings, {v.get('counts', {}).get('fail', 0)} failed)" if v else "")
    el += [Paragraph(vtxt, small), Spacer(1, 4), Paragraph("Executive summary", h2), Paragraph(_esc(rep.get("executive_summary", "")), body),
           Paragraph(f"Narrative source: {_esc(rep.get('narrative_source'))}", small), Paragraph("Key findings", h2)]
    for f in rep.get("findings", []):
        mark = {True: "✓ verified", False: "✗ failed verification", None: "not verified"}.get(f.get("verified"))
        el.append(KeepTogether([Paragraph(f"<b>{_esc(f['title'])}</b>", body), Paragraph(_esc(f["detail"]), body),
                                Paragraph(f"{_esc(f.get('kind'))} · confidence {_esc(f.get('confidence'))} · {mark} · evidence: {_esc(', '.join(f.get('evidence', [])))}", small), Spacer(1, 4)]))
    charts = [c for c in rep.get("charts", []) if _chart_drawing(c)]
    if charts:
        el.append(Paragraph("Charts (computed from the dataset)", h2))
        for ch in charts[:6]:
            el += [_chart_drawing(ch), Spacer(1, 4)]
    metrics = [(k, m.get("value")) for k, m in rep.get("metrics", {}).items() if isinstance(m.get("value"), (int, float)) and not isinstance(m.get("value"), bool)]
    if metrics:
        el.append(Paragraph("Statistical results and metrics", h2))
        rows = [["Metric", "Value", "Detail"]]
        for k, val in metrics[:40]:
            m = rep["metrics"][k]
            det = ", ".join(f"{a}={b}" for a, b in m.items() if a not in ("value",) and not isinstance(b, (list, dict)))
            ci = m.get("ci95") or m.get("interval95")
            if ci:
                det = (det + f" 95% CI [{ci[0]:.4g}, {ci[1]:.4g}]").strip()
            rows.append([k, f"{val:,.4g}" if isinstance(val, float) else str(val), det[:70]])
        t = Table(rows, colWidths=[55 * mm, 30 * mm, 85 * mm])
        t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 7), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF2FF")),
                               ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1"))]))
        el.append(t)
    if rep.get("recommendations"):
        el.append(Paragraph("Recommendations (suggestions linked to evidence)", h2))
        for r in rep["recommendations"]:
            el.append(Paragraph(f"• <b>{_esc(r['action'])}</b> — {_esc(r['rationale'])} <font color='#64748B'>[evidence: {_esc(', '.join(r.get('evidence', [])))}]</font>", body))
    el.append(Paragraph("Limitations and uncertainty", h2))
    for lim in rep.get("limitations", []) + rep.get("warnings", []):
        el.append(Paragraph("• " + _esc(lim), body))
    if rep.get("data_quality"):
        el.append(Paragraph("Data-quality warnings", h2))
        for q in rep["data_quality"]:
            el.append(Paragraph("• " + _esc(q["message"]), body))
    if v.get("checks"):
        el.append(Paragraph("Verification checks", h2))
        rows = [["Status", "Category", "Check"]] + [[c["status"], c.get("category", ""), Paragraph(_esc(c["message"])[:300], small)] for c in v["checks"][:40]]
        t = Table(rows, colWidths=[15 * mm, 22 * mm, 133 * mm])
        t.setStyle(TableStyle([("FONTSIZE", (0, 0), (-1, -1), 7), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1"))]))
        el.append(t)
    el.append(Paragraph("Reproducibility", h2))
    r = rep.get("reproducibility", {})
    el.append(Paragraph(f"Dataset SHA-256: {_esc(dataset.get('sha256', ''))}<br/>Strategy: {_esc(rep.get('final_strategy'))} · attempts: {len(rep.get('attempts', []))} · "
                        f"seed {r.get('random_seed')} · Python {_esc(r.get('python'))} · " + _esc(", ".join(f"{k} {v}" for k, v in r.get("libraries", {}).items())) +
                        f"<br/>Execution: {_esc(r.get('isolation'))}. Download the code bundle to re-run every step.", small))
    doc.build(el)
    return buf.getvalue()


def tables_zip(rep: dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, t in rep.get("tables", {}).items():
            s = io.StringIO()
            w = csv.writer(s)
            w.writerow([csv_safe(c) for c in t["columns"]])
            for row in t["rows"]:
                w.writerow([csv_safe(v) for v in row])
            z.writestr(f"{name}.csv", s.getvalue())
        s = io.StringIO()
        w = csv.writer(s)
        w.writerow(["metric", "value"])
        for k, m in rep.get("metrics", {}).items():
            w.writerow([k, csv_safe(json.dumps(m.get("value")) if isinstance(m.get("value"), (list, dict)) else m.get("value"))])
        z.writestr("metrics.csv", s.getvalue())
    return buf.getvalue()


def code_zip(analysis: dict[str, Any], steps: list[dict[str, Any]], dataset: dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("ifrt.py", (SANDBOX_DIR / "runtime_lib.py").read_text())
        names = []
        for st in steps:
            if st["code"]:
                fn = f"step{st['idx']:02d}_{st['key']}_attempt{st['attempt']}.py"
                names.append((fn, st["title"], st["status"]))
                z.writestr(fn, st["code"])
        readme = [f"# Reproduce analysis {analysis['id']}", "", f"Question: {analysis['question']}", "",
                  f"Dataset: {dataset['name']} (SHA-256 {dataset['sha256']}). The data file is NOT included, to keep it private.",
                  "Place your copy next to these scripts as `data.csv`, then run each step:", "",
                  "    pip install pandas numpy scipy statsmodels scikit-learn", "    python stepNN_<name>.py   # writes result.json", "", "Steps:"]
        readme += [f"- `{fn}` — {title} [{status}]" for fn, title, status in names]
        z.writestr("README.md", "\n".join(readme) + "\n")
        z.writestr("plan.json", json.dumps(analysis.get("plan", {}), indent=2, default=str))
    return buf.getvalue()


def _fmt(v: Any) -> str:
    if isinstance(v, bool) or v is None:
        return "" if v is None else str(v)
    if isinstance(v, float):
        return f"{v:,.4g}" if abs(v) < 1e6 else f"{v:,.0f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def _svg_bars(rows: list[tuple[str, float]], title: str, width: int = 640) -> str:
    """Small self-contained horizontal bar chart for the HTML report."""
    rows = rows[:15]
    if not rows:
        return ""
    vmax = max(abs(v) for _, v in rows) or 1
    h = 26 + 22 * len(rows)
    out = [f'<figure><figcaption>{_esc(title)}</figcaption><svg viewBox="0 0 {width} {h}" width="100%" role="img" aria-label="{_esc(title)}">']
    for i, (label, v) in enumerate(rows):
        y = 10 + i * 22
        w = abs(v) / vmax * (width - 260)
        out.append(f'<text x="170" y="{y + 13}" text-anchor="end" font-size="11">{_esc(str(label)[:28])}</text>'
                   f'<rect x="178" y="{y}" width="{w:.1f}" height="16" rx="3" fill="#4F46E5"/>'
                   f'<text x="{184 + w:.1f}" y="{y + 13}" font-size="11" fill="#475569">{_esc(_fmt(v))}</text>')
    out.append("</svg></figure>")
    return "".join(out)


def _svg_line(points: list[tuple[str, float]], title: str, width: int = 640, height: int = 200) -> str:
    if len(points) < 2:
        return ""
    vals = [v for _, v in points]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    xs = [40 + i * (width - 60) / (len(points) - 1) for i in range(len(points))]
    ys = [height - 30 - (v - lo) / span * (height - 50) for v in vals]
    path = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(zip(xs, ys)))
    return (f'<figure><figcaption>{_esc(title)}</figcaption><svg viewBox="0 0 {width} {height}" width="100%" role="img" aria-label="{_esc(title)}">'
            f'<path d="{path}" fill="none" stroke="#4F46E5" stroke-width="2"/>'
            f'<text x="40" y="{height - 8}" font-size="11" fill="#475569">{_esc(points[0][0])}</text>'
            f'<text x="{width - 20}" y="{height - 8}" font-size="11" text-anchor="end" fill="#475569">{_esc(points[-1][0])}</text>'
            f'<text x="4" y="{ys[vals.index(hi)]:.0f}" font-size="10" fill="#475569">{_esc(_fmt(hi))}</text>'
            f'<text x="4" y="{ys[vals.index(lo)]:.0f}" font-size="10" fill="#475569">{_esc(_fmt(lo))}</text></svg></figure>')


def _html_table(columns: list[str], rows: list[list[Any]]) -> str:
    head = "".join(f"<th>{_esc(c)}</th>" for c in columns)
    body = "".join("<tr>" + "".join(f"<td>{_esc(_fmt(v))}</td>" for v in r) + "</tr>" for r in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def dataset_report_sections(dataset: dict[str, Any], eda: dict[str, Any], questions: list[dict[str, Any]], models: list[dict[str, Any]]) -> dict[str, Any]:
    """Collect report content once; rendered as HTML or PDF. Everything here was computed from the data."""
    p = dataset.get("profile") or {}
    return {"dataset": dataset, "profile": p, "eda": eda, "questions": questions, "models": models}


def build_dataset_html(sec: dict[str, Any], generated: str) -> str:
    d, p, e = sec["dataset"], sec["profile"], sec["eda"]
    parts = [f"<h1>{_esc(d['name'])}</h1><p class='meta'>{d.get('n_rows', 0):,} rows × {d.get('n_cols', 0)} columns · SHA-256 {_esc(d.get('sha256', ''))[:16]}… · generated {generated}</p>"]
    if d.get("is_synthetic"):
        parts.append("<p class='warn'><b>Synthetic demo data.</b> All records are invented for demonstration.</p>")
    if e.get("kpis"):
        def kv(k: dict[str, Any]) -> str:
            return f"{k['value'] * 100:.1f}%" if k.get("format") == "pct" else _fmt(k["value"])
        parts.append("<section class='kpis'>" + "".join(f"<div><span>{_esc(k['label'])}</span><b>{_esc(kv(k))}</b></div>" for k in e["kpis"]) + "</section>")
    parts.append("<h2>Data quality</h2>")
    parts.append(f"<p>Quality score {round((p.get('quality_score') or 0) * 100)}/100 · {p.get('duplicates', 0):,} duplicate rows · {(p.get('missing_pct') or 0) * 100:.1f}% missing cells.</p>")
    if p.get("issues"):
        parts.append("<ul>" + "".join(f"<li class='{_esc(i['severity'])}'>{_esc(i['message'])}</li>" for i in p["issues"][:30]) + "</ul>")
    if d.get("cleaning_log"):
        parts.append("<h3>Cleaning applied</h3><ol>" + "".join(f"<li>{_esc(op.get('op'))} {_esc(op.get('column') or '')}: {_esc(op.get('reason') or '')}</li>"
                                                                for h in d["cleaning_log"] for op in h.get("operations", [])) + "</ol>")
    parts.append("<h2>Insights</h2>")
    if e.get("insights"):
        for i in e["insights"]:
            ev = i.get("evidence", {})
            parts.append(f"<div class='ins'><h3>{_esc(i['title'])}</h3><p>{_esc(i['detail'])}</p><p class='meta'>{_esc(ev.get('method', ''))}"
                         f"{' · n = ' + _fmt(ev['n']) if ev.get('n') is not None else ''}. {_esc(i.get('caveat', ''))}</p></div>")
    else:
        parts.append("<p>No pattern passed the evidence thresholds.</p>")
    t = e.get("trend")
    if t:
        parts.append(_svg_line([(r["period"], r["value"] or 0) for r in t["series"]], f"{'Total' if t['aggregation'] == 'sum' else 'Count of'} {t['measure']} per {t['granularity']}"))
    for c in (e.get("categorical") or [])[:2]:
        if c.get("by_measure"):
            parts.append(_svg_bars([(r["value"], r["sum"]) for r in c["by_measure"]["rows"]], f"Total {c['by_measure']['measure']} by {c['column']}"))
    if e.get("summary"):
        parts.append("<h2>Summary statistics</h2>" + _html_table(["column", "count", "missing", "mean", "median", "std", "min", "max"],
                                                                 [[r.get(k) for k in ("column", "count", "missing", "mean", "median", "std", "min", "max")] for r in e["summary"]]))
    if sec["questions"]:
        parts.append("<h2>Saved questions</h2><ul>" + "".join(f"<li><b>{_esc(q['question'])}</b>: {_esc(q['headline'])}</li>" for q in sec["questions"]) + "</ul>")
    for m in sec["models"]:
        r = m["result"]
        tm = r["test_metrics"]
        parts.append(f"<h2>Model: predicting {_esc(r['target'])}</h2><p>{_esc(r['best_model'].replace('_', ' '))} chosen by 5-fold cross-validation from "
                     f"{len(r['leaderboard'])} candidates. {_esc(r['split_description'])}</p>")
        parts.append(_html_table(["metric (held-out test)", "value"], [[k, v] for k, v in tm.items()]))
        parts.append(_svg_bars([(s["feature"], s["mean_abs_shap"] or 0) for s in r["shap_global"]], "Mean |Shapley value| per feature"))
        for w in r["warnings"]:
            parts.append(f"<p class='warn'>{_esc(w)}</p>")
        if r["excluded"]:
            parts.append("<p class='meta'>Excluded: " + "; ".join(f"{_esc(x['feature'])} ({_esc(x['reason'])})" for x in r["excluded"]) + "</p>")
    parts.append("<h2>Method notes</h2><ul>" + "".join(f"<li>{_esc(n)}</li>" for n in e.get("notes", [])) +
                 "<li>Associations are not causes. Group differences and correlations may be explained by other factors.</li>"
                 "<li>Model explanations describe how the model uses its inputs, not what would happen if an input were changed.</li></ul>")
    css = ("body{font:14px/1.55 system-ui,-apple-system,Segoe UI,sans-serif;color:#0f172a;max-width:860px;margin:32px auto;padding:0 16px}"
           "h1{font-size:26px;margin:0}h2{font-size:18px;color:#4f46e5;margin-top:28px;border-bottom:1px solid #e2e8f0;padding-bottom:4px}h3{font-size:15px;margin:12px 0 2px}"
           ".meta{color:#64748b;font-size:12px}.warn{color:#b45309}li.warning{color:#b45309}table{border-collapse:collapse;width:100%;font-size:12px;margin:8px 0}"
           "th,td{border:1px solid #e2e8f0;padding:4px 8px;text-align:left}th{background:#eef2ff}.kpis{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0}"
           ".kpis div{border:1px solid #e2e8f0;border-radius:10px;padding:10px 14px}.kpis span{display:block;font-size:12px;color:#64748b}.kpis b{font-size:18px}"
           ".ins{border-left:3px solid #4f46e5;padding-left:10px;margin:10px 0}figure{margin:12px 0}figcaption{font-size:12px;color:#334155;font-weight:600}"
           "@media print{body{margin:0}}")
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{_esc(d['name'])} · InsightForge report</title><style>{css}</style></head><body><p class='meta'>InsightForge AI · Dataset report</p>"
            + "".join(parts) + "</body></html>")


def build_dataset_pdf(sec: dict[str, Any], generated: str) -> bytes:
    d, p, e = sec["dataset"], sec["profile"], sec["eda"]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm, title=f"InsightForge report: {d['name'][:80]}")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Heading1"], fontSize=16, textColor=colors.HexColor("#0F172A"), spaceAfter=4)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=12, textColor=ACCENT, spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=9, leading=12.5)
    small = ParagraphStyle("s", parent=body, fontSize=7.5, textColor=colors.HexColor("#475569"))
    tstyle = TableStyle([("FONTSIZE", (0, 0), (-1, -1), 7), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF2FF")), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1"))])
    el: list[Any] = [Paragraph("InsightForge AI · Dataset report", small), Paragraph(_esc(d["name"]), h1),
                     Paragraph(f"{d.get('n_rows', 0):,} rows × {d.get('n_cols', 0)} columns · SHA-256 {_esc(d.get('sha256', ''))[:16]}… · generated {generated}", small)]
    if d.get("is_synthetic"):
        el.append(Paragraph("<b>SYNTHETIC DEMO DATA.</b> All records are invented for demonstration.", ParagraphStyle("w", parent=body, textColor=colors.HexColor("#B45309"))))
    if e.get("kpis"):
        el.append(Spacer(1, 4))
        el.append(Table([[k["label"] for k in e["kpis"]], [f"{k['value'] * 100:.1f}%" if k.get("format") == "pct" else _fmt(k["value"]) for k in e["kpis"]]], style=tstyle))
    el.append(Paragraph("Data quality", h2))
    el.append(Paragraph(f"Quality score {round((p.get('quality_score') or 0) * 100)}/100 · {p.get('duplicates', 0):,} duplicate rows · {(p.get('missing_pct') or 0) * 100:.1f}% missing cells.", body))
    for i in (p.get("issues") or [])[:25]:
        el.append(Paragraph("• " + _esc(i["message"]), body))
    el.append(Paragraph("Insights", h2))
    for i in e.get("insights", []):
        ev = i.get("evidence", {})
        el.append(KeepTogether([Paragraph(f"<b>{_esc(i['title'])}</b>", body), Paragraph(_esc(i["detail"]), body),
                                Paragraph(_esc(f"{ev.get('method', '')}. {i.get('caveat', '')}"), small), Spacer(1, 3)]))
    if not e.get("insights"):
        el.append(Paragraph("No pattern passed the evidence thresholds.", body))
    t = e.get("trend")
    if t:
        dr = _chart_drawing({"kind": "line", "title": f"{t['measure']} per {t['granularity']}", "data": t["series"], "x": "period", "series": [{"key": "value"}]})
        if dr:
            el += [dr, Spacer(1, 4)]
    for c in (e.get("categorical") or [])[:2]:
        if c.get("by_measure"):
            dr = _chart_drawing({"kind": "bar", "layout": "horizontal", "title": f"Total {c['by_measure']['measure']} by {c['column']}", "data": c["by_measure"]["rows"][:15],
                                 "x": "value", "series": [{"key": "sum"}]})
            if dr:
                el += [dr, Spacer(1, 4)]
    if e.get("summary"):
        el.append(Paragraph("Summary statistics", h2))
        keys = ("column", "count", "missing", "mean", "median", "std", "min", "max")
        el.append(Table([list(keys)] + [[_fmt(r.get(k))[:18] for k in keys] for r in e["summary"][:30]], style=tstyle, repeatRows=1))
    if sec["questions"]:
        el.append(Paragraph("Saved questions", h2))
        for q in sec["questions"]:
            el.append(Paragraph(f"• <b>{_esc(q['question'])}</b>: {_esc(q['headline'])}", body))
    for m in sec["models"]:
        r = m["result"]
        el.append(Paragraph(f"Model: predicting {_esc(r['target'])}", h2))
        el.append(Paragraph(_esc(f"{r['best_model'].replace('_', ' ')} chosen by 5-fold cross-validation from {len(r['leaderboard'])} candidates. {r['split_description']}"), body))
        el.append(Table([["Metric (held-out test)", "Value"]] + [[k, _fmt(v)] for k, v in r["test_metrics"].items()], style=tstyle))
        dr = _chart_drawing({"kind": "bar", "layout": "horizontal", "title": "Mean |Shapley value| per feature", "data": r["shap_global"][:15], "x": "feature", "series": [{"key": "mean_abs_shap"}]})
        if dr:
            el.append(dr)
        for w in r["warnings"]:
            el.append(Paragraph("• " + _esc(w), body))
    el.append(Paragraph("Method notes", h2))
    for n in e.get("notes", []) + ["Associations are not causes.", "Model explanations describe how the model uses its inputs, not causal effects."]:
        el.append(Paragraph("• " + _esc(n), body))
    doc.build(el)
    return buf.getvalue()
