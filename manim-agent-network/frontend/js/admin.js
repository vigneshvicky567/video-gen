/* Admin console — LangSmith-style ops dashboard for video-gen jobs.
 * Pure vanilla, no deps. Talks to the orchestrator /admin/* + /job/* API.
 * Auth is bypassed in this build (see admin.html). */
(function () {
  "use strict";
  const BASE = window.API_BASE || "";
  const $ = (id) => document.getElementById(id);

  // ── API ──────────────────────────────────────────────────
  async function api(path, opts) {
    const token = window.__authToken ? await window.__authToken() : null;
    const headers = Object.assign({}, (opts && opts.headers) || {});
    if (token) headers["Authorization"] = "Bearer " + token;
    const res = await fetch(BASE + path, Object.assign({ headers }, opts));
    if (!res.ok) throw new Error(res.status + " " + res.statusText);
    const ct = res.headers.get("content-type") || "";
    return ct.includes("json") ? res.json() : res.text();
  }
  const apiPost = (p, body) => api(p, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  const apiDelete = (p) => api(p, { method: "DELETE" });

  // ── helpers ──────────────────────────────────────────────
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  const short = (id) => String(id || "").slice(0, 8);
  // Short generated name when the script writer has produced one; raw prompt
  // (which can be huge/messy) is the fallback, only until that title lands.
  const dispName = (j) => (j && (j.script_title || j.topic)) || "";

  function parseTs(s) {
    if (!s) return null;
    // SQLite "YYYY-MM-DD HH:MM:SS" is UTC — make it explicit.
    const d = new Date(String(s).replace(" ", "T") + (/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? "" : "Z"));
    return isNaN(d) ? null : d;
  }
  function relTime(s) {
    const d = parseTs(s); if (!d) return "—";
    const sec = Math.max(0, (Date.now() - d.getTime()) / 1000);
    if (sec < 60) return Math.floor(sec) + "s ago";
    if (sec < 3600) return Math.floor(sec / 60) + "m ago";
    if (sec < 86400) return Math.floor(sec / 3600) + "h ago";
    return Math.floor(sec / 86400) + "d ago";
  }
  function fmtDur(ms) {
    if (ms == null || ms < 0) return "—";
    const s = Math.floor(ms / 1000);
    const m = Math.floor(s / 60), h = Math.floor(m / 60);
    if (h) return h + "h " + (m % 60) + "m";
    return m + ":" + String(s % 60).padStart(2, "0");
  }
  function jobDurMs(j) {
    const a = parseTs(j.created_at); if (!a) return null;
    const b = parseTs(j.completed_at) || (isActive(j.status) ? new Date() : parseTs(j.updated_at));
    return b ? b.getTime() - a.getTime() : null;
  }
  function copy(text, msg) {
    navigator.clipboard.writeText(text).then(() => toast(msg || "Copied"));
  }
  let toastT;
  function toast(msg) {
    let t = document.querySelector(".toast");
    if (!t) { t = document.createElement("div"); t.className = "toast"; document.body.appendChild(t); }
    t.textContent = msg; clearTimeout(toastT);
    toastT = setTimeout(() => t.remove(), 1800);
  }

  // ── status taxonomy ──────────────────────────────────────
  const ACTIVE = new Set(["starting", "pending", "script_generation", "code_generation",
    "validation", "voiceover_and_images", "voiceover", "image_fetch", "assembly"]);
  const isActive = (s) => ACTIVE.has(s);
  function statusKind(s) {
    if (s === "completed") return "ok";
    if (s === "partial") return "warn";
    if (s === "failed") return "bad";
    if (s === "cancelled") return "cancelled";
    return "run";
  }
  const STATUS_ICON = { ok: "✓", bad: "✕", warn: "◑", cancelled: "／", run: "" };
  const STAGE_LABELS = {
    starting: "Starting", pending: "Pending", script_generation: "Script",
    code_generation: "Code", validation: "Validation", voiceover_and_images: "Voice + Images",
    voiceover: "Voiceover", image_fetch: "Images", assembly: "Assembly",
    completed: "Completed", partial: "Partial", failed: "Failed", cancelled: "Cancelled",
  };
  const PIPELINE = ["script_generation", "code_generation", "validation",
    "voiceover_and_images", "voiceover", "image_fetch", "assembly"];
  const STEP = { starting: 0, pending: 0, script_generation: 1, code_generation: 2,
    validation: 3, voiceover_and_images: 4, voiceover: 4, image_fetch: 4, assembly: 5,
    completed: 6, partial: 6, failed: 6, cancelled: 6 };
  const label = (s) => STAGE_LABELS[s] || s || "—";

  function statusIcon(s) {
    const k = statusKind(s);
    if (k === "run") return `<span class="s-ico run"></span>`;
    return `<span class="s-ico ${k}">${STATUS_ICON[k]}</span>`;
  }

  // ── state ────────────────────────────────────────────────
  const S = {
    jobs: [], analytics: null, cost: null, health: null,
    filter: "all", q: "", timeRange: 0,
    sortKey: "created_at", sortDir: "desc",
    selected: new Set(), view: "jobs",
    auto: true, openId: null, openTab: "waterfall", openState: null,
    paletteOpen: false, paletteIdx: 0, palItems: [],
  };
  let timer = null, ticker = null;

  // ── data load ────────────────────────────────────────────
  async function load() {
    try {
      const [jobs, analytics, cost, health] = await Promise.all([
        api("/admin/jobs"), api("/admin/analytics"), api("/admin/cost"),
        api("/services/health").catch(() => null),
      ]);
      S.jobs = jobs || []; S.analytics = analytics; S.cost = cost; S.health = health;
      $("lastUpdated").textContent = "updated " + new Date().toLocaleTimeString();
      renderAll();
    } catch (e) {
      $("jobsBody").innerHTML = `<tr><td colspan="7" class="t-empty">
        <div class="t-empty-title">Can't reach the orchestrator</div>
        <div>${esc(e.message)} — is it running on :8010?</div></td></tr>`;
    }
  }

  // ── filtering / sorting ──────────────────────────────────
  function visibleJobs() {
    let out = S.jobs.slice();
    if (S.timeRange > 0) {
      const cutoff = Date.now() - S.timeRange * 3600 * 1000;
      out = out.filter((j) => { const d = parseTs(j.created_at); return d && d.getTime() >= cutoff; });
    }
    if (S.filter === "active") out = out.filter((j) => isActive(j.status));
    else if (S.filter !== "all") out = out.filter((j) => j.status === S.filter);
    if (S.q) {
      const q = S.q.toLowerCase();
      out = out.filter((j) => dispName(j).toLowerCase().includes(q) || String(j.job_id).toLowerCase().includes(q));
    }
    const dir = S.sortDir === "asc" ? 1 : -1;
    out.sort((a, b) => {
      let av, bv;
      if (S.sortKey === "duration") { av = jobDurMs(a) || 0; bv = jobDurMs(b) || 0; }
      else if (S.sortKey === "status") { av = STEP[a.status] ?? 0; bv = STEP[b.status] ?? 0; }
      else if (S.sortKey === "topic") { av = dispName(a).toLowerCase(); bv = dispName(b).toLowerCase(); }
      else { av = parseTs(a.created_at)?.getTime() || 0; bv = parseTs(b.created_at)?.getTime() || 0; }
      return av < bv ? -dir : av > bv ? dir : 0;
    });
    return out;
  }

  // ── render: everything ───────────────────────────────────
  function renderAll() { renderStats(); renderNav(); renderTable(); renderAnalytics(); renderServices(); renderHealthStrip(); }

  function renderNav() {
    $("navJobsCount").textContent = S.jobs.length;
    const h = S.health;
    const dot = $("navHealthDot");
    if (h) {
      const vals = Object.values(h);
      const down = vals.some((v) => v.status === "down");
      const deg = vals.some((v) => v.status === "degraded");
      dot.className = "nav-dot " + (down ? "bad" : deg ? "warn" : "ok");
    }
  }

  function renderStats() {
    const a = S.analytics || { total: 0, by_status: {} }, c = S.cost || {};
    const by = a.by_status || {};
    const active = S.jobs.filter((j) => isActive(j.status)).length;
    const used = c.minutes_used || 0, budget = c.minute_budget || 0;
    const pct = budget ? Math.min(100, Math.round((used / budget) * 100)) : 0;
    const tiles = [
      { n: a.total || 0, l: "Total jobs" },
      { n: active, l: "Active now", cls: active ? "run" : "" },
      { n: by.completed || 0, l: "Completed", cls: "ok" },
      { n: by.failed || 0, l: "Failed", cls: (by.failed ? "bad" : "") },
      budget
        ? { n: `${used}/${budget}`, l: "Runner-min / mo", cls: pct >= 80 ? "warn" : "", bar: pct }
        : { n: active + (by.completed || 0), l: "Throughput" },
    ];
    $("stats").innerHTML = tiles.map((t) => `
      <div class="stat">
        <div class="stat-n ${t.cls || ""}">${esc(t.n)}</div>
        <div class="stat-l">${esc(t.l)}</div>
        ${t.bar != null ? `<div class="stat-bar"><i class="${pct >= 80 ? "warn" : ""}" style="width:${t.bar}%"></i></div>` : ""}
      </div>`).join("");
  }

  function renderTable() {
    const jobs = visibleJobs();
    const body = $("jobsBody");
    if (!jobs.length) {
      body.innerHTML = `<tr><td colspan="7" class="t-empty">
        <div class="t-empty-title">No jobs match</div>
        <div>Try a different filter or time range.</div></td></tr>`;
      syncSelectAll(); return;
    }
    body.innerHTML = jobs.map((j) => {
      const k = statusKind(j.status);
      const step = STEP[j.status] ?? 0, ppct = Math.round((step / 6) * 100);
      const pcls = k === "ok" ? "ok" : k === "bad" ? "bad" : k === "warn" ? "warn" : "";
      const sel = S.selected.has(j.job_id);
      const live = isActive(j.status);
      return `<tr data-id="${esc(j.job_id)}" class="${j.job_id === S.openId ? "is-selected" : ""}">
        <td class="c-check"><input type="checkbox" class="row-cb" data-id="${esc(j.job_id)}" ${sel ? "checked" : ""}/></td>
        <td class="c-stat">${statusIcon(j.status)}</td>
        <td class="c-name"><div class="td-topic" title="${esc(j.topic)}">${esc(dispName(j)) || "<span class='td-time'>untitled</span>"}</div></td>
        <td class="c-id"><span class="td-id copy-id" data-id="${esc(j.job_id)}" title="${esc(j.job_id)}">${esc(short(j.job_id))}</span></td>
        <td class="c-stage"><div class="stage-cell">
          <span class="stage-label">${esc(label(j.status))}</span>
          <span class="stage-prog"><i class="${pcls}" style="width:${k === "cancelled" ? 0 : ppct}%"></i></span>
        </div></td>
        <td class="c-time"><span class="td-time" title="${esc(j.created_at)}">${esc(relTime(j.created_at))}</span></td>
        <td class="c-dur"><span class="td-dur ${live ? "live-dur" : ""}" data-start="${esc(j.created_at)}">${esc(fmtDur(jobDurMs(j)))}</span></td>
      </tr>`;
    }).join("");
    syncSelectAll();
    markSort();
  }

  function markSort() {
    document.querySelectorAll("th.sortable").forEach((th) => {
      const on = th.dataset.sort === S.sortKey;
      th.classList.toggle("sorted", on);
      let a = th.querySelector(".arrow");
      if (!a) { a = document.createElement("span"); a.className = "arrow"; th.appendChild(a); }
      a.textContent = on ? (S.sortDir === "asc" ? "▲" : "▼") : "▾";
    });
  }

  function renderHealthStrip() {
    const h = S.health, el = $("healthStrip");
    if (!h) { el.innerHTML = ""; return; }
    const dots = Object.entries(h).map(([name, v]) => {
      const c = v.status === "ok" ? "var(--ok)" : v.status === "degraded" ? "var(--warn)" : "var(--bad)";
      return `<span class="hs" title="${esc(v.status)}${v.latency_ms != null ? " · " + v.latency_ms + "ms" : ""}">
        <span class="dot" style="background:${c}"></span>${esc(name)}</span>`;
    }).join("");
    el.innerHTML = `<span class="hs-label">Fleet</span>${dots}`;
  }

  function renderAnalytics() {
    const a = S.analytics; if (!a) return;
    const by = a.by_status || {}, total = Object.values(by).reduce((x, y) => x + y, 0) || 1;
    const colors = { completed: "var(--ok)", failed: "var(--bad)", partial: "var(--warn)", cancelled: "var(--chalk-faint)" };
    const rows = Object.entries(by).sort((x, y) => y[1] - x[1]).map(([s, n]) => {
      const c = colors[s] || "var(--run)";
      return `<div class="an-row">
        <span class="an-k">${esc(label(s))}</span>
        <span class="an-bar"><i style="width:${Math.round((n / total) * 100)}%;background:${c}"></i></span>
        <span class="an-n">${n}</span></div>`;
    }).join("");
    $("analyticsBody").innerHTML = `<div class="an-section-title">Status breakdown · ${a.total || total} jobs</div>${rows || "<div class='d-empty'>No jobs yet.</div>"}`;
  }

  function renderServices() {
    const h = S.health, el = $("servicesBody");
    if (!h) { el.innerHTML = "<div class='d-empty'>Health endpoint unavailable.</div>"; return; }
    el.innerHTML = Object.entries(h).map(([name, v]) => `
      <div class="svc">
        <span class="svc-dot ${esc(v.status)}"></span>
        <div><div class="svc-name">${esc(name)}</div>
          <div class="svc-meta">${esc(v.status)}</div></div>
        <span class="svc-meta-right">${v.latency_ms != null ? v.latency_ms + " ms" : "—"}</span>
      </div>`).join("");
  }

  // ── selection ────────────────────────────────────────────
  function syncSelectAll() {
    const vis = visibleJobs().map((j) => j.job_id);
    const all = vis.length && vis.every((id) => S.selected.has(id));
    const sa = $("selectAll"); if (sa) sa.checked = all;
    const n = S.selected.size;
    $("bulkbar").hidden = n === 0;
    $("bulkN").textContent = n;
  }

  // ── drawer ───────────────────────────────────────────────
  async function openJob(id) {
    S.openId = id; S.openTab = S.openTab || "waterfall";
    $("drawer").hidden = false; $("scrim").hidden = false;
    $("drawer").setAttribute("aria-hidden", "false");
    document.querySelectorAll("#jobsBody tr").forEach((tr) =>
      tr.classList.toggle("is-selected", tr.dataset.id === id));
    $("drawerBody").innerHTML = "<div class='d-empty'>Loading…</div>";
    try {
      S.openState = await api("/job/" + encodeURIComponent(id));
    } catch (e) {
      S.openState = null;
      $("drawerBody").innerHTML = `<div class='d-empty'>Failed to load job: ${esc(e.message)}</div>`;
    }
    renderDrawer();
  }
  function closeDrawer() {
    S.openId = null; S.openState = null;
    $("drawer").hidden = true; $("scrim").hidden = true;
    $("drawer").setAttribute("aria-hidden", "true");
    document.querySelectorAll("#jobsBody tr.is-selected").forEach((tr) => tr.classList.remove("is-selected"));
  }
  function stepJob(delta) {
    const vis = visibleJobs(); if (!vis.length) return;
    let i = vis.findIndex((j) => j.job_id === S.openId);
    i = i < 0 ? 0 : i + delta;
    if (i < 0 || i >= vis.length) return;
    openJob(vis[i].job_id);
  }

  function renderDrawer() {
    const st = S.openState; if (!st) return;
    const status = st.status, k = statusKind(status);
    $("dStat").innerHTML = statusIcon(status);
    $("dTopic").textContent = st.topic || "untitled";
    $("dId").textContent = S.openId;

    // per-job actions (real endpoints)
    const acts = [];
    if (isActive(status)) acts.push(`<button class="act-btn danger" data-act="cancel">■ Cancel</button>`);
    if (st.final_output_path) acts.push(`<button class="act-btn primary" data-act="video">▸ Open video</button>`);
    if (["failed", "cancelled", "partial"].includes(status)) acts.push(`<button class="act-btn" data-act="resume">↻ Resume</button>`);
    if (!isActive(status)) acts.push(`<button class="act-btn danger" data-act="delete">🗑 Delete</button>`);
    $("drawerActions").innerHTML = acts.join("");

    // error tab visibility
    const hasErr = !!(st.overall_error || (st.error_logs && Object.keys(st.error_logs).length));
    document.querySelector('.d-tab[data-tab="error"]').classList.toggle("is-hidden", !hasErr);
    if (S.openTab === "error" && !hasErr) S.openTab = "overview";
    document.querySelectorAll(".d-tab").forEach((t) => t.classList.toggle("is-active", t.dataset.tab === S.openTab));

    $("drawerBody").innerHTML = drawerTab(S.openTab, st);
  }

  function drawerTab(tab, st) {
    if (tab === "waterfall") return dwWaterfall(st);
    if (tab === "overview") return dwOverview(st);
    if (tab === "input") return dwInput(st);
    if (tab === "output") return dwOutput(st);
    if (tab === "scenes") return dwScenes(st);
    if (tab === "error") return dwError(st);
    if (tab === "raw") return dwRaw(st);
    return "";
  }

  function dwOverview(st) {
    const b = st.brief || {};
    const k = statusKind(st.status);
    const dur = (() => {
      const a = parseTs(st.created_at) || null;
      return a ? fmtDur((parseTs(st.completed_at) || new Date()).getTime() - a.getTime()) : "—";
    })();
    const rows = [
      ["Status", `<span class="d-badge ${k}">${statusIcon(st.status)} ${esc(label(st.status))}</span>`],
      b.target_duration_seconds ? ["Target", esc(b.target_duration_seconds) + "s"] : null,
      b.audience_level ? ["Audience", esc(b.audience_level)] : null,
      st.eta_seconds && isActive(st.status) ? ["ETA", "~" + Math.round(st.eta_seconds) + "s"] : null,
      ["Created", esc(st.created_at || "—")],
      ["Updated", esc(st.updated_at || "—")],
      st.completed_at ? ["Completed", esc(st.completed_at)] : null,
      ["Duration", `<span class="mono">${dur}</span>`],
      (st.dropped_scenes && st.dropped_scenes.length) ? ["Dropped scenes", esc(st.dropped_scenes.join(", "))] : null,
      st.overall_error ? ["Error", `<span style="color:var(--bad)">${esc(String(st.overall_error).slice(0, 120))}</span>`] : null,
    ].filter(Boolean);
    const dl = `<dl class="dl">${rows.map(([k2, v]) => `<dt>${k2}</dt><dd>${v}</dd>`).join("")}</dl>`;
    const cta = st.final_output_path
      ? `<a class="video-cta" href="${BASE}/video/${encodeURIComponent(S.openId)}" target="_blank" rel="noopener">▸ Open final video</a>` : "";
    return dl + cta;
  }

  function sceneUniverse(st) {
    const keys = new Set();
    ["code_paths", "render_paths", "audio_paths", "image_paths", "retry_counts", "error_logs", "previous_code", "audio_segments"]
      .forEach((k) => Object.keys(st[k] || {}).forEach((id) => keys.add(String(id))));
    const sc = st.script && st.script.scenes;
    if (Array.isArray(sc)) sc.forEach((s, i) => keys.add(String((s && (s.scene_id ?? s.id)) ?? i + 1)));
    return [...keys].map(Number).filter((n) => !isNaN(n)).sort((a, b) => a - b);
  }

  // Nested execution tree: orchestrator.pipeline → each node → per-scene children.
  function dwWaterfall(st) {
    const nt = st.node_timings;
    if (Array.isArray(nt) && nt.length > 0) return dwWaterfallFromNodeTimings(st, nt);
    return dwWaterfallFromStageTimings(st);
  }

  function dwWaterfallFromNodeTimings(st, timings) {
    const nodeOrder = [], byNode = {};
    for (const span of timings) {
      if (!byNode[span.node]) { byNode[span.node] = { node: [], scenes: {} }; nodeOrder.push(span.node); }
      if (span.scene_id != null) {
        const sid = String(span.scene_id);
        if (!byNode[span.node].scenes[sid]) byNode[span.node].scenes[sid] = [];
        byNode[span.node].scenes[sid].push(span);
      } else {
        byNode[span.node].node.push(span);
      }
    }
    const allDurs = timings.map((s) => s.dur || 0);
    const maxDur = Math.max(0.001, ...allDurs);
    const barW = (dur) => Math.max(2, Math.round(((dur || 0) / maxDur) * 100));
    const totalDur = timings.filter((s) => !byNode[s.node]?.scenes[s.scene_id]?.length || s.scene_id == null)
      .reduce((acc, s) => acc + (s.dur || 0), 0);

    const groups = nodeOrder.map((nodeName) => {
      const { node: nodeSpans, scenes } = byNode[nodeName];
      const ns = nodeSpans[0];
      const nodeDur = ns ? ns.dur : 0;
      const dotK = ns ? (ns.status === "error" ? "bad" : "ok") : "cancelled";
      const sceneIds = Object.keys(scenes).map(Number).sort((a, b) => a - b);
      const kids = sceneIds.map((sid) => {
        const attempts = scenes[String(sid)];
        const last = attempts[attempts.length - 1];
        const k = last.status === "error" ? "bad" : "ok";
        const retries = attempts.length > 1 ? `<span class="tflag warn">↻${attempts.length - 1}</span>` : "";
        return `<div class="tnode t-leaf">
          <span class="tspace"></span>
          <span class="tdot ${k}">${k === "bad" ? "✕" : "✓"}</span>
          <span class="tname">Scene #${sid}</span>
          <span class="tflags">${retries}</span>
          <span class="ttrack"><i style="width:${barW(last.dur)}%"></i></span>
          <span class="tdur">${(last.dur || 0).toFixed(2)}s</span>
        </div>`;
      }).join("");
      return `<div class="tgroup collapsed">
        <div class="tnode t1">
          <button class="ttoggle">▾</button>
          <span class="tdot ${dotK}">${dotK === "run" ? "" : dotK === "bad" ? "✕" : "✓"}</span>
          <span class="tname">${esc(nodeName)}</span>
          <span class="ttrack"><i style="width:${barW(nodeDur)}%"></i></span>
          <span class="tdur">${nodeDur ? nodeDur.toFixed(2) + "s" : "—"}</span>
        </div>
        <div class="tkids">${kids || '<div class="tnode t-leaf"><span class="tspace"></span><span class="tname tdim">no per-scene spans</span></div>'}</div>
      </div>`;
    }).join("");

    const rk = statusKind(st.status);
    const controls = `<div class="wf-controls">
      <button class="wf-ctl" data-wfctl="expand">⊕ Expand all</button>
      <button class="wf-ctl" data-wfctl="collapse">⊖ Collapse all</button>
      <span class="wf-badge">Real spans · ${timings.length}</span>
    </div>`;
    return controls + `<div class="tree">
      <div class="tgroup t0-group">
        <div class="tnode t0">
          <button class="ttoggle">▾</button>
          <span class="tdot ${rk}">${rk === "run" ? "" : (STATUS_ICON[rk] || "")}</span>
          <span class="tname strong">orchestrator.pipeline</span>
          <span class="ttrack"><i style="width:100%"></i></span>
          <span class="tdur">${totalDur.toFixed(2)}s</span>
        </div>
        <div class="tkids">${groups}</div>
      </div>
    </div>`;
  }

  function dwWaterfallFromStageTimings(st) {
    const t = st.stage_timings || {};
    const total = Object.values(t).reduce((a, b) => a + (Number(b) || 0), 0);
    const max = Math.max(0.001, ...Object.values(t).map((x) => Number(x) || 0));
    const ids = sceneUniverse(st);
    const cp = st.code_paths || {}, rp = st.render_paths || {}, ap = st.audio_paths || {},
      ip = st.image_paths || {}, rc = st.retry_counts || {}, el = st.error_logs || {};
    const barW = (sec) => Math.max(2, Math.round((sec / max) * 100));

    const stages = [
      { key: "script_generation", name: "script_writer_node", kid: () => ({ ok: true }) },
      { key: "code_generation", name: "code_generator_node", kid: (id) => ({
          ok: !!(cp[id] || rp[id]), err: !!el[id] && !rp[id],
          flags: rc[id] ? `<span class="tflag warn">↻${rc[id]}</span>` : "" }) },
      { key: "validation", name: "validator_node", kid: (id) => ({ ok: !!rp[id], err: !!el[id] && !rp[id] }) },
      { key: "voiceover_and_images", name: "voiceover_node · image_fetcher_node", kid: (id) => ({
          ok: !!ap[id],
          flags: `${ap[id] ? '<span class="tflag">🔊</span>' : ""}${ip[id] ? '<span class="tflag">🖼</span>' : ""}` }) },
    ];

    const sceneRow = (id, info) => {
      const k = info.err ? "bad" : info.ok ? "ok" : "cancelled";
      return `<div class="tnode t-leaf">
        <span class="tspace"></span>
        <span class="tdot ${k}">${info.err ? "✕" : info.ok ? "✓" : "·"}</span>
        <span class="tname">Scene #${id}</span>
        <span class="tflags">${info.flags || ""}</span></div>`;
    };

    const groups = stages.map((s) => {
      const has = s.key in t;
      const sec = Number(t[s.key]) || 0;
      const running = st.status === s.key;
      const kids = ids.map((id) => sceneRow(id, s.kid(String(id)))).join("");
      const dotK = running ? "run" : has ? "ok" : "cancelled";
      return `<div class="tgroup collapsed">
        <div class="tnode t1">
          <button class="ttoggle">▾</button>
          <span class="tdot ${dotK}">${running ? "" : has ? "✓" : "·"}</span>
          <span class="tname">${esc(s.name)}</span>
          <span class="ttrack"><i class="${running ? "run" : ""}" style="width:${has ? barW(sec) : 0}%"></i></span>
          <span class="tdur">${has ? sec.toFixed(2) + "s" : "—"}</span>
        </div>
        <div class="tkids">${kids || `<div class="tnode t-leaf"><span class="tspace"></span><span class="tname tdim">no scenes</span></div>`}</div>
      </div>`;
    }).join("");

    const asm = st.final_output_path
      ? `<div class="tnode t1"><span class="tnotoggle"></span><span class="tdot ok">✓</span><span class="tname">assembler_node</span><span class="ttrack"></span><span class="tdur">done</span></div>`
      : (st.status === "assembly"
        ? `<div class="tnode t1"><span class="tnotoggle"></span><span class="tdot run"></span><span class="tname">assembler_node</span><span class="ttrack"></span><span class="tdur">…</span></div>` : "");

    const rk = statusKind(st.status);
    const controls = `<div class="wf-controls">
      <button class="wf-ctl" data-wfctl="expand">⊕ Expand all</button>
      <button class="wf-ctl" data-wfctl="collapse">⊖ Collapse all</button>
    </div>`;
    return controls + `<div class="tree">
      <div class="tgroup t0-group">
        <div class="tnode t0">
          <button class="ttoggle">▾</button>
          <span class="tdot ${rk}">${rk === "run" ? "" : (STATUS_ICON[rk] || "")}</span>
          <span class="tname strong">orchestrator.pipeline</span>
          <span class="ttrack"><i style="width:100%"></i></span>
          <span class="tdur">${total.toFixed(2)}s</span>
        </div>
        <div class="tkids">${groups}${asm}</div>
      </div>
    </div>
    <div class="wf-total">Recorded <span class="mono">${total.toFixed(1)}s</span> · ${ids.length} scenes · expand nodes for per-scene steps</div>`;
  }

  function dwInput(st) {
    const b = st.brief || {}, js = st.job_style || {};
    const base = [
      ["topic", `<span class="jt-str">"${esc(st.topic || "")}"</span>`],
      ["job_id", `<span class="mono">${esc(st.job_id || S.openId)}</span>`],
    ];
    const briefCount = Object.keys(b).length;
    const briefSection = briefCount
      ? `<div class="d-section-title">Brief · ${briefCount} fields</div><div class="jt-root">${jsonTree(b)}</div>`
      : "";
    const styleSection = js.name
      ? `<div class="d-section-title">Job style</div>
         <dl class="dl"><dt>name</dt><dd>${esc(js.name)}</dd>
         <dt>palette</dt><dd>${["palette_bg", "palette_fg", "palette_accent"].map((k) =>
           js[k] ? `<span class="sw" style="background:${esc(js[k])}" title="${esc(js[k])}"></span>` : "").join("")}</dd>
         <dt>motion</dt><dd>${esc(js.motion_sig || "—")}${js.energy ? " · " + esc(js.energy) : ""}</dd></dl>`
      : "";
    return `<dl class="dl">${base.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>${briefSection}${styleSection}`;
  }

  function dwOutput(st) {
    const sm = st.script_meta || {};
    const rendered = Object.keys(st.render_paths || {}).length;
    const planned = (st.script && Array.isArray(st.script.scenes)) ? st.script.scenes.length : sceneUniverse(st).length;
    const rows = [
      ["final video", st.final_output_path
        ? `<a class="link" href="${BASE}/video/${encodeURIComponent(S.openId)}" target="_blank" rel="noopener">open ▸</a>`
        : "<span class='tdim'>not ready</span>"],
      ["scenes rendered", `${rendered} / ${planned}`],
      ["audio segments", Object.keys(st.audio_segments || {}).length],
      (st.dropped_scenes && st.dropped_scenes.length) ? ["dropped scenes", esc(st.dropped_scenes.join(", "))] : null,
      sm.mode ? ["script mode", esc(sm.mode)] : null,
    ].filter(Boolean);
    const warn = (sm.warnings && sm.warnings.length)
      ? `<div class="d-section-title">Warnings · ${sm.warnings.length}</div><div class="code-block">${esc(sm.warnings.join("\n"))}</div>` : "";
    const audit = sm.duration_audit
      ? `<div class="d-section-title">Duration audit</div><div class="code-block">${esc(typeof sm.duration_audit === "string" ? sm.duration_audit : JSON.stringify(sm.duration_audit, null, 2))}</div>` : "";
    const cta = st.final_output_path
      ? `<div style="margin:14px 0"><a class="video-cta" href="${BASE}/video/${encodeURIComponent(S.openId)}" target="_blank" rel="noopener">▸ Open final video</a></div>` : "";
    return `<dl class="dl">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>${cta}${warn}${audit}`;
  }

  function dwScenes(st) {
    const rp = st.render_paths || {}, ids = Object.keys(rp);
    if (!ids.length) return `<div class="d-empty">No scenes rendered yet.</div>`;
    const errs = st.error_logs || {}, retries = st.retry_counts || {};
    const chips = ids.sort((a, b) => Number(a) - Number(b)).map((id) => {
      const r = retries[id] || 0, hasErr = !!errs[id];
      return `<a class="scene-chip" href="${BASE}/video/${encodeURIComponent(S.openId)}/scene/${encodeURIComponent(id)}" target="_blank" rel="noopener">
        <div class="scene-vid"><span class="play">▸</span></div>
        <div class="scene-foot">
          <span class="scene-id">#${esc(id)}</span>
          ${r ? `<span class="scene-retry">↻${r}</span>` : ""}
          ${hasErr ? `<span class="scene-err-dot" title="had errors"></span>` : ""}
        </div></a>`;
    }).join("");
    return `<div class="scenes-grid">${chips}</div>`;
  }

  function dwError(st) {
    let h = "";
    if (st.overall_error) h += `<div class="err-block"><div class="err-head">Overall error</div><div class="code-block">${esc(st.overall_error)}</div></div>`;
    const el = st.error_logs || {};
    Object.keys(el).forEach((id) => {
      h += `<div class="err-block"><div class="err-head">Scene #${esc(id)}</div><div class="code-block">${esc(el[id])}</div></div>`;
    });
    return h || `<div class="d-empty">No errors. 🎉</div>`;
  }

  // ── JSON tree viewer (P2) ─────────────────────────────────
  function jsonTree(value, key, depth) {
    depth = depth || 0;
    const isArr = Array.isArray(value);
    const isObj = value !== null && typeof value === "object" && !isArr;
    const keyHtml = key !== undefined
      ? `<span class="jt-key">${esc(String(key))}</span><span class="jt-colon">: </span>` : "";

    if (isArr || isObj) {
      const entries = isArr ? value.map((v, i) => [i, v]) : Object.entries(value);
      const count = entries.length;
      if (count === 0) {
        return `<div class="jt-row"><span class="tspace"></span>${keyHtml}<span class="jt-sum">${isArr ? "[]" : "{}"}</span></div>`;
      }
      const summary = isArr ? `[${count}]` : `{${count} items}`;
      const kids = entries.map(([k, v]) => jsonTree(v, k, depth + 1)).join("");
      return `<div class="tgroup collapsed">
        <div class="tnode jt-row"><button class="ttoggle">▾</button>${keyHtml}<span class="jt-sum">${esc(summary)}</span></div>
        <div class="tkids">${kids}</div>
      </div>`;
    }
    if (value === null) {
      return `<div class="jt-row"><span class="tspace"></span>${keyHtml}<span class="jt-null">null</span></div>`;
    }
    const t = typeof value;
    const cls = t === "number" ? "jt-num" : t === "boolean" ? "jt-bool" : "jt-str";
    const display = t === "string" ? `"${esc(String(value).slice(0, 300))}"` : esc(String(value));
    const full = JSON.stringify(value);
    return `<div class="jt-row"><span class="tspace"></span>${keyHtml}<span class="${cls} copy-val" data-val="${esc(full)}">${display}</span></div>`;
  }

  function dwRaw(st) {
    return `<div class="raw-actions"><button class="btn-soft" id="copyRaw">⧉ Copy JSON</button></div>
      <div class="jt-root">${jsonTree(st)}</div>`;
  }

  // ── job actions ──────────────────────────────────────────
  async function doAction(act) {
    const id = S.openId; if (!id) return;
    try {
      if (act === "video") { window.open(BASE + "/video/" + encodeURIComponent(id), "_blank"); return; }
      if (act === "cancel") { await apiPost(`/job/${id}/cancel`); toast("Cancel requested"); }
      if (act === "resume") { await apiPost(`/job/${id}/resume`); toast("Resume started"); }
      if (act === "delete") {
        if (!confirm("Delete this job permanently?")) return;
        await apiDelete(`/job/${id}`); toast("Job deleted"); closeDrawer();
      }
      await load();
      if (S.openId) openJob(S.openId);
    } catch (e) { toast("Failed: " + e.message); }
  }

  async function bulkDelete() {
    const ids = [...S.selected];
    if (!ids.length || !confirm(`Delete ${ids.length} job(s)? Running jobs are skipped.`)) return;
    let ok = 0, skip = 0;
    for (const id of ids) {
      try { await apiDelete(`/job/${id}`); ok++; } catch (e) { skip++; }
    }
    S.selected.clear();
    toast(`Deleted ${ok}${skip ? `, ${skip} skipped` : ""}`);
    await load();
  }

  async function bulkCancel() {
    const ids = [...S.selected].filter((id) => { const j = S.jobs.find((x) => x.job_id === id); return j && isActive(j.status); });
    if (!ids.length) { toast("No active jobs selected"); return; }
    let ok = 0;
    for (const id of ids) { try { await apiPost(`/job/${id}/cancel`); ok++; } catch (e) {} }
    toast(`Cancel requested for ${ok} job(s)`);
    await load();
  }

  async function bulkResume() {
    const ids = [...S.selected].filter((id) => { const j = S.jobs.find((x) => x.job_id === id); return j && ["failed", "cancelled", "partial"].includes(j.status); });
    if (!ids.length) { toast("No resumable jobs selected"); return; }
    let ok = 0;
    for (const id of ids) { try { await apiPost(`/job/${id}/resume`); ok++; } catch (e) {} }
    toast(`Resume started for ${ok} job(s)`);
    await load();
  }

  // ── command palette ──────────────────────────────────────
  function openPalette() {
    S.paletteOpen = true; S.paletteIdx = 0;
    $("paletteWrap").hidden = false;
    const inp = $("paletteInput"); inp.value = ""; inp.focus();
    renderPalette("");
  }
  function closePalette() { S.paletteOpen = false; $("paletteWrap").hidden = true; }
  function renderPalette(q) {
    q = (q || "").toLowerCase();
    S.palItems = S.jobs.filter((j) =>
      !q || (j.topic || "").toLowerCase().includes(q) || String(j.job_id).toLowerCase().includes(q)
    ).slice(0, 20);
    const list = $("paletteList");
    if (!S.palItems.length) { list.innerHTML = `<div class="palette-empty">No matching jobs</div>`; return; }
    list.innerHTML = S.palItems.map((j, i) => `
      <div class="palette-item ${i === S.paletteIdx ? "is-active" : ""}" data-id="${esc(j.job_id)}">
        ${statusIcon(j.status)}
        <span class="pi-topic">${esc(j.topic || "untitled")}</span>
        <span class="pi-id">${esc(short(j.job_id))}</span>
      </div>`).join("");
  }
  function palettePick(i) {
    const j = S.palItems[i]; if (!j) return;
    closePalette(); openJob(j.job_id);
  }

  // ── views ────────────────────────────────────────────────
  function setView(v) {
    S.view = v;
    document.querySelectorAll(".nav-item[data-view]").forEach((b) => b.classList.toggle("is-active", b.dataset.view === v));
    ["jobs", "analytics", "services"].forEach((x) => { const el = $("view-" + x); if (el) el.hidden = x !== v; });
    $("toolbar").style.display = v === "jobs" ? "" : "none";
    $("stats").style.display = v === "jobs" ? "" : "none";
    const tt = { jobs: "Jobs", analytics: "Analytics", services: "Services" }[v];
    $("viewTitle").textContent = tt; $("crumbView").textContent = tt;
    $("sidebar").classList.remove("open");
  }

  // ── live duration ticker ─────────────────────────────────
  function tick() {
    document.querySelectorAll(".live-dur").forEach((el) => {
      const d = parseTs(el.dataset.start);
      if (d) el.textContent = fmtDur(Date.now() - d.getTime());
    });
  }

  // ── auto refresh ─────────────────────────────────────────
  function setupTimers() {
    if (timer) clearInterval(timer);
    timer = setInterval(() => {
      // don't yank focus while inspecting a terminal job
      if (S.openId && S.openState && !isActive(S.openState.status)) return;
      if (S.auto) load();
    }, 10000);
    if (!ticker) ticker = setInterval(tick, 1000);
  }

  // ── events ───────────────────────────────────────────────
  function wire() {
    // nav
    $("nav").addEventListener("click", (e) => {
      const b = e.target.closest(".nav-item[data-view]"); if (b) setView(b.dataset.view);
    });
    $("paletteOpen").addEventListener("click", openPalette);
    $("collapseBtn").addEventListener("click", () => $("layout").classList.toggle("side-collapsed"));
    $("showSide").addEventListener("click", () => $("sidebar").classList.toggle("open"));

    // toolbar
    $("statusChips").addEventListener("click", (e) => {
      const c = e.target.closest(".chip"); if (!c) return;
      S.filter = c.dataset.f;
      document.querySelectorAll(".chip").forEach((x) => x.classList.toggle("is-active", x === c));
      renderTable();
    });
    let qT;
    $("search").addEventListener("input", (e) => { clearTimeout(qT); qT = setTimeout(() => { S.q = e.target.value.trim(); renderTable(); }, 120); });
    $("timeRange").addEventListener("change", (e) => { S.timeRange = Number(e.target.value); renderTable(); });
    $("refreshBtn").addEventListener("click", load);
    $("autoToggle").addEventListener("change", (e) => { S.auto = e.target.checked; });

    // sort
    document.querySelectorAll("th.sortable").forEach((th) => th.addEventListener("click", () => {
      const k = th.dataset.sort;
      if (S.sortKey === k) S.sortDir = S.sortDir === "asc" ? "desc" : "asc";
      else { S.sortKey = k; S.sortDir = k === "topic" ? "asc" : "desc"; }
      renderTable();
    }));

    // table interactions
    $("jobsBody").addEventListener("click", (e) => {
      const cb = e.target.closest(".row-cb");
      if (cb) { cb.checked ? S.selected.add(cb.dataset.id) : S.selected.delete(cb.dataset.id); syncSelectAll(); return; }
      const cid = e.target.closest(".copy-id");
      if (cid) { e.stopPropagation(); copy(cid.dataset.id, "Job id copied"); return; }
      const tr = e.target.closest("tr[data-id]");
      if (tr) openJob(tr.dataset.id);
    });
    $("selectAll").addEventListener("change", (e) => {
      const vis = visibleJobs().map((j) => j.job_id);
      if (e.target.checked) vis.forEach((id) => S.selected.add(id));
      else vis.forEach((id) => S.selected.delete(id));
      renderTable();
    });
    $("bulkDelete").addEventListener("click", bulkDelete);
    $("bulkCancel").addEventListener("click", bulkCancel);
    $("bulkResume").addEventListener("click", bulkResume);
    $("bulkClear").addEventListener("click", () => { S.selected.clear(); renderTable(); });

    // drawer
    $("drawerClose").addEventListener("click", closeDrawer);
    $("scrim").addEventListener("click", closeDrawer);
    $("prevJob").addEventListener("click", () => stepJob(-1));
    $("nextJob").addEventListener("click", () => stepJob(1));
    $("dCopyId").addEventListener("click", () => copy(S.openId, "Job id copied"));
    $("drawerTabs").addEventListener("click", (e) => {
      const t = e.target.closest(".d-tab"); if (!t) return;
      S.openTab = t.dataset.tab;
      document.querySelectorAll(".d-tab").forEach((x) => x.classList.toggle("is-active", x === t));
      $("drawerBody").innerHTML = drawerTab(S.openTab, S.openState);
    });
    $("drawerActions").addEventListener("click", (e) => {
      const b = e.target.closest(".act-btn"); if (b) doAction(b.dataset.act);
    });
    $("drawerBody").addEventListener("click", (e) => {
      if (e.target.id === "copyRaw") { copy(JSON.stringify(S.openState, null, 2), "JSON copied"); return; }
      const cv = e.target.closest(".copy-val");
      if (cv) { copy(cv.dataset.val || cv.textContent, "Copied"); return; }
      const wfCtl = e.target.closest("[data-wfctl]");
      if (wfCtl) {
        const action = wfCtl.dataset.wfctl;
        const body = $("drawerBody");
        if (action === "expand") body.querySelectorAll(".tgroup").forEach((g) => g.classList.remove("collapsed"));
        else if (action === "collapse") body.querySelectorAll(".tgroup:not(.t0-group)").forEach((g) => g.classList.add("collapsed"));
        return;
      }
      const tg = e.target.closest(".ttoggle");
      if (tg) { const g = tg.closest(".tgroup"); if (g) g.classList.toggle("collapsed"); }
    });

    // palette
    $("paletteInput").addEventListener("input", (e) => { S.paletteIdx = 0; renderPalette(e.target.value); });
    $("paletteList").addEventListener("click", (e) => {
      const it = e.target.closest(".palette-item"); if (it) palettePick(S.palItems.findIndex((j) => j.job_id === it.dataset.id));
    });
    $("paletteWrap").addEventListener("click", (e) => { if (e.target === $("paletteWrap")) closePalette(); });

    // keyboard
    document.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); S.paletteOpen ? closePalette() : openPalette(); return; }
      if (S.paletteOpen) {
        if (e.key === "Escape") closePalette();
        else if (e.key === "ArrowDown") { e.preventDefault(); S.paletteIdx = Math.min(S.palItems.length - 1, S.paletteIdx + 1); renderPalette($("paletteInput").value); }
        else if (e.key === "ArrowUp") { e.preventDefault(); S.paletteIdx = Math.max(0, S.paletteIdx - 1); renderPalette($("paletteInput").value); }
        else if (e.key === "Enter") palettePick(S.paletteIdx);
        return;
      }
      const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
      if (e.key === "Escape" && S.openId) closeDrawer();
      if (typing) return;
      if (e.key === "\\") $("layout").classList.toggle("side-collapsed");
      if (S.openId) {
        if (e.key === "j" || e.key === "ArrowDown") { e.preventDefault(); stepJob(1); }
        if (e.key === "k" || e.key === "ArrowUp") { e.preventDefault(); stepJob(-1); }
      }
    });
  }

  // ── boot ─────────────────────────────────────────────────
  (async () => {
    await (window.__authReady || Promise.resolve());
    wire(); setView("jobs"); setupTimers();
    await load();
  })();
})();
