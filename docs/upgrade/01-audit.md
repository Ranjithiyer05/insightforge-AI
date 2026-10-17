# Phase 1: Audit and feature-gap report

Date: 2026-10-17. Commit audited: `7ad8574` (main).

## How this was checked

- Read every backend module and the main frontend pages.
- Ran the backend test suite: **26 passed** (`python -m pytest -q`, Python 3.13).
- Type-checked and built the frontend: **`tsc --noEmit` clean, `next build` succeeded** (15 routes).
- Ran the app locally (FastAPI on :8000, Next.js on :3000) and drove it with Playwright: register, overview, every sidebar page, the retail demo, the dataset page, and a 390 px mobile viewport. No console or page errors.
- Ran six analysis types through the API with the **same sandbox memory limit Render uses (`SANDBOX_MEMORY_MB=384`)**.
- The live Render URLs could not be reached from this sandbox (the egress proxy refuses `*.onrender.com`), so the live site was audited from its code and `render.yaml`.

## Stack

| Layer | What is used |
|---|---|
| Frontend | Next.js 15 (App Router), React 19, Tailwind CSS 4, Radix primitives, Recharts 2, TanStack Table, next-themes, lucide icons. No animation library. |
| Backend | FastAPI, SQLAlchemy 2, pandas, NumPy, SciPy, statsmodels, scikit-learn, openpyxl, reportlab. |
| Database | SQLite by default; Postgres when `DATABASE_URL` is set. Tables are created with `create_all` (no migrations). |
| Jobs | A 2-worker `ThreadPoolExecutor` inside the API process. |
| Execution | Generated analysis scripts run in a subprocess sandbox (AST allowlist, rlimits, timeout, scrubbed env, audit hook, optional netns). |
| AI | Optional LLM (Ollama or any OpenAI-compatible endpoint) for plan refinement and the summary only. Off by default; the deterministic planner and writer always work. |
| Deploy | Render free plan, two Docker services from `render.yaml`. The web service proxies `/api/*` to the API at runtime. |

## What works today (verified)

