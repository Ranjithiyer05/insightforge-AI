# Phase 7: What-if scenarios, dataset comparison, report exports

## Files changed
- backend/app/automl.py: `run_scenario` (model-based what-if with bootstrap interval); models now store their training categories.
- backend/app/compare.py (new): schema diff and per-column distribution shift between two datasets.
- backend/app/reports.py: dataset report as self-contained HTML (inline SVG charts, no scripts) and as PDF.
- backend/app/main.py: POST /api/models/{id}/scenario, GET /api/compare/datasets?a=&b=, GET /api/datasets/{id}/report?format=html|pdf. The EDA cache is shared by the Insights tab and reports.
- frontend: what-if panel under each trained model; "Datasets" tab on the Compare page (components/dataset-compare.tsx); "Report (HTML)" and "Report (PDF)" in the dataset Export menu.
- backend/tests/test_phase7.py (3 tests).

## What-if scenarios
- Change one or more inputs for every row, or for one segment: set a category, or change a number by %, add, multiply or set.
- Shows average prediction before and after, the difference with a 95% bootstrap interval over rows, the share of rows whose prediction rose or fell, totals for regression, and a before/after distribution chart.
- Refuses categories the model never saw. Warns when changes push rows outside the range seen in training (extrapolation).
- Clearly labelled as what the model predicts, not a causal effect.

## Dataset comparison
- Added and removed columns, type changes, row counts.
- Numeric columns: Kolmogorov-Smirnov test plus standardised mean difference, quantile-binned histograms of both.
- Categorical columns: chi-square test plus population stability index (PSI), new and vanished categories, largest share changes.
- p-values adjusted with Benjamini-Hochberg. A column counts as shifted only when q < 0.05 and the effect size is at least moderate, so huge samples do not flag trivial changes.

## Reports
- One-click HTML or PDF report per dataset: KPIs, data quality, cleaning steps, evidence-backed insights, trend and ranking charts, summary statistics, pinned questions from the Ask tab, and up to two trained models with test metrics, Shapley chart and warnings.
- Reports are generated from stored results only; nothing in them is written by an LLM.

## Tests
- Scenario recovers a known linear effect with an interval that covers it, works on a segment, flags extrapolation, rejects unknown categories and features.
- Comparison detects a planted shift, a new category and schema changes, and reports no shift between two samples of the same process.
- Report HTML and PDF download, compare API, and privacy between users.
- Full suite: 59 passed. tsc and production build pass. Browser run: scenario, PDF download and dataset comparison with no console errors.

## Limitations
- Scenarios assume the changed input moves alone; real interventions often change other inputs too.
- Comparison matches columns by exact name.

## Next
Phase 8: saved projects and reproducibility, dashboard builder, pipeline view, anomaly/forecast/cluster modules, KPI monitoring.
