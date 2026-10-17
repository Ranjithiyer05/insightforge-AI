# Phase 8: Dashboards, monitoring, patterns, pipeline and reproducibility

## Files changed
- backend/app/patterns.py (new): anomalies, forecast, segments.
- backend/app/dashboards.py (new): version lineage, tile validation, live rendering, KPI rule evaluation.
- backend/app/db.py: Dashboard and MonitorEvent tables.
- backend/app/main.py: GET /api/datasets/{id}/patterns/{anomalies|forecast|segments}, POST /api/datasets/{id}/versions, GET /api/datasets/{id}/pipeline, GET /api/datasets/{id}/reproduce.zip, dashboards CRUD (/api/dashboards, /api/dashboards/{id}, /tiles), GET /api/alerts.
- frontend: Patterns and Pipeline tabs on the dataset page, Dashboards in the sidebar (/dashboards and /dashboards/[id]), "Add to dashboard" on every Ask answer. The forecast chart now honours its interval keys and label and hides empty series.
- backend/tests/test_phase8.py (4 tests).

## Features
- Patterns tab:
  - Anomalies: Isolation Forest flags unusual rows, and each one says which values make it unusual. Unusual days are found against a rolling median. The caveat that unusual does not mean wrong is shown.
  - Forecast: naive, seasonal naive, linear trend and Holt-Winters are scored on the latest held-out periods. The forecast says plainly when nothing beats the naive forecast, and an incomplete last period is dropped.
  - Segments: k-means with k chosen by silhouette score. Each segment gets a plain description, and a weak silhouette is reported as "no clear segments".
- Dashboards: tiles store the question's validated spec, not numbers, and are recomputed from the latest data version whenever the board opens. Tiles can be reordered, resized and renamed, and boards can hold notes. Each tile can show its pandas code.
- KPI monitoring: a single-number tile can carry a rule (above or below a value, or a % change from the previous version). A rule is evaluated once per data version and recorded. Alerts are only those recorded breaches. Re-opening a board never duplicates an alert, and nothing is simulated.
- New data versions: "Upload newer data" (Pipeline tab) adds next month's file as a new version. Dashboards and monitors follow it automatically, and added or removed columns are reported.
- Pipeline tab: the timeline of versions (original upload, cleaned, newer data) with their cleaning steps, plus the questions, models, analyses and dashboards built on each.
- Reproduce bundle: a zip with the exact cleaning code, recipe.json (every step with its reason), replay.py, and saved questions as standalone pandas scripts. The data is not included. The test runs replay.py in a clean folder and checks the rebuilt file matches.
- Projects already existed. Dashboards inherit the dataset's project.

## Tests
- Planted outliers and an outlier day are found. A trend series beats naive, and too little history is refused. Two clear clusters are detected and pure noise is called weak.
- End to end: dashboard on version 1 shows no alert. Uploading version 2 with sales halved records exactly one "-50.0%" breach, and re-rendering adds none. The pipeline shows upload, new data and cleaned versions. The reproduce bundle rebuilds the cleaned file. Other users get 404s.
- Full suite: 63 passed. tsc and production build pass. Browser run: all three pattern views, adding tiles from Ask to a new dashboard, the dashboard page and the pipeline page, with no console errors.

## Limitations
- Monitoring runs when a dashboard is opened, after new data arrives. There is no background scheduler or email, because the free hosting sleeps when idle.
- Pattern modules sample large files (up to 50,000 rows for anomaly training and 10,000 for segments).

## Next
Phase 9: tests, benchmarks, docs, security review, deploy verification.
