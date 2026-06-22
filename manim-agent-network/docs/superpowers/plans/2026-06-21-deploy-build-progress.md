# Deploy Build — Progress Tracker (ralph loop)

Living checklist for building the GitHub Actions hybrid deployment to production.
Spec: [`../specs/2026-06-21-deployment-hybrid-spec.md`](../specs/2026-06-21-deployment-hybrid-spec.md). Branch: `deploy/hybrid-spec`.

## Decisions locked (ralph iteration 1, 2026-06-21)
1. **Frontend served by the web tier** (same origin) → studio.js relative paths unchanged, no CORS. R2 needs CORS for video range requests only.
2. **Neon writes via a runner-side mirror** (`scripts/runner_neon_mirror.py`): polls in-runner orchestrator over localhost, UPSERTs Neon event-driven. **Zero orchestrator code change.**
3. **Clerk from day one** — whole web tier gated. No shared-secret half-measure.
4. **`/analyze` reimplemented in the web tier** (synchronous NIM). Web tier holds `NVIDIA_API_KEY` (only place).
5. **Variant A first**; Variant B (long-video matrix) sequenced later.
6. **Staleness sweep** marks stuck `queued` jobs failed; dispatch failure → job failed + 502.
7. **Datadog** — ~~agent + ddtrace on the web tier~~ **superseded** (see M2 below): Azure F1 can't host an Agent sidecar, so the web tier ships **agentless metrics via the HTTP API**; APM/tracing deferred until the web tier runs with a sidecar.
8. Timeout ladder: app 20000s < watchdog 20400s < workflow 350min < GH cap 360min.
9. Non-negotiable free tier: **Neon + Clerk + Datadog**. Actions spend limit **$0**, Azure **F1**, R2 zero-egress.

## M0 — Security pre-work (BLOCKING, needs user/keys)
- [ ] Revoke leaked stale key `nvapi-80infK…` in NVIDIA console *(user)*
- [ ] `git filter-repo` scrub `.env` from `ver-2.0`; delete stale `jules-*`/`feature/*` branches; force-push *(user-approved)*
- [ ] Make repo private
- [x] `.gitignore` already excludes `.env` (confirmed)
- [x] gitleaks CI gate (`.github/workflows/gitleaks.yml` + `.gitleaks.toml`, full-history scan)

## M1 — Get it live, free (core)
- [x] Web tier app — FastAPI: `/generate`, `/job`, `/jobs`, `/video`, `/analyze`, `/health`, `/admin/*` (`services/web-tier/app/`)
- [x] Clerk JWT verify + RBAC + owner scoping (404 on mismatch) (`auth.py`)
- [x] Neon schema + SQLAlchemy store (`db.py`, `migrations/0001_init.sql`)
- [x] GitHub dispatch client (`dispatch.py`) + idempotency
- [x] R2 SigV4 presign (`storage.py`)
- [x] Quotas (daily + global concurrency) + staleness sweep
- [x] `docker-compose.ci.yml` runner override (no GPU, no image-fetcher, mem_limits, concurrency=1)
- [x] `.github/workflows/render-job.yml` (Variant A) + `build-images.yml` (ghcr prebuild)
- [x] `scripts/runner_neon_mirror.py` (drive orchestrator → Neon → R2)
- [x] Tests: 20 passing (web-tier behaviour + presign determinism + mirror logic)
- [x] web-tier `Dockerfile` + `requirements.txt`
- [x] Frontend Clerk: `clerk-auth.js` (loads clerk-js, gates sign-in, exposes `window.__authToken()`); `studio.js` `api()` attaches Bearer; `studio.html` includes it; web tier serves public `/auth-config.json` (graceful no-op when unkeyed). *(clerk-js v5 import URL to verify against live docs when keys land)*
- [ ] `<ClerkProvider>` in React landing *(source in Downloads, outside repo — do at rebuild)*
- [x] Wire frontend copy into web-tier image (`COPY frontend /frontend`, served same-origin)
- [x] Azure deploy workflow (`.github/workflows/deploy-web-tier.yml` — build→ghcr→Azure Web App for Containers; app settings set in Azure, needs `AZURE_WEBAPP_*` secrets)
- [ ] End-to-end dry run against real services *(needs keys)*

## M2 — Harden + features
- [x] Admin backend: `/admin/jobs`, `/admin/analytics` (status counts + month minutes vs budget), `/admin/users` (job counts + month minutes), `/admin/cost` (budget/active/quota), `/admin/users/{id}/role` — all `require_admin`, tested
- [x] Admin dashboard UI (`frontend/admin.html` + `admin.js`): cost cards, status breakdown bars, jobs + users tables, Clerk-gated, 10s refresh, no chart lib *(needs browser verify when keys land)*
- [x] `usage_minutes` accounting from runner + monthly budget gate on dispatch *(Santa it.3)*
- [x] Datadog **agentless metrics** (`metrics.py` via HTTP API; emits dispatched/dispatch_failed/budget.blocked). ⚠️ APM/tracing **deferred** — needs an Agent sidecar F1 can't host (do it when web tier runs on a VM with dd-agent)
- [x] R2 lifecycle TTL on `jobs/` prefix (`scripts/r2_lifecycle.py`, 30-day expiry)
- [ ] Datadog dashboard + monitors (failure-rate, job-stuck, budget) *(needs key)*
- [ ] Variant B (long-video matrix: prep → matrix render → assemble, R2 round-trip)

## Santa Method round 1 (it.3) — NAUGHTY → fixed
Both independent reviewers FAILED. Fixed all 5 criticals + cheap correctness:
- [x] **Brief validation** — web tier defaults/clamps `target_duration_seconds` + rejects > threshold; runner injects default + on orchestrator 4xx marks Neon `failed` (no crash); sweep now also fails dead `running` jobs
- [x] **build-images.yml** — base tagged locally (`base-manim-agent:latest`) so service `FROM` resolves
- [x] **sweep off hot `/job` path** — time-gated + count-guarded, runs on `/jobs`+`/generate` only (Neon CU-hr safe)
- [x] **monthly minute budget gate** — `/generate` checks `global_month_minutes` vs `MONTHLY_MINUTE_BUDGET`; runner records `usage_minutes`
- [x] **long-video reject** at `/generate` (Variant B deferred to M2)
- [x] cheap: mandatory issuer when configured; admin role from DB (revocation); `analyze` fence-strip bug; Pydantic request models; full state mirror; worker-aware health gate

## Santa Method round 2 (it.4) — NICE ✅
Two FRESH independent reviewers (D, E) both PASS, **zero critical issues**. Reviewer D ran the 28-test suite to confirm. Converged in 2 rounds. M1 web-tier core is adversarially verified and shippable pending keys.
- Documented non-blocking limitation: `usage_minutes` is recorded on job completion, so in-flight jobs are invisible to the budget gate → worst-case overshoot ≈ `GLOBAL_CONCURRENCY_CAP` (3) × per-job minutes. Bounded + acceptable for the $0/3000-min target; revisit with dispatch-time reservation if it matters.

## Test status
`cd services/web-tier && python -m pytest tests/ -q` → **28 passed** (sqlite, mocked auth/dispatch/analyze; no keys).

## Notes for next iteration
- Docker not installed locally → compose merge validates in CI, not here.
- Keys are NOT yet provided; all key-dependent steps (M0 revoke/scrub, live e2e, Azure deploy) are stubbed/queued. Build everything that doesn't need keys first.
- `/analyze` web-tier impl needs `NVIDIA_API_KEY` — spec §11 updated to allow it on the web tier.
