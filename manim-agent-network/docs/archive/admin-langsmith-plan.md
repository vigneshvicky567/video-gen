# Admin Console — Full LangSmith-Parity Plan (for Sonnet to build)

Reference target: LangSmith Tracing UI (sidebar · run table · nested Waterfall trace
detail with Input/Output/Attributes). This plan takes the **already-working** admin
console to full parity.

Files in play:
- `frontend/admin.html` · `frontend/css/admin.css` · `frontend/js/admin.js`
- `services/orchestrator/app/main.py` (API + pipeline timing)
- `services/orchestrator/app/core/graph.py` (LangGraph nodes — where per-node timing must be added)
- `services/orchestrator/app/db.py` (job store)

Cache-bust rule: bump `?v=lsN` on both `admin.css` and `admin.js` in `admin.html`
after every frontend change. Orchestrator code changes need a container restart
(ask the user first — see memory rule).

---

## 0. Current state (DONE — working, verified on live data)

Frontend (`?v=ls3`):
- 3-zone layout: sidebar (Jobs/Analytics/Services, collapse, Ctrl-K hint) · main · detail drawer + scrim.
- Stat strip: total / active / completed / failed / throughput (+ runner-min bar when budgeted).
- Toolbar: status filter chips, live search, time-range select, manual refresh.
- Jobs table: status icon (spinner/check/✕/◑/slash), topic (ellipsis), mono job id (click-copy), stage + colored progress bar, relative created, live duration. `table-layout: fixed`.
- Sortable headers (topic/status/created/duration), select-all + per-row checkbox, **bulk delete**.
- Auto-refresh 10s + toggle (pauses while inspecting a terminal job), 1s live-duration ticker.
- **Command palette** (Ctrl-K) — jump to job by topic/id, ↑↓/enter.
- Keyboard: Esc close, j/k run-nav, `\` collapse sidebar.
- Detail drawer tabs: **Waterfall** (nested tree) · Overview · Input · Output · Scenes · Error · Raw.
  - Waterfall: `orchestrator.pipeline` → `script_writer_node` / `code_generator_node` / `validator_node` / `voiceover_node·image_fetcher_node` / `assembler_node`, each expandable to **per-scene** children with ✓/✕ status, retry badges (↻N), audio/image flags.
  - Per-job actions wired to real endpoints: **Cancel** (`POST /job/{id}/cancel`), **Resume** (`/resume`), **Delete** (`DELETE /job/{id}`), **Open video** (`/video/{id}`).
  - Run nav (↑↓ prev/next job), copy id, copy raw JSON.
- Services view + fleet health strip (`GET /services/health`).

Backend (DONE): `/admin/jobs`, `/admin/analytics`, `/admin/cost` added to orchestrator
`main.py`; `require_admin` bypassed in web-tier `auth.py` (dev only).

Known shortcut: the Waterfall **parent** bars use real `stage_timings`; **scene
children** show real status but have **no per-scene duration** (not recorded yet).
Phase 1 fixes this.

---

## 1. P1 — Real per-node + per-scene timings (BACKEND, highest value)

Goal: the Waterfall shows true durations for every node and every scene, like
LangSmith — including repeated `code_generator_node` runs (retries) and routers.

### 1.1 Record node timings in the graph
In `graph.py`, wrap each node so it appends a span to state. Add a helper:

```python
# graph.py
import time
def _span(state, node, scene_id=None, t0=None, status="ok", error=None):
    ev = {"node": node, "scene_id": scene_id,
          "start": t0, "end": time.time(),
          "dur": round(time.time() - t0, 3) if t0 else 0.0,
          "status": status}
    if error: ev["error"] = str(error)[:300]
    state.setdefault("node_timings", []).append(ev)
