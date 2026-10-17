# Phase 9: Tests, benchmarks, docs, security, deploy check

## Files changed
- backend/scripts/benchmark.py (new): runs each main operation in a fresh process and records time and peak memory.
- backend/app/auth.py: login and guest limits now use the visitor's address from X-Forwarded-For; guests are capped per visitor and at 200 per hour overall.
- backend/app/main.py: per-user limit of 40 heavy requests per minute on Ask, Patterns, predictions, scenarios, reports, comparisons and reproduce bundles. AutoML uses at most 8,000 training rows on the free plan.
- backend/app/ask.py: generated code runs with a minimal set of builtins (only `scipy` can be imported); filter values must be finite; limits must be whole numbers.
- backend/app/patterns.py: silhouette sample reduced to 2,000 rows (segments peak memory about 420 MB to about 220 MB).
- README.md: feature table, performance table, security notes and roadmap updated.
- Tests: injection tests for Ask; a guest-limit test.

## Bugs found and fixed in this phase
1. **The live demo button would lock out everyone.** Guest sign-ups were rate-limited under one shared key, so after 5 demo sessions in 10 minutes nobody could try the demo. Behind Render's proxy, login limits were also shared by all visitors, so 5 failed logins anywhere could block every login. Both are now per visitor, with a global hourly cap on guests.
2. **Segments could exceed free-plan memory.** Peak memory was about 420 MB, close to Render's 512 MB limit. It is now about 220 MB.
3. **AutoML was slow for free hosting.** It took about 30 seconds locally on 4 cores; Render's free plan has a fraction of one core. Training is now capped at 8,000 rows there.

## Test results
- 65 backend tests pass on Python 3.13 (local) and on Python 3.12 in a fresh virtualenv installed only from requirements.txt, which matches the Docker image used on Render.
- The frontend type check and production build pass.
- Browser regression (Playwright) passed with no console errors:
  - Phase 4: quality, insights, cleaning and save.
  - Phase 5: Ask, refusal, code view.
  - Phase 6: train, results, prediction.
  - Phase 7: scenario, PDF export, dataset comparison.
  - Phase 8: patterns, dashboards, pipeline.
- Mobile check at 390 px: no horizontal page overflow on Ask, Predict, Patterns, Pipeline and Dashboards.

## Benchmarks (before the memory fix; 4-core sandbox)
| Data | Operation | Seconds | Peak memory (MB) |
|---|---|---|---|
| retail demo (19,560 rows) | profile | 0.31 | 74 |
| retail demo (19,560 rows) | eda | 0.69 | 132 |
| retail demo (19,560 rows) | ask (4 questions) | 0.65 | 132 |
| retail demo (19,560 rows) | anomalies | 1.55 | 165 |
| retail demo (19,560 rows) | forecast | 0.8 | 151 |
| retail demo (19,560 rows) | segments | 2.87 | 404 (now about 220) |
| retail demo (19,560 rows) | automl | 28.77 | 197 |
| synthetic (100,000 rows) | profile | 0.75 | 104 |
| synthetic (100,000 rows) | eda | 0.94 | 162 |
| synthetic (100,000 rows) | ask (4 questions) | 0.87 | 165 |
| synthetic (100,000 rows) | anomalies | 3.57 | 197 |
| synthetic (100,000 rows) | forecast | 0.83 | 172 |
| synthetic (100,000 rows) | segments | 3.87 | 422 (now about 220) |
| synthetic (100,000 rows) | automl (20,000-row sample) | 23.95 | 227 |

## Deploy check
- Every phase was pushed to main, which triggers Render's auto-deploy from render.yaml.
- I could not open the live site from this sandbox: its network proxy blocks Render (HTTP 403), and there is no Docker daemon here to build the image.
- Instead, a clean Python 3.12 install from requirements.txt ran `scripts/init_db.py`, imported every module and passed the full suite with `SANDBOX_MEMORY_MB=384`, the value set in render.yaml.
- **Still to confirm by opening the site:** that the latest deploy finished on Render's dashboard, and that "Try the live demo" opens a workspace.

## Still needed from you
- Set `DATABASE_URL` on the Render API service to a free Neon (or Supabase) Postgres URL. Until then, accounts, datasets, models and dashboards are erased whenever the free instance restarts, and the app shows a banner saying so.

## Known limitations (honest list)
- The sandbox is process isolation, not a VM. Training runs inside the API process, one model at a time per user.
- There are no background jobs or email alerts. KPI rules are checked when a dashboard is opened after new data arrives.
- The Ask parser covers common phrasing. Unusual wording may need the interpretation editor. Joins across datasets are not supported.
- Forecasts have no ARIMA or Prophet, and AutoML has no hyperparameter search. Both are kept small for free hosting.
