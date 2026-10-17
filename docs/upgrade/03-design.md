# Phase 3: Design system, animation and first-run experience

## Added

- **Motion** (`motion@12.23.12`, the Framer Motion successor) behind `MotionConfig reducedMotion="user"`, so every animation is disabled for people who ask their OS to reduce motion.
- Page transitions on every route, staggered card entrances, KPI counters that count up when they scroll into view, and a smoother sidebar collapse.
- **Command palette** (Ctrl/⌘ K or the search box): navigation, demos, theme switching and live search of datasets and analyses, fully keyboard-driven with ARIA combobox/listbox roles. Replaces the old dropdown search.
- **Public landing page** at `/welcome` (visitors who are not signed in land here instead of the sign-in form): what the product does, how it is built, plainly stated limitations.
- **One-click guest demo**: `POST /api/auth/guest` creates a temporary account with the retail demo already loaded. Guest accounts are rate-limited per address, never become admin, show a banner, and are deleted with all their data after `GUEST_TTL_HOURS` (default 24) on the next server start.
- **Getting started** card on the overview for accounts with no data yet.
- The decorative floating animation on the overview was removed.

## Files changed

`frontend/src/components/{motion,command-palette,shell,auth,auth-form}.tsx`, `frontend/src/app/{layout,page}.tsx`, `frontend/src/app/welcome/page.tsx`, `frontend/src/lib/api.ts`, `frontend/package.json`, `backend/app/{main,db,auth,config}.py`, `backend/tests/test_guest.py`.

## Tests

- Backend: **33 passed** (new: guest account creation, dataset access, purge after expiry).
- Frontend: `tsc` clean, `next build` succeeded.
- Browser check (Playwright): `/` → `/welcome` when signed out; "Try the live demo" → guest workspace on the dataset page; palette search finds the dataset; mobile layout renders.

## Remaining

The per-dataset workspace (quality, cleaning, explore, ask, model tabs) is built in Phases 4 to 6, where its content lands.