```

In each `*_node` (script_writer, art_director, image_fetcher, code_generator,
validator, voiceover, assembler) capture `t0 = time.time()` at entry and call
`_span(...)` before returning. For per-scene work (code_generator, validator
render, voiceover, image_fetcher) emit one span **per scene_id** so children get
real durations. Keep spans append-only so retries naturally produce repeated rows.

### 1.2 Persist `node_timings`
- Add `"node_timings": []` to the `initial_state` dict in `main.py` (~L135).
- It rides through `db.update_job` automatically (state is JSON-blobbed). No schema change.

### 1.3 Frontend: render the real tree
In `admin.js` `dwWaterfall(st)`:
- If `st.node_timings?.length`, build the tree from it (group by `node`, nest
  `scene_id` children, use real `dur`, mark `status`), normalizing bar width to the
  max span. Show repeated nodes as sibling rows (codegen attempt 1, 2…).
- Else fall back to the current `stage_timings`-derived synthesis (keep it).

Acceptance: opening a job with retries shows `code_generator_node` twice with real
seconds, each scene child with its own duration; total matches pipeline elapsed.

---

## 2. P2 — Collapsible field viewer (Input / Output / Raw)

LangSmith's "Fields → request → brief {8 items}" is an expandable JSON tree. Build
one reusable component.

- Add `jsonTree(value, key, depth)` to `admin.js`: renders objects/arrays as
  expandable rows (chevron, key, `{N items}` / `[N]` summary), primitives inline,
  mono values, click-to-copy leaf values. Reuse the `.tgroup/.tnode/.ttoggle`
  pattern already in CSS (extend, don't duplicate).
- `dwInput`: render `{topic, brief, job_style, resume_state?}` via `jsonTree` instead
  of the flat `dl`.
- `dwRaw`: replace the `<pre>` dump with `jsonTree(st)` + keep "Copy JSON".
- Add **Plain / Pretty** toggle on Input & Output (LangSmith's Markdown/Plain toggle).

Acceptance: nested brief/script_meta expand and collapse; deep objects don't blow
the layout; copy works on any leaf.

---

## 3. P3 — Trace controls + 3-pane option

Match LangSmith's trace toolbar.

- Waterfall header row: **Expand all / Collapse all**, **Show durations** toggle,
  **Tree / Flat** toggle (flat = sort all spans by start, no nesting).
- Drawer **fullscreen** toggle (expand drawer to full width) and **side-by-side**
  layout (tree left, selected-span detail right) for wide screens.
- Clicking a scene/span row → inline detail (its code_path, render link, audio link,
  error) below or in the right sub-pane.

Acceptance: expand/collapse-all works; fullscreen toggles; clicking a scene span
reveals its artifacts without leaving the drawer.

---

## 4. P4 — Monitoring view (charts over time)

LangSmith has a Monitoring section. Add a nav item + view.

- Nav: add **Monitoring** between Jobs and Analytics.
- Compute client-side from `/admin/jobs` (already has created_at/status/duration),
  or add `GET /admin/timeseries?days=14` to orchestrator aggregating from `jobs`.
- Charts (no chart lib — small inline SVG/CSS, matches "no dep" style):
  - Jobs per day (stacked by status).
  - Success rate % over time.
  - Duration p50/p95 trend.
  - Active concurrency now + 24h sparkline.

Acceptance: Monitoring renders 3–4 charts from real data, respects the time-range select.

---

## 5. P5 — Table power features

- **Bulk cancel/resume/retry** (not just delete) in the bulk bar — loop the
  existing endpoints; skip non-applicable statuses, toast a summary.
- **Column config** popover: show/hide columns; persist to `localStorage`.
- **Saved views**: persist {filter, sort, timeRange, columns} as named views in
  `localStorage`, surfaced in a "Default View ▾" dropdown (LangSmith parity).
- **Pagination / load-more**: `/admin/jobs` currently caps at 200. Add `?offset=`
  to `db.list_jobs` + a "Load more" row (or virtualized scroll) for large histories.

Acceptance: can hide a column and it persists across reload; saved view restores
all settings; histories >200 are reachable.

---

## 6. P6 — Production hardening

- **Re-enable auth**: restore the original `require_admin` body in
  `services/web-tier/app/auth.py` and un-comment `clerk-auth.js` in `admin.html`;
  gate the orchestrator `/admin/*` routes too (currently open). Add a real
  `API_BASE`/CORS story for cross-origin (Live Server) use, or serve admin only
  same-origin from :8010.
- **Real runner-minutes**: orchestrator `/admin/cost` returns 0s. Compute monthly
  minutes from job durations (sum completed_at−created_at by month) or wire to the
  web-tier's minute ledger; show the budget bar with real data.
- **Live updates**: optional SSE — orchestrator `GET /admin/stream` pushing job
  state deltas; frontend swaps the 10s poll for EventSource, falls back to poll.
- **Scene poster frames**: generate a thumbnail per scene at render time; the
  Scenes grid + waterfall scene rows show posters instead of a ▸ glyph.

---

## 7. Suggested build order for Sonnet

1. **P1** (backend timings) — unlocks the real waterfall; biggest visible win. Needs orchestrator restart (ask user).
2. **P2** (json tree) — pure frontend, reused by P3.
3. **P3** (trace controls) — frontend, builds on P1/P2.
4. **P5** (table power) — frontend + small `db.list_jobs` offset.
5. **P4** (monitoring) — new view, optional backend aggregate.
6. **P6** (hardening) — before any non-local deployment.

Each phase: bump `?v=lsN`, verify with Playwright against `http://localhost:8010/admin.html`,
screenshot the drawer Waterfall + table. Keep the "no new dependency, vanilla JS,
built on base.css tokens" constraints. Don't restart the orchestrator without asking.

---

## 8. Design invariants (do not regress)

- Built on `base.css` tokens; blue `--acc` for active/selection; gold stays out of the tool.
- `[hidden] { display:none !important }` must remain (drawer/palette/bulkbar use `display:flex`).
- All-sans/mono (no Instrument Serif in admin); no grain overlay.
- Flat surfaces, no nested-card spam; dense table, generous outer padding.
- Every interactive element keyboard-reachable; Esc closes overlays.
