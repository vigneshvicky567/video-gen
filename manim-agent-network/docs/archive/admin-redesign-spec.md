# Admin Console Redesign — Spec

**Goal:** Rebuild the admin dashboard with LangSmith-grade clarity — a 3-zone
observability console (sidebar · table · detail drawer) for inspecting video-gen
jobs. Reuse the existing `base.css` design tokens so it reads as the same product,
not a bolt-on tool.

**Reference:** LangSmith Tracing UI (left nav, dense run table, slide-in trace
detail with a Waterfall tab).

**Status:** spec / pre-build. No images generated yet (visual references come at
build time per the image-to-code flow).

---

## 1. Scope

In scope:
- Full rewrite of `frontend/admin.html`, `frontend/js/admin.js`.
- New `frontend/css/admin.css` (layout + components on top of `base.css` tokens).
- Jobs-centric console: stat strip → filterable table → detail drawer.
- Detail drawer with a **pipeline waterfall** (the LangSmith "Waterfall" analog),
  built from `stage_timings`.
- Live service-health row (uses existing `/services/health`).

Out of scope (call out, don't build):
- Users management — orchestrator has no users table (web-tier-only). Hidden in
  this build.
- New backend endpoints — the drawer reuses `GET /job/{id}` and
  `GET /services/health`. Only data-field fixes on the client.
- Auth — already bypassed (`require_admin` stub + Clerk script commented out).

---

## 2. Backend data contract (what exists today)

No new endpoints. The console consumes:

| Endpoint | Returns | Used by |
|---|---|---|
| `GET /admin/jobs` | list of `{job_id, topic, status, created_at, updated_at, completed_at, intro_duration_seconds}` | table |
| `GET /admin/analytics` | `{total, by_status:{}}` | stat strip, status bars |
| `GET /admin/cost` | `{active_jobs, ...}` (minutes are 0 locally) | stat strip |
| `GET /job/{id}` | **full job state** (see below) | detail drawer |
| `GET /services/health` | `{service: {status, latency_ms}}` | health row |
| `GET /video/{id}` | final mp4 | drawer "open video" |
| `GET /video/{id}/scene/{sceneId}` | per-scene mp4 | drawer scenes tab |

Full job state fields the drawer reads: `topic`, `status`, `brief`,
`stage_timings` (stage → seconds), `render_paths` (sceneId → path),
`audio_paths`, `image_paths`, `retry_counts`, `error_logs` (sceneId → text),
`overall_error`, `eta_seconds`, `final_output_path`, `dropped_scenes`.

### Client data fixes (current bugs)
- Use `job_id`, **not** `j.id`.
- Drop `owner_user_id` (doesn't exist on orchestrator).
- Status taxonomy is `completed` (not `done`), plus `partial`, `failed`,
  `cancelled`, and in-flight stages: `starting`, `pending`,
  `script_generation`, `code_generation`, `validation`,
  `voiceover_and_images`, `voiceover`, `image_fetch`, `assembly`.

---

## 3. Layout — three zones

```
┌────────────┬─────────────────────────────────────────────┬──────────────┐
│  SIDEBAR   │  MAIN                                         │  DRAWER      │
│  ~220px    │  breadcrumb                                   │  (slides in  │
│            │  stat strip  ▢ ▢ ▢ ▢ ▢                        │   on row     │
│  brand     │  toolbar  [filter chips] [search] [⟳ auto]    │   click,     │
│  ─ nav ─   │  ┌─ jobs table ──────────────────────────┐   │   ~42% wide) │
│  Overview  │  │ ● id   topic        stage    created   │   │  job header  │
│  Jobs ◀    │  │ ◐ id   topic        stage    created   │   │  ─ tabs ─    │
│  Analytics │  │ ✓ id   topic        stage    created   │   │  Overview    │
│  Services  │  │ ✕ id   topic        stage    created   │   │  Pipeline    │
│            │  └───────────────────────────────────────┘   │  Scenes      │
│  ⟳ 10s     │  service health: ● orch ● script ● code …     │  Error · Raw │
│  v / env   │                                               │              │
└────────────┴─────────────────────────────────────────────┴──────────────┘
```

- **No nested cards.** Stat tiles and table are flat bordered cells on `--ink-0`.
- Drawer overlays the right of MAIN (does not reflow the table); dim scrim behind
  on narrow screens, push-aside on wide.

### Sidebar
- Brand mark top (small, mono wordmark — no serif here).
- Nav groups with icon + label. Active = gold left-border (3px) + faint tint
  (`rgba(202,216,255,0.04)`), like LangSmith's active "Tracing".
- Footer: auto-refresh cadence + last-updated timestamp; env/version line.

### Stat strip (5 flat tiles)
Total jobs · Active · Completed · Failed · Runner-min (this month).
Big mono number, dim label under. Active tile pulses if `active_jobs > 0`.
Runner-min tile shows a thin usage bar; turns amber ≥80% (0 locally — show "—").

### Toolbar
- Status filter chips: All · Active · Completed · Partial · Failed · Cancelled
  ("Active" = any in-flight stage). Client-side filter.
- Search box: matches topic or id substring.
- Auto-refresh toggle (default on, 10s) + manual ⟳. Pause auto-refresh while the
  drawer is open on a **terminal** job (avoid yanking the user's focus).

---

## 4. Jobs table

Columns (compact rows ~40px, 13px text, mono for id/time):

| Col | Source | Render |
|---|---|---|
| Status | `status` | icon + label. Active → pulsing ring (blue). completed → check (green). failed → ✕ (red). partial → half (amber). cancelled → slash (faint). |
| Job ID | `job_id` | mono, first 8 chars, click-to-copy full. |
| Topic | `topic` | truncate ~60ch, full on hover (title). |
| Stage | `status` | humanized label + thin progress bar (stage index / 7 of pipeline; full+green when completed). |
| Created | `created_at` | relative ("2m ago"), full on hover. |
| Duration | `completed_at − created_at`, else live elapsed | mono `m:ss`. |

- Row hover: `--ink-2` bg. Selected row: gold left-border + tint (matches nav).
- Empty state: centered, calm — "No jobs yet" + faint hint, not a bare "none".
- Newest first (API already orders `created_at DESC`).

---

## 5. Detail drawer (the LangSmith trace panel)

Opens on row click; fetches `GET /job/{id}` for full state. Header: status badge,
topic (title), job id (mono, copy), close (✕ / Esc). Tabs below:

**Overview** — definition list: status, brief (target duration, audience level),
created / updated / completed, ETA (if in-flight), dropped scenes (if any).
If `final_output_path`: prominent "Open video ▸" → `/video/{id}`.

**Pipeline** *(signature component — the Waterfall)* — horizontal bars, one per
stage present in `stage_timings`, in pipeline order
(script_generation → code_generation → validation → voiceover → image_fetch →
assembly). Bar width ∝ elapsed seconds, normalized to the longest stage; mono
duration label at the bar end; stage name left. In-flight stage = animated/striped
bar. This is the page's centerpiece — give it room, this is where "clarity like
LangSmith" lives.

**Scenes** — grid of scene chips from `render_paths` (sceneId → path):
each chip = scene id, a "play ▸" link to `/video/{id}/scene/{sceneId}`, retry
badge if `retry_counts[id] > 0`, red dot if `error_logs[id]`. Fixed-aspect chips,
consistent radius (per FIXED MEDIA FRAME rule).

**Error** — `overall_error` (if any) at top, then per-scene `error_logs` as
collapsible mono blocks. Hidden tab if no errors.

**Raw** — full job-state JSON, monospace, subtle key/value tinting, copy-all.

Interaction: Esc closes; click-scrim closes; ↑/↓ (or j/k) move row selection and
keep the drawer synced (nice-to-have).

---

## 6. Service health row

Below the table: one line of dots from `/services/health` — orchestrator,
script-writer, code-generator, validator, voiceover, compositor, image-fetcher.
Green=ok, amber=degraded, red=down; latency ms on hover. Refreshes with the page.

---

## 7. Visual system (built on base.css tokens)

Reuse, don't reinvent:
- Surfaces: `--ink-0` app bg · `--ink-1` sidebar/drawer/table-head · `--ink-2`
  row hover · borders `--line` / `--line-strong`.
- Text: `--chalk` / `--chalk-dim` / `--chalk-faint`.
- Status: `--green` completed · `--red` failed · `--amber` partial ·
  `--blue` active/in-flight · `--chalk-faint` cancelled. `--gold` reserved for
  the primary accent (active nav, selected row) — used sparingly.
- Type: **Schibsted Grotesk** UI, **Spline Sans Mono** for ids/numbers/timings/
  JSON. **Drop Instrument Serif here** — a tool reads cleaner all-sans/mono (this
  is the one deliberate divergence from the marketing pages).
- **No grain overlay** in admin (atmosphere is for marketing; clarity is for the
  console).
- Density: dense table, generous outer padding. Radius: small (2–3px, matches
  existing buttons). Easing: `--ease-out`. No bounce/elastic.

---

## 8. Files

| File | Change |
|---|---|
| `frontend/admin.html` | restructure: sidebar + main + drawer skeleton; link `css/base.css` + `css/admin.css`; keep `API_BASE` shim + commented Clerk script. |
| `frontend/css/admin.css` | **new** — layout, table, drawer, waterfall, chips, health row. |
| `frontend/js/admin.js` | rewrite — correct data fields, table, filters, drawer fetch+render, waterfall, services health, copy/keyboard. |
| backend | **none** (reuse `/job/{id}`, `/services/health`). |

---

## 9. Build order

1. `admin.css` shell + `admin.html` 3-zone skeleton (sidebar/main/drawer empty).
2. `admin.js`: fetch `/admin/*`, render stat strip + table with **correct fields**
   (kills the current blank-id bug).
3. Filter chips + search + auto-refresh toggle.
4. Detail drawer: open/close, fetch `/job/{id}`, Overview + Raw tabs.
5. **Pipeline waterfall** tab (centerpiece).
6. Scenes tab + Error tab.
7. Service-health row.
8. Polish pass: empty/loading/error states, keyboard nav, copy buttons,
   responsive (drawer → full-width sheet under ~900px).

---

## 10. Open decisions

- **D1 — Serif in title?** Spec drops Instrument Serif for full tool-clarity.
  Alternative: keep serif on the one page `<h1>` for brand continuity.
- **D2 — Drawer width / behavior on wide screens:** push-aside (table reflows)
  vs overlay (table stays, drawer floats). Spec assumes overlay + scrim.
- **D3 — Waterfall depth:** flat per-stage bars (spec) vs nested (stage → per-scene
  sub-bars) if per-scene timings become available later.
