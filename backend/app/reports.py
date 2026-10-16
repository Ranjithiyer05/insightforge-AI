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
