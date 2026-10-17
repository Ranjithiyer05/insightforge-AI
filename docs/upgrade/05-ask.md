# Phase 5: Ask your data

## Files changed
- backend/app/ask.py (new): question parser, spec validation, pandas and SQL compilers, executor, answer summaries, suggestions, optional LLM interpretation.
- backend/app/db.py: AskQuery table (question history, pinning).
- backend/app/main.py: POST /api/datasets/{id}/ask, GET /ask/suggestions, GET /ask/history, POST /api/ask/{id}/pin, DELETE /api/ask/{id}.
- frontend/src/components/ask-data.tsx (new) and an "Ask" tab on the dataset page.
- backend/tests/test_ask.py (8 tests).

## How it works
1. The question is parsed by rules into a small spec: operation, measure, aggregation, grouping, filters, time grain, top/bottom N.
2. The spec is validated against the dataset's columns.
3. The spec is compiled into pandas code, and that exact code is executed. Equivalent SQL is shown for reference.
4. The answer shows a headline computed from the result, a chart, a table, the code, the assumptions the parser made, and warnings (rows dropped for missing values, groups under 5 rows, incomplete last period, correlation is not causation).
5. The interpretation can be edited (calculation, column, grouping, time grain, top/bottom N) and recomputed.
6. An LLM is used only if configured, and only to propose a spec for questions the rules cannot parse. It never computes numbers.

Supported: totals, averages, medians, min/max, counts, distinct counts, grouping, top/bottom N, "which X has the highest Y", category and numeric filters, yes/no columns, trends by day/week/month/quarter/year, correlations (Pearson and Spearman with n and p), distributions, unique values, matching rows.

## Honest refusals
Questions about columns that do not exist get a clear error listing the real columns (for example "total profit" on a dataset without profit), instead of a guessed answer.

## Tests
- 8 new tests check results against direct pandas computation, that the shown code reproduces the answer, that invalid or injected specs are rejected, and that other users cannot query or delete someone's questions.
- Full suite: 51 passed. tsc and production build pass. Browser run: suggestion, trend, refusal and code view, no console errors.

## Limitations
- The rule parser covers common phrasing; unusual wording may need the editor or rephrasing. Joins across datasets are not supported.
- Results are capped at 500 rows in the UI.

## Next
Phase 6: AutoML and explainability.