- Accounts, sessions, per-user isolation (other users' ids return 404), admin page that cannot open user data.
- Upload of CSV/XLSX with extension, magic-byte and size checks; server-generated storage names.
- Profiling: semantic types, roles, missing values, duplicates, inconsistent spellings, IQR outliers, candidate targets, leakage hints, quality score.
- The agent pipeline: question → editable plan → sandboxed Python/SQL → independent verifier → retries → memory → report. The retail demo finished in 5 s with verification **passed** and a correct profit decomposition.
- Nine analysis templates: descriptive, comparison, hypothesis test, classification, regression, forecasting, segmentation, anomaly detection, profit change.
- Exports: PDF report, CSV tables zip, reproducible code zip. Share links (hashed tokens, revocable). Side-by-side comparison of two analyses.
- Dataset explorer (histograms, top values, correlation heatmap) and missing-value filling as a cleaned copy.
- Dark and light themes; a responsive shell with a collapsible sidebar.

## Bugs and reliability problems found

| # | Severity | Problem | Evidence |
|---|---|---|---|
| B1 | **High** | With Render's `SANDBOX_MEMORY_MB=384`, scikit-learn runs crash with `OpenBLAS error: Memory allocation still failed`. Segmentation fails outright and the first classification attempt fails. `RLIMIT_AS` caps *virtual* address space, which OpenBLAS reserves generously. | Reproduced locally with the Render setting. |
| B2 | **High** | The live site uses SQLite on an ephemeral disk, so accounts, datasets and analyses vanish whenever the free instance restarts or sleeps. Even with Postgres, uploaded files live only on disk and are lost on redeploy, leaving analyses that point at missing files. | `render.yaml`, `storage.py`. |
| B3 | Medium | `POST /datasets/upload` is an `async` endpoint that parses the file synchronously with pandas' slow Python engine (`sep=None`), which blocks the whole event loop for large files. | `main.py:228`, `storage.py:54`. |
| B4 | Medium | The frontend hard-codes a 50 MB upload limit while Render's API allows 20 MB, so a 30 MB file uploads fully and only then fails. | `new/page.tsx:18`, `render.yaml`. |
| B5 | Medium | SQLite foreign keys are not enabled, so `ON DELETE CASCADE` is ignored. Retention cleanup deletes old datasets but leaves their analyses behind. | `db.py`, `main.py:49`. |
| B6 | Low | Every preview, explore and profile request re-reads the full CSV from disk; there is no caching. | `storage.load_dataset`. |
| B7 | Low | New columns can't be added to an existing Postgres database because there is no migration step. | `init_db` uses `create_all` only. |
| B8 | Low | No public landing page: a first-time visitor lands on the sign-in form with no explanation of the product and no way to try it without registering. | `auth.tsx`. |

## Feature gaps against the brief

Legend: ✅ present, 🟡 partial, ❌ missing.

| Brief section | Status | Gap |
|---|---|---|
| 3 Premium animated UI | 🟡 | Polished shell and tokens exist. Missing: page transitions, staggered entrances, animated KPI counters, skeletons everywhere, command palette (only a name search), onboarding. |
| 4 Smart upload | 🟡 | Drag-and-drop, validation and progress exist. Missing: preview pagination, Excel sheet choice, limits read from the server, clearer malformed-file messages. |
| 5 Profiling | 🟡 | Missing: identifier/text/redundant/constant column flags in the UI, mixed-type (invalid) value detection, a filterable data-quality dashboard. |
| 6 Transparent cleaning | 🟡 | Only fill-missing, drop-duplicates, normalise-spellings, drop-column, drop-missing-rows. Missing: rename, type conversion, date parsing, outlier capping, text normalisation, before/after stats, side-by-side view, history with reasons, restore. |
| 7 Automated EDA and insights | 🟡 | Only through the "descriptive" analysis template. Missing: an always-available EDA page with mode/variance, time trends, grouped summaries and an evidence-backed insight engine. |
| 8 Ask your data | ❌ | Questions become multi-step planned analyses. There is no conversational Q&A that answers "which product had the highest revenue?" directly with the pandas/SQL shown. |
| 9 Universal analysis engine | 🟡 | The planner covers nine task types. Missing: a dataset-level "what can I analyse here?" recommender that explains why each analysis is or is not suitable and asks to confirm ambiguous choices. |
| 10 AutoML lab | 🟡 | Models are tried one at a time until one passes. Missing: a lab where the user confirms the target, sees a baseline plus several models compared in one table, train/validation/test, time-aware splits, error analysis. |
| 11 Explainability | 🟡 | Permutation importance only. Missing: local explanations, Shapley values, contribution charts. |
| 12 Anomalies, forecasting, clustering | 🟡 | Exist as analysis templates. Missing: per-row reasons for anomalies, rolling backtests and intervals for forecasts, cluster profiles with silhouette in a dedicated module. |
| 13 What-if simulator | ❌ | |
| 14 Dashboard builder | ❌ | |
| 15 Dataset comparison and change detection | ❌ | "Compare" compares two analyses, not two datasets or periods. |
| 16 Report generator | 🟡 | Per-analysis PDF exists. Missing: a dataset-level business report (quality, KPIs, insights, model results, methodology), cleaned-dataset CSV/Excel export. |
| 17 Saved projects and reproducibility | 🟡 | Projects exist but are thin. Missing: one place showing a dataset's lineage, cleaning recipe, models, dashboards, questions and reports; a replayable recipe. |
| 18 Pipeline visualiser | 🟡 | Per-analysis step timeline exists. Missing: the Upload → … → Report pipeline per dataset. |
| 19 KPI monitoring | ❌ | Render's free plan sleeps, so an in-process scheduler would not be reliable. |
| 20 Security | 🟡 | Strong base. Missing: request-size limit on JSON bodies, per-user job limits, a clear statement of what is sent to an LLM in the UI. |
| 22 Tests and benchmark | 🟡 | 26 tests. Missing: tests for the new features, a known-answer benchmark, CI. |
| 23 Recruiter presentation | 🟡 | Good README. Missing: landing page, guest demo, API docs link, refreshed screenshots. |

## Prioritised plan

1. **Phase 2 (reliability first).** Fix B1–B7: replace the address-space limit with a data-segment limit that works with OpenBLAS; persist dataset bytes in the database so files survive restarts; move parsing off the event loop and use the fast CSV engine; read upload limits from the server; enable SQLite foreign keys and clean up orphans; cache parsed datasets; add a small additive migration step; show a clear banner when storage is ephemeral.
2. **Phase 3.** Add Motion for animation; page transitions, staggered cards, animated counters, skeletons, a real command palette, a public landing page, a guest demo, and a dataset workspace with tabs.
3. **Phase 4.** Paginated preview, Excel sheet choice, richer profiling and a quality dashboard, a full cleaning workspace with before/after and history, and an EDA page with an evidence-backed insight engine.
4. **Phase 5.** "Ask your data": a deterministic question parser (optionally refined by the LLM, always validated) that runs fixed pandas operations, shows the pandas and SQL, the filters and the table/chart, keeps context per dataset, and says what is missing when it can't answer.
5. **Phase 6.** AutoML lab with confirmed target, baseline, model comparison, CV on the training split only, time-aware splits, imbalance handling, error analysis, permutation importance and sampled Shapley local explanations.
6. **Phase 7.** What-if simulator, dataset/period comparison, dataset-level PDF report and cleaned data exports.
7. **Phase 8.** Project page with lineage and history, replayable cleaning recipes, dashboard builder, pipeline view, anomaly/forecast/cluster modules, and KPI rules that are checked on every new data version plus an optional cron endpoint (never claimed active unless it ran).
8. **Phase 9.** Tests for every new module, a known-answer benchmark with measured timings, CI on GitHub Actions, security review, README and screenshots.
