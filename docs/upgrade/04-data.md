# Phase 4: Upload, profiling, cleaning, EDA

## Files changed
- backend/app/cleaning.py (new): 13 logged cleaning operations, preview, suggestions.
- backend/app/eda.py (new): automatic EDA with statistical evidence.
- backend/app/profiler.py: new issue kinds (constant, whitespace, numeric-as-text, dates-as-text, redundant columns) and stats (mode, variance, kurtosis, IQR).
- backend/app/db.py: Dataset.parent_id, sheet_names.
- backend/app/main.py: clean preview, suggestions, lineage, CSV/XLSX download (formula-safe), cached EDA endpoint, versioned cleaning.
- frontend: quality-dashboard, cleaning-workspace, eda-view, paged-preview; dataset page tabs synced with ?tab=; Excel sheet picker on upload.

## Features
- Interactive quality dashboard with filters.
- Cleaning workspace: ordered steps, per-step before/after stats, side-by-side preview, saves a new version (original never overwritten), lineage panel.
- Insights tab: KPIs with formulas, ranked insights each with method, n, p and Benjamini-Hochberg q, trend with partial-period detection, correlation heatmap (Spearman), Kruskal-Wallis group tests.
- Export cleaned data as CSV or XLSX.

## Tests
- tests/test_cleaning_eda.py: 10 tests. Full suite: 43 passed. tsc and production build pass.
- Browser run (Playwright): guest demo, all tabs, cleaning preview and save, no console errors.

## Bugs fixed during the phase
- "q = 0" shown for tiny q values; now "< 0.001".
- Insights dominated by one kind; capped at 3 per kind.
- Price-like numeric columns were used as groups; excluded.

## Limitations
- EDA is capped to sampled rows on very large files; insights are associations, not causes.
- Data still resets on Render restarts until DATABASE_URL points to Postgres (e.g. Neon).

## Next
Phase 5: Ask your data.
