# Phase 2: Reliability fixes

## Bugs fixed

| # | Fix | Files |
|---|---|---|
| B1 | The sandbox memory cap now uses `RLIMIT_DATA` (real allocations) instead of `RLIMIT_AS` (reserved address space). Under Render's 384 MB setting, classification and segmentation used to crash with an OpenBLAS allocation error; both now complete. A 1.6 GB allocation is still refused. | `backend/app/sandbox/executor.py` |
| B2 | Every dataset file is also kept as a gzip copy in the database (`dataset_blobs`, up to `DB_BLOB_MAX_MB`, default 25). If the disk copy disappears after a restart, it is restored on first use. If no copy exists, the API returns a clear 410 message instead of a 500. `postgres://` and `postgresql://` URLs from Neon or Supabase now work as pasted. | `storage.py`, `db.py`, `config.py`, `main.py` |
| B2 | When the server runs on temporary SQLite storage, `/api/health` says so and the app shows a dismissible banner explaining that data is erased on restart and how to keep it. | `main.py`, `frontend/src/components/shell.tsx` |
| B3 | Upload parsing runs in a worker thread instead of blocking the event loop, and CSVs are parsed with pandas' C engine after sniffing the delimiter, instead of the slow Python engine. | `main.py`, `storage.py` |
| B4 | The upload page reads the server's size limit from `/api/status` instead of a hard-coded 50 MB. | `frontend/src/app/new/page.tsx` |
| B5 | SQLite foreign keys are enabled, so `ON DELETE CASCADE` works. Retention cleanup now removes a dataset's analyses and its stored copy with it. | `db.py`, `main.py` |
| B6 | Parsed datasets are cached (4 most recent, keyed by file modification time, copies handed out). | `storage.py` |
| B7 | A small additive migration adds new columns to tables created by older versions, so Postgres users can upgrade in place. | `db.py` |

## Tests

- New `backend/tests/test_reliability.py` (6 tests): scikit-learn under the 384 MB cap, memory cap still enforced, semicolon CSV, restore after a disk wipe, 410 when no copy exists, health reports the storage mode.
- Full suite: **32 passed**. Frontend `tsc --noEmit` clean.

## Remaining limitations

- Accounts on the live site still reset on restart until `DATABASE_URL` is set to a Postgres database in the Render dashboard. That needs the account owner; the code side is ready.
- The live site could not be reached from this sandbox, so the fixes were verified locally with Render's settings, not on Render itself.
