# Phase 6: AutoML and explainability

## Files changed
- backend/app/automl.py (new): task detection, feature screening, model comparison, held-out evaluation, Shapley estimates, partial dependence, predictions with explanations.
- backend/app/db.py: ModelRun table (config, status, progress, results, fitted pipeline).
- backend/app/main.py: POST /api/datasets/{id}/automl, GET /api/datasets/{id}/models, GET /api/models/{id}, POST /api/models/{id}/predict, DELETE /api/models/{id}. Runs left unfinished by a restart are marked failed on startup.
- frontend/src/components/model-builder.tsx (new) and a "Predict" tab on the dataset page.
- frontend/src/components/charts/chart-renderer.tsx: fixed sideways (horizontal) bar charts, which rendered a single bar with no labels everywhere in the app.
- backend/tests/test_automl.py (5 tests). requirements.txt lists joblib explicitly (already installed with scikit-learn).

## How evaluation stays honest
- Identifiers, date columns, free text, constant columns, profiler leakage hints, and any feature that predicts the target almost perfectly on its own are excluded and listed with the reason.
- Preprocessing (imputation, scaling, one-hot encoding) is inside the pipeline, so it is learned from training folds only.
- A naive baseline, a linear model, a random forest and gradient boosting are compared by 5-fold cross-validation on the training split. Only the chosen model is scored on the held-out 25%, once.
- Optional time-ordered split (train on earliest 75%, test on latest 25%).
- Warnings for near-perfect scores (likely leakage), overfitting (train vs CV gap), barely beating the baseline, low recall on the positive class, and small datasets.

## Explanations
- Permutation importance on the test set, with spread over 5 repeats.
- Shapley value estimates by permutation sampling against 100 background rows. Each sample is exactly additive, so the bars always sum to the prediction minus the base value. Tested against a linear model where the exact answer is known.
- Partial dependence for the top numeric features.
- Prediction form: start from typical values, change inputs, get a prediction with a per-feature contribution chart and an extrapolation warning outside the training range.
- All explanations are labelled as how the model uses its inputs, not causal effects.

## Tests
- Leakage and identifier exclusion, beats-baseline check, Shapley additivity, exact linear Shapley values, time split, refusal on too little data or a single class, API run, prediction, and privacy between users.
- Full suite: 56 passed. tsc and production build pass. Browser run on the churn demo: training, results, charts and prediction with no console errors.

## Limitations
- Training runs in the API process (one at a time per user) and is capped at 20,000 rows on the free Render plan, where it takes noticeably longer than locally.
- Multiclass explanations use the probability of the predicted class.
- No hyperparameter search beyond the fixed candidates; this keeps runs fast on free hosting.

## Next
Phase 7: what-if scenarios, dataset comparison, report exports.
