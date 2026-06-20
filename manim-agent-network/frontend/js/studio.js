/* Reel — "the interface IS a strip of film."
   A small SPA over the Manim Agent Network pipeline. Three stages:
     home  — compose an idea
     cut   — a finished film (projection screen + filmstrip of scenes)
     lab   — a film in development (the developing track + render log)
   Wired live: /jobs, /services/health, /job/{id}, /analyze, /generate, /video/...
   Shells mount once per (view, job); live data is patched in place so polling
   never interrupts video playback, typing, or scroll. */

(() => {
  "use strict";

  const root = document.getElementById("app");
  const NAME = "Vicky";

  /* ── services / starters ── */
  const SERVICES = ["orchestrator", "script-writer", "code-generator",
                    "validator", "voiceover", "compositor", "image-fetcher"];
  const STARTERS = [
    "How gradient descent finds minima",
    "What a transformer actually attends to",
    "The central limit theorem in motion",
    "Binary search, step by step",
    "How RSA encryption works",
  ];

  /* ── developing-track stages (display order) ── */
  const STAGES = [
    { nm: "Story",  ic: '<path d="M5 4h14M5 9h14M5 14h9"/>',                 keys: ["starting", "pending", "script_generation"] },
    { nm: "Create", ic: '<path d="M8 6l-4 6 4 6M16 6l4 6-4 6"/>',           keys: ["code_generation"] },
    { nm: "Render", ic: '<path d="M5 12l4 4L19 6"/>',                        keys: ["validation"] },
    { nm: "Voice",  ic: '<path d="M12 4v16M7 9v6M17 9v6"/>',                 keys: ["voiceover", "voiceover_and_images"] },
    { nm: "Finish", ic: '<path d="M4 7h7v7H4zM13 10h7v7h-7z"/>',            keys: ["assembly"] },
    { nm: "Done",   ic: '<circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2"/>', keys: ["completed"] },
  ];

  /* ── state ── */
  let jobs = [], health = null;
  let selectedId = null, jobState = null, prevState = null;
  let view = "home";
  let etaSmooth = null, createdMs = null, completedMs = null;
  let feedLines = [];                 // accumulated live log lines for the lab
  let mountKey = null;                // what shell is currently rendered
  let lastJobsSig = "", lastHealthSig = "";
  let setupOpen = false;

  /* library/history view state */
  let libQuery = "", libFilter = "all";
  const LIB_FILTERS = [["all", "All"], ["completed", "Ready"], ["running", "Rendering"], ["failed", "Failed"]];

  /* setup/analyze working state */
  let analyzer = null, setupAns = {}, setupPrompt = "", setupBusy = false;

  /* render engine for the NEXT job: "hybrid" (per-scene auto), "manim", "hyperframes" */
  let renderMode = "hybrid";
  const RENDER_MODES = [["hybrid", "Auto"], ["manim", "Classic"], ["hyperframes", "Visual"]];
  /* Visual templates — mirror shared/schemas/common.py VISUAL_STYLES. The picker
     sends the KEY as visual_style; art_director_node matches it. Keep in sync. */
  const STYLES = [
    { k: "swiss_pulse",     n: "Swiss Pulse",     bg: "#f5f5f0", fg: "#1a1a1a", ac: "#e63946", v: "Grid precision · clean cuts" },
    { k: "velvet_standard", n: "Velvet Standard", bg: "#1a0a2e", fg: "#f0e6ff", ac: "#b388ff", v: "Slow luxury · blur crossfades" },
    { k: "deconstructed",   n: "Deconstructed",   bg: "#0d0d0d", fg: "#f0f0f0", ac: "#ff6b00", v: "Fragmented · asymmetric" },
    { k: "maximalist_type", n: "Maximalist Type", bg: "#fffbe6", fg: "#1a1a00", ac: "#ffcc00", v: "Bold weight · scale surprises" },
    { k: "data_drift",      n: "Data Drift",      bg: "#0a0f1c", fg: "#e8f4fd", ac: "#00d4ff", v: "Analytical · chart reveals" },
    { k: "soft_signal",     n: "Soft Signal",     bg: "#f7f0e8", fg: "#2d2820", ac: "#7ec8a4", v: "Organic · gentle drift" },
    { k: "folk_frequency",  n: "Folk Frequency",  bg: "#2d1b0e", fg: "#f5e6d3", ac: "#e8a87c", v: "Handcrafted · warm texture" },
    { k: "shadow_cut",      n: "Shadow Cut",      bg: "#121212", fg: "#ffffff", ac: "#ff3366", v: "Cinematic · hard cuts" },
  ];

  /* ── utils ── */
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fmtClock = (d) => d.toLocaleTimeString("en-GB", { hour12: false });
  function parseUtc(ts) { if (!ts) return null; const d = new Date(ts.replace(" ", "T") + "Z"); return isNaN(d) ? null : d.getTime(); }
  function fmtDur(sec) {
    if (sec == null || !isFinite(sec) || sec < 0) return "—";
    sec = Math.round(sec); const m = Math.floor(sec / 60), s = sec % 60;
    if (m >= 60) return `${Math.floor(m / 60)}h ${m % 60}m`;
    return `${m}:${String(s).padStart(2, "0")}`;
  }
  function timeAgo(ms) {
    if (!ms) return "";
    const s = Math.max(0, (Date.now() - ms) / 1000);
    if (s < 60) return "just now";
    if (s < 3600) return `${Math.floor(s / 60)} min ago`;
    if (s < 86400) return `${Math.floor(s / 3600)} hr ago`;
    return `${Math.floor(s / 86400)}d ago`;
  }

  const RUNNING = new Set(["starting", "pending", "script_generation", "code_generation",
    "validation", "voiceover", "voiceover_and_images", "assembly"]);
  function chipText(s) {
    return ({
      starting: "starting", pending: "starting", script_generation: "writing story",
      code_generation: "creating scenes", validation: "rendering", voiceover: "adding voice",
      voiceover_and_images: "adding voice", assembly: "finishing up",
      completed: "ready", failed: "failed", cancelled: "stopped",
    })[s] || s || "unknown";
  }
  function curStageIdx(status) {
    if (status === "completed") return 5;
    const i = STAGES.findIndex((st) => st.keys.includes(status));
    return i < 0 ? 0 : i;
  }
  function counts(state) {
    return {
      scenes: state.script?.scenes?.length || 0,
      coded: Object.keys(state.code_paths || {}).length,
      rendered: Object.keys(state.render_paths || {}).length,
      voiced: Object.keys(state.audio_paths || {}).length,
      retries: Object.values(state.retry_counts || {}).reduce((a, b) => a + (b || 0), 0),
    };
  }
  function failStageIdx(state) {
    // Returns the stage INDEX where the job was working when it stopped.
    // Each check: "this data exists → pipeline got past the preceding stage → failed HERE."
    const c = counts(state);
    if (state.final_output_path) return 4; // audio + renders + film path → died in assembly
    if (c.voiced) return 4;    // audio done, no final_output → assembly fault
    if (c.rendered) return 3;  // renders done, no audio → voice fault
    if (c.coded) return 2;     // code written, nothing rendered → validation fault
    if (state.script) return 1; // screenplay exists, nothing coded → code-gen fault
    return 0;                  // no script at all → script-writer fault
  }
  function pipelineFraction(state) {
    if (state.status === "completed") return 1;
    const c = counts(state), idx = curStageIdx(state.status);
    if (state.status === "starting" || state.status === "pending") return 0.04;
    if (state.status === "script_generation") return 0.12;
    if (state.status === "code_generation") {
      const inner = c.scenes ? (c.coded * 0.4 + c.rendered * 0.6) / c.scenes : 0.4;
      return 0.18 + Math.min(1, inner) * 0.44;
    }
    if (state.status === "validation") return 0.62 + (c.scenes ? Math.min(1, c.rendered / c.scenes) : 0.5) * 0.06;
    if (state.status === "voiceover" || state.status === "voiceover_and_images")
      return 0.70 + (c.scenes ? Math.min(1, c.voiced / c.scenes) : 0.4) * 0.18;
    if (state.status === "assembly") return 0.90;
    return 0.5;
  }
  function sceneState(sid, state) {
    const has = (o) => o && (sid in o);
    if (has(state.render_paths)) return "rendered";
    if (has(state.error_logs)) return state.status === "failed" ? "error" : "retry";
    if (has(state.code_paths)) return "coding";
    return "queued";
  }
  const SCENE_LABEL = { queued: "queued", coding: "developing", retry: "healing", rendered: "developed", error: "fault" };

  /* ── api ── */
  async function api(path, opts) {
    const res = await fetch(path, opts);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return res.json();
  }

  /* ════════ shared chrome ════════ */
  function marquee() {
    const dots = SERVICES.map((name) => {
      const h = health?.[name];
      const cls = !h ? "down" : h.status === "ok" ? "" : h.status === "degraded" ? "amber" : "down";
      const info = h ? (h.status === "ok" ? `${h.latency_ms}ms` : h.status) : "unreachable";
      return `<i class="${cls}" data-name="${name}" data-info="${info}"></i>`;
    }).join("");
    const tab = (v, label) => `<button class="${view === v ? "on" : ""}" data-v="${v}">${label}</button>`;
    return `<div class="marquee">
      <div class="logo"><a href="index.html"><img class="logo-mark" src="assets/kinetic-mark.png" alt=""/><span class="m">Kinetic <i>Studios</i></span><span class="sub">idea → film</span></a></div>
      <div class="switch">${tab("home", "Home")}${tab("library", "Library")}${tab("cut", "The cut")}${tab("lab", "The lab")}</div>
      <div class="right">
        <div class="pool" id="pool"><span class="t">render pool</span>${dots}</div>
        <span class="clock" id="clock">${fmtClock(new Date())}</span>
        <button class="sheet-btn" id="open-sheet">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>
          Films · <span id="film-count">${jobs.length}</span>
        </button>
      </div>
    </div>`;
  }

  function renderModeToggle() {
    const btns = RENDER_MODES.map(([v, label]) =>
      `<button class="rm-opt ${renderMode === v ? "on" : ""}" data-rm="${v}">${label}</button>`
    ).join("");
    return `<div class="rm-toggle" id="rm-toggle" title="Render engine for the next film">${btns}</div>`;
  }
  function slate() {
    return `<div class="slate">
      <span class="clap">Roll camera —</span>
      <input id="slate-input" maxlength="300" placeholder="Describe an idea to film… e.g. how a hash map handles collisions"/>
      ${renderModeToggle()}
      <button class="go" id="slate-go">Make it <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#0a0b0e" stroke-width="2.4"><path d="M5 12h14M13 6l6 6-6 6"/></svg></button>
    </div>`;
  }

  function drawerItems() {
    if (!jobs.length) return `<p class="cs-empty">No films yet.<br/>The swarm awaits its first command.</p>`;
    return jobs.map((f) => {
      const kind = f.status === "completed" ? "ready" : (f.status === "failed" || f.status === "cancelled") ? "fail" : "render";
      const badge = f.status === "completed" ? "Ready" : f.status === "failed" ? "Failed" : f.status === "cancelled" ? "Stopped" : "Rendering";
      const meta = `${chipText(f.status)} · ${timeAgo(parseUtc(f.created_at))}`;
      const stoppable = f.status === "failed" || f.status === "cancelled";
      const retry = stoppable
        ? `<button class="cs-retry" data-retry="${f.job_id}" title="Resume this job">↻ ${f.status === "cancelled" ? "Continue" : "Retry"}</button>` : "";
      return `<div class="cs ${f.job_id === selectedId ? "on" : ""}" data-id="${f.job_id}">
        <div class="ti">${esc(f.topic)}</div>
        <div class="ti-meta">${esc(meta)}</div>
        <span class="bd bd-${kind}">${badge}</span>${retry}
      </div>`;
    }).join("");
  }
  function drawer() {
    return `<div class="scrim" id="scrim"></div>
    <div class="drawer" id="drawer">
      <div class="dh"><h3>Your films</h3><button class="x" id="close-sheet">×</button></div>
      <div class="cs-grid" id="cs-grid">${drawerItems()}</div>
    </div>`;
  }

  function clipModal() {
    return `<div class="clip-scrim" id="clip-scrim">
      <div class="clip">
        <div class="ch"><span id="clip-title">Scene</span><button class="x" id="clip-x" aria-label="Close">×</button></div>
        <video id="clip-video" controls playsinline></video>
      </div>
    </div>`;
  }

  function setupOverlay() {
    return `<div class="setup-scrim" id="setup-scrim">
      <div class="setup" role="dialog" aria-modal="true" aria-label="Set up the shot">
        <div class="clap-row"><span class="slate-icon"></span><span class="eye">Set up the shot</span></div>
        <h2>Before we roll</h2>
        <p class="said">Filming: <b id="setup-prompt">${esc(setupPrompt || "your idea")}</b></p>

        <div class="setup-load" id="setup-load">
          <p>Reading your idea… the analyzer can take up to a minute.</p>
          <div class="sk l w60"></div><div class="sk l w85"></div>
          <div class="sk c"></div><div class="sk c"></div>
        </div>

        <div class="setup-err" id="setup-err" hidden>
          <p id="setup-err-msg">The analyzer didn't answer.</p>
          <div class="row">
            <button class="skip" id="setup-retry">Try again</button>
            <button class="roll" id="setup-direct">Film anyway
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#0a0b0e" stroke-width="2.4"><path d="M5 12h14M13 6l6 6-6 6"/></svg></button>
          </div>
        </div>

        <div id="setup-qs" hidden></div>

        <div class="setup-foot" id="setup-foot" hidden>
          <button class="skip" id="setup-skip">Use sensible defaults</button>
          <button class="roll" id="setup-roll">Roll camera
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#0a0b0e" stroke-width="2.4"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
          </button>
        </div>
      </div>
    </div>`;
  }

  const overlaysNoSlate = () => `${drawer()}${setupOverlay()}${clipModal()}`;
  const overlays = () => `${slate()}${overlaysNoSlate()}`;

  /* ════════ HOME ════════ */
  function homeShell() {
    const hour = new Date().getHours();
    const part = hour < 12 ? "morning" : hour < 18 ? "afternoon" : "evening";
    return `${marquee()}
    <div class="home">
      <img class="home-mark" src="assets/kinetic-mark.png" alt="Kinetic Studios"/>
      <div class="reel-eye"><span class="dot"></span>Kinetic Studios · idea → film</div>
      <h1>What should we <em>film</em>, ${esc(NAME)}?</h1>
      <p class="greet-sub">Good ${part}. Describe any idea and we'll shoot the explainer.</p>
      <div class="hero-compose">
        <svg class="plus" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>
        <input id="home-input" maxlength="300" placeholder="A concept to explain — e.g. how a hash map handles collisions"/>
        <select class="model" id="home-mode" title="Render engine for the next film">
          ${RENDER_MODES.map(([v, l]) => `<option value="${v}" ${renderMode === v ? "selected" : ""}>${l}</option>`).join("")}
        </select>
        <button class="roll" id="home-roll" aria-label="Set up the shot"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#0a0b0e" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg></button>
      </div>
      <div class="starters">
        ${STARTERS.map((s, i) => `<button class="starter" data-q="${esc(s)}" style="--i:${i}">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M10 8l6 4-6 4z" fill="currentColor" stroke="none"/></svg>${esc(s)}</button>`).join("")}
      </div>
      <div class="home-foot">8 scenes · 1080p · narrated · captions baked in</div>
    </div>${overlaysNoSlate()}`;
  }

  /* ════════ LIBRARY (history of every film) ════════ */
  function libFiltered() {
    const q = libQuery.trim().toLowerCase();
    return jobs.filter((j) => {
      if (libFilter === "completed" && j.status !== "completed") return false;
      if (libFilter === "failed" && j.status !== "failed") return false;
      if (libFilter === "running" && !RUNNING.has(j.status)) return false;
      if (q && !String(j.topic || "").toLowerCase().includes(q)) return false;
      return true;
    });
  }
  function libCards() {
    const list = libFiltered().slice().sort((a, b) => {
      const rank = (s) => s === "failed" || s === "cancelled" ? 2 : s === "completed" ? 0 : 1;
      return rank(a.status) - rank(b.status);
    });
    if (!list.length) {
      return `<p class="lib-empty">No films ${libQuery ? "match that search" : "here yet"}.<br/>Describe an idea to shoot one.</p>`;
    }
    return list.map((f) => {
      const done = f.status === "completed", failed = f.status === "failed" || f.status === "cancelled";
      const kind = done ? "ready" : failed ? "fail" : "render";
      const badge = done ? "Ready" : f.status === "failed" ? "Failed" : f.status === "cancelled" ? "Stopped" : chipText(f.status);
      const when = timeAgo(parseUtc(f.created_at));
      // Thumbnail = the finished film's own first frame (no separate poster
      // endpoint). preload=metadata fetches only headers + the seek frame.
      const thumb = done
        ? `<video class="lib-thumb" src="/video/${f.job_id}#t=1" preload="metadata" muted playsinline></video>`
        : `<div class="lib-thumb ph ${kind}">${failed ? "⚠" : ""}</div>`;
      return `<article class="lib-card ${kind}" data-id="${f.job_id}" tabindex="0" title="${esc(f.topic)}">
        <div class="lib-pic">${thumb}<span class="lib-badge ${kind}">${esc(badge)}</span></div>
        <div class="lib-body">
          <div class="lib-ti">${esc(f.topic || "Untitled")}</div>
          <div class="lib-meta"><span class="lib-chan">Kinetic Studios</span> · ${esc(when)}</div>
        </div>
      </article>`;
    }).join("");
  }
  function libraryShell() {
    return `${marquee()}
    <div class="library">
      <div class="lib-head">
        <div class="lib-title">
          <h1>Your films</h1>
          <p class="lib-sub">Every explainer the swarm has shot · <span>${jobs.length}</span> total</p>
        </div>
        <button class="lib-new" id="lib-new"><svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="#0a0b0e" stroke-width="2.4" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>Create film</button>
      </div>
      <div class="lib-bar">
        <div class="lib-filters" id="lib-filters">
          ${LIB_FILTERS.map(([f, l]) => `<button class="lib-f ${libFilter === f ? "on" : ""}" data-f="${f}">${l}</button>`).join("")}
        </div>
        <div class="lib-searchwrap">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4-4"/></svg>
          <input class="lib-search" id="lib-search" placeholder="Search your films…" value="${esc(libQuery)}"/>
        </div>
      </div>
      <div class="lib-grid" id="lib-grid">${libCards()}</div>
    </div>${overlaysNoSlate()}`;
  }
  function bindLibCards() {
    document.getElementById("lib-grid")?.querySelectorAll(".lib-card[data-id]").forEach((el) => {
      el.onclick = () => selectJob(el.dataset.id);
      el.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); selectJob(el.dataset.id); } };
    });
  }

  /* ════════ THE CUT (completed) ════════ */
  function cutShell() {
    if (!jobState || jobState.status !== "completed") {
      return `${marquee()}<div class="canvas"><div class="empty-stage">
        <h2>No finished film selected</h2>
        <p>Pick a completed film from <b>Films</b>, or describe a new idea below to shoot one.</p>
      </div></div>${overlays()}`;
    }
    const st = jobState, c = counts(st);
    const runtime = st.script?.scenes?.reduce((a, s) => a + (s.estimated_duration_seconds || 0), 0) || 0;
    const cap = st.script?.title || st.topic || "";
    const scenes = st.script?.scenes || [];
    const titles = scenes.map((s) => s.title).filter(Boolean);
    const chapters = titles.join("  →  ");
    const descText = `A ${fmtDur(runtime)} explainer on ${st.topic || cap}, told across ${c.scenes} scene${c.scenes === 1 ? "" : "s"}.` +
      (chapters ? `\n\nChapters:  ${chapters}` : "") +
      `\n\nFully narrated end to end, captions baked in, rendered at 1080p.` +
      (c.retries ? ` ${c.retries} render hiccup${c.retries > 1 ? "s were" : " was"} caught and auto-healed during production.` : "");
    return `${marquee()}
    <div class="canvas">
      <div class="proj">
        <div class="proj-head">
          <div>
            <div class="meta-eyebrow"><span class="live"></span>Ready to watch · final cut</div>
            <h1>${esc(st.topic || "Untitled")}</h1>
          </div>
        </div>
        <div class="screen" id="screen">${filmPlayerHtml(`/video/${selectedId}`)}</div>
      </div>

      <div class="ytinfo">
        <div class="yt-desc" id="yt-desc">
          <div class="yt-stats">${c.scenes} scenes · ≈ ${fmtDur(runtime)} · 1080p MP4 · captions baked in · Kokoro voice · ${c.retries} retries auto-healed</div>
          <div class="yt-body">${esc(descText)}</div>
          <button class="yt-more" id="yt-more">…more</button>
        </div>
        <div class="yt-bar">
          <div class="yt-left">
            <div class="yt-chan">
              <img class="yt-ava" src="assets/kinetic-mark.png" alt=""/>
              <div><div class="yt-name">Kinetic Studios</div>
                <div class="yt-sub">AI film · ${c.scenes} scenes · ≈ ${fmtDur(runtime)}</div></div>
            </div>
            <div class="canister">
              <a class="dl" id="film-dl" href="/video/${selectedId}" download><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#0a0b0e" stroke-width="2.2"><path d="M12 3v12m0 0l-4-4m4 4l4-4M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2"/></svg>Download film</a>
              <div class="fmt"><b>1080p</b> MP4 · <b>captions</b> baked in · <b>Kokoro</b> voice</div>
            </div>
          </div>
          <div class="yt-acts">
            <button class="yt-btn" id="film-copy"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 12v7a2 2 0 002 2h12a2 2 0 002-2v-7M16 6l-4-4-4 4M12 2v14"/></svg><span class="lbl">Copy link</span></button>
            <button class="yt-btn" id="film-new"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg><span class="lbl">New cut</span></button>
          </div>
        </div>
      </div>

      <div class="strip-wrap">
        <div class="strip-label">The reel <span class="ct">· ${c.rendered} / ${c.scenes} frames developed</span></div>
        <div class="filmstrip">
          ${sprockets(44)}
          <div class="frames">${scenes.map((s, i) => frameHtml(s, st, i)).join("")}</div>
        </div>
      </div>

      <div class="log">
        <div class="h"><span class="l"></span><span class="t">On set</span></div>
        <div class="body" id="log-body">${synthCutLog(st)}</div>
      </div>
    </div>${overlays()}`;
  }

  const sprockets = (n) => `<div class="perf top">${"<b></b>".repeat(n)}</div><div class="perf bottom">${"<b></b>".repeat(n)}</div>`;

  /* video.js v10 default skin (web components, self-initializing via video-ui.js) */
  function filmPlayerHtml(src) {
    return `<video-player class="screenvid">
      <media-container class="media-default-skin media-default-skin--video">
        <video src="${src}" playsinline></video>

        <media-buffering-indicator class="media-buffering-indicator">
          <div class="media-surface"><media-icon name="spinner" class="media-icon"></media-icon></div>
        </media-buffering-indicator>

        <media-error-dialog class="media-error">
          <div class="media-error__dialog media-surface">
            <div class="media-error__content">
              <media-alert-dialog-title class="media-error__title">Couldn't play this film.</media-alert-dialog-title>
              <media-alert-dialog-description class="media-error__description"></media-alert-dialog-description>
            </div>
            <div class="media-error__actions">
              <media-alert-dialog-close class="media-button media-button--primary">OK</media-alert-dialog-close>
            </div>
          </div>
        </media-error-dialog>

        <media-controls class="media-surface media-controls">
          <media-tooltip-group>
            <div class="media-button-group">
              <media-play-button commandfor="play-tooltip" class="media-button media-button--subtle media-button--icon media-button--play">
                <media-icon name="restart" class="media-icon media-icon--restart"></media-icon>
                <media-icon name="play" class="media-icon media-icon--play"></media-icon>
                <media-icon name="pause" class="media-icon media-icon--pause"></media-icon>
              </media-play-button>
              <media-tooltip id="play-tooltip" side="top" class="media-surface media-tooltip"></media-tooltip>

              <media-seek-button commandfor="seek-backward-tooltip" seconds="-10" class="media-button media-button--subtle media-button--icon media-button--seek">
                <span class="media-icon__container"><media-icon name="seek" class="media-icon media-icon--flipped"></media-icon><span class="media-icon__label">10</span></span>
              </media-seek-button>
              <media-tooltip id="seek-backward-tooltip" side="top" class="media-surface media-tooltip"></media-tooltip>

              <media-seek-button commandfor="seek-forward-tooltip" seconds="10" class="media-button media-button--subtle media-button--icon media-button--seek">
                <span class="media-icon__container"><media-icon name="seek" class="media-icon"></media-icon><span class="media-icon__label">10</span></span>
              </media-seek-button>
              <media-tooltip id="seek-forward-tooltip" side="top" class="media-surface media-tooltip"></media-tooltip>
            </div>

            <div class="media-time-controls">
              <media-time type="current" class="media-time"></media-time>
              <media-time-slider class="media-slider">
                <media-slider-track class="media-slider__track">
                  <media-slider-fill class="media-slider__fill"></media-slider-fill>
                  <media-slider-buffer class="media-slider__buffer"></media-slider-buffer>
                </media-slider-track>
                <media-slider-thumb class="media-slider__thumb"></media-slider-thumb>
              </media-time-slider>
              <media-time type="duration" class="media-time"></media-time>
            </div>

            <div class="media-button-group">
              <media-playback-rate-menu-trigger commandfor="playback-rate-menu" class="media-button media-button--subtle media-button--icon media-button--playback-rate"></media-playback-rate-menu-trigger>
              <media-playback-rate-menu id="playback-rate-menu" side="top" align="center" class="media-surface media-popover media-menu media-menu--playback-rate">
                <media-playback-rate-options class="media-menu__group">
                  <template>
                    <media-menu-radio-item class="media-menu__item">
                      <span data-part="label"></span>
                      <media-menu-item-indicator force-mount class="media-menu__indicator"><media-icon name="check" class="media-icon"></media-icon></media-menu-item-indicator>
                    </media-menu-radio-item>
                  </template>
                </media-playback-rate-options>
              </media-playback-rate-menu>

              <media-mute-button commandfor="video-volume-popover" class="media-button media-button--subtle media-button--icon media-button--mute">
                <media-icon name="volume-off" class="media-icon media-icon--volume-off"></media-icon>
                <media-icon name="volume-low" class="media-icon media-icon--volume-low"></media-icon>
                <media-icon name="volume-high" class="media-icon media-icon--volume-high"></media-icon>
              </media-mute-button>
              <media-popover id="video-volume-popover" open-on-hover delay="200" close-delay="100" side="top" class="media-surface media-popover media-popover--volume">
                <media-volume-slider class="media-slider" orientation="vertical" thumb-alignment="edge">
                  <media-slider-track class="media-slider__track"><media-slider-fill class="media-slider__fill"></media-slider-fill></media-slider-track>
                  <media-slider-thumb class="media-slider__thumb media-slider__thumb--persistent"></media-slider-thumb>
                </media-volume-slider>
              </media-popover>

              <media-captions-button commandfor="captions-tooltip" class="media-button media-button--subtle media-button--icon media-button--captions">
                <media-icon name="captions-off" class="media-icon media-icon--captions-off"></media-icon>
                <media-icon name="captions-on" class="media-icon media-icon--captions-on"></media-icon>
              </media-captions-button>
              <media-tooltip id="captions-tooltip" side="top" class="media-surface media-tooltip"></media-tooltip>

              <media-pip-button commandfor="pip-tooltip" class="media-button media-button--subtle media-button--icon media-button--pip">
                <media-icon name="pip-enter" class="media-icon media-icon--pip-enter"></media-icon>
                <media-icon name="pip-exit" class="media-icon media-icon--pip-exit"></media-icon>
              </media-pip-button>
              <media-tooltip id="pip-tooltip" side="top" class="media-surface media-tooltip"></media-tooltip>

              <media-fullscreen-button commandfor="fullscreen-tooltip" class="media-button media-button--subtle media-button--icon media-button--fullscreen">
                <media-icon name="fullscreen-enter" class="media-icon media-icon--fullscreen-enter"></media-icon>
                <media-icon name="fullscreen-exit" class="media-icon media-icon--fullscreen-exit"></media-icon>
              </media-fullscreen-button>
              <media-tooltip id="fullscreen-tooltip" side="top" class="media-surface media-tooltip"></media-tooltip>
            </div>
          </media-tooltip-group>
        </media-controls>

        <div class="media-overlay"></div>

        <media-hotkey keys="Space" action="togglePaused"></media-hotkey>
        <media-hotkey keys="k" action="togglePaused"></media-hotkey>
        <media-hotkey keys="m" action="toggleMuted"></media-hotkey>
        <media-hotkey keys="f" action="toggleFullscreen"></media-hotkey>
        <media-hotkey keys="c" action="toggleSubtitles"></media-hotkey>
        <media-hotkey keys="ArrowRight" action="seekStep" value="5"></media-hotkey>
        <media-hotkey keys="ArrowLeft" action="seekStep" value="-5"></media-hotkey>

        <media-gesture type="tap" action="togglePaused" pointer="mouse" region="center"></media-gesture>
        <media-gesture type="tap" action="toggleControls" pointer="touch"></media-gesture>
        <media-gesture type="doubletap" action="seekStep" value="-10" region="left"></media-gesture>
        <media-gesture type="doubletap" action="toggleFullscreen" region="center"></media-gesture>
        <media-gesture type="doubletap" action="seekStep" value="10" region="right"></media-gesture>
      </media-container>
    </video-player>`;
  }

  function frameHtml(s, st, i) {
    const sid = String(s.scene_id);
    const state = sceneState(sid, st);
    const type = (s.content_type || "manim").toLowerCase();
    const anim = type === "manim";
    const title = s.title || `Scene ${sid}`;
    const desc = (s.visual_description || s.narration_text || "").trim();
    return `<div class="frame" data-st="${state}" data-id="${sid}" data-dur="${s.estimated_duration_seconds || 0}" style="--i:${i || 0}" title="Jump to this scene in the film">
      <div class="pic">
        <span class="n">SC ${sid.padStart(2, "0")}</span>
      </div>
      <div class="cap2">
        <div class="ti">${esc(title)}</div>
        ${desc ? `<div class="desc">${esc(desc)}</div>` : ""}
        <div class="fr"><span class="ok">${SCENE_LABEL[state]}</span><span class="du">${s.estimated_duration_seconds ?? "–"}s</span></div>
      </div>
    </div>`;
  }

  function synthCutLog(st) {
    const c = counts(st);
    const rows = [
      ["director", `film ready — <b>enjoy watching</b>`, "good"],
      ["narrator", `voice added across ${c.scenes} scenes`, ""],
      c.retries ? ["renderer", `${c.retries} scene${c.retries > 1 ? "s" : ""} had issues and were <b>auto-fixed</b>`, "bad"] : null,
      ["renderer", `${c.rendered} of ${c.scenes} scenes completed`, ""],
      ["writer", `story: "${esc(st.script?.title || st.topic || "")}"`, ""],
    ].filter(Boolean);
    return rows.map(([who, ms, tone], i) =>
      `<div class="ln ${tone}"><span class="tm">${String(i).padStart(2, "0")}:00</span><span class="who">${who}</span><span class="ms">${ms}</span></div>`
    ).join("");
  }

  /* ════════ THE LAB — fan-out helpers ════════ */
  // a single-track endpoint node (Script / Assemble / Film)
  function capNode(id, ic, nm, sub) {
    return `<div class="cap-node" id="cap-${id}">
      <div class="orb"><svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${ic}</svg></div>
      <div class="nm">${nm}</div><div class="sub">${sub}</div><div class="st" id="cap-${id}-st"></div>
    </div>`;
  }
  // SVG connector rail that fans from a single point to N lanes (or converges back).
  // viewBox stretches to the rail cell (preserveAspectRatio=none) so it tracks the band height.
  // Smooth bezier rails: a single point (the cap) splays to N lanes. Each path
  // also carries a slow traveling dot (the signal). Gradient flows lime→teal on
  // fan-out, teal→amber on converge, matching the img.
  // ys: array of lane-center Y fractions [0..1] of the rail box height. When
  // omitted, fall back to even spacing (used before lanes are measured).
  function railSvg(n, dir, ys) {
    if (!n) return "";
    const Hn = 1000, mid = Hn / 2, paths = [], beads = [];
    const grad = dir === "fan" ? "url(#gFan)" : "url(#gMerge)";
    const dotCol = dir === "fan" ? "var(--teal)" : "var(--amber)";
    for (let i = 0; i < n; i++) {
      const frac = ys && ys[i] != null ? ys[i] : (i + 0.5) / n;
      const y = frac * Hn;
      const d = dir === "fan"
        ? `M2,${mid} C46,${mid} 54,${y} 98,${y}`
        : `M2,${y} C46,${y} 54,${mid} 98,${mid}`;
      paths.push(`<path d="${d}" fill="none" stroke="${grad}" stroke-width="1.8" stroke-linecap="round" class="rail-line" style="--d:${(i * 0.22).toFixed(2)}s" vector-effect="non-scaling-stroke"/>`);
      beads.push(
        `<path d="${d}" fill="none" stroke="${dotCol}" stroke-width="2.5" stroke-linecap="round"` +
        ` stroke-dasharray="5 170" class="rail-packet" vector-effect="non-scaling-stroke"` +
        ` style="animation-delay:${(i * 0.32).toFixed(2)}s;filter:drop-shadow(0 0 5px ${dotCol})"/>`
      );
    }
    return `<svg viewBox="0 0 100 ${Hn}" preserveAspectRatio="none" width="100%" height="100%">
      <defs>
        <linearGradient id="gFan" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="var(--signal)"/><stop offset="1" stop-color="var(--teal)"/></linearGradient>
        <linearGradient id="gMerge" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="var(--teal)"/><stop offset="1" stop-color="var(--amber)"/></linearGradient>
      </defs>${paths.join("")}${beads.join("")}</svg>`;
  }
  // per-scene pip states across [code, validate, voice]
  function lanePips(sid, st, running) {
    const has = (o) => o && (sid in o);
    const map = { code: has(st.code_paths), voice: has(st.audio_paths), validate: has(st.render_paths) };
    const done = LANE_STAGES.map((g) => map[g.key]);
    const hasErr = has(st.error_logs);
    // "retry" = job still running but scene had an error → auto-healing (amber pulse)
    // "fail"  = job stopped AND scene has an error → permanent fault (red)
    const retrying = hasErr && running;
    const permFail = hasErr && !running;
    const firstOpen = done.indexOf(false);
    const states = done.map((d, j) => {
      if (d) return "done";
      if (permFail && j === firstOpen) return "fail";
      if (retrying && j === firstOpen) return "retry";
      if (running && j === firstOpen) return "cur";
      return "wait";
    });
    let word = SCENE_LABEL[sceneState(String(sid), st)] || "queued";
    if (retrying) word = "healing";
    else if (map.code && !map.voice && running && !hasErr) word = "narrating";
    if (map.code && map.voice && map.validate) word = "developed";
    return { states, word, err: permFail, retrying, allDone: done.every(Boolean) };
  }
  // Per-scene stages in true pipeline order: generate code → render/validate → narrate.
  // "validate" key maps to render_paths (a scene is "validated" by a successful render).
  const LANE_STAGES = [
    { key: "code",     label: "CODE",   ic: STAGES[1].ic },
    { key: "validate", label: "RENDER", ic: STAGES[2].ic },
    { key: "voice",    label: "VOICE",  ic: STAGES[3].ic },
  ];
  function pipNode(g) {
    return `<span class="pip ${g.key}">
      <svg viewBox="0 0 24 24" fill="none" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${g.ic}</svg>
    </span>`;
  }
  // Bundle scenes into at most MAX_LANES groups so the diagram stays compact for
  // long videos (a 30-scene job shows 4 group lanes, not 30 rows). Each group
  // owns a contiguous run of scenes; its disc lights only when ALL its scenes
  // finish that stage. ≤4 scenes => one scene per lane (no bundling).
  const MAX_LANES = 4;
  function sceneGroups(scenes) {
    const n = scenes.length;
    const groups = Math.min(MAX_LANES, n);
    const per = Math.ceil(n / groups);
    const out = [];
    for (let g = 0; g < groups; g++) {
      const slice = scenes.slice(g * per, (g + 1) * per);
      if (slice.length) out.push(slice);
    }
    return out;
  }
  // (re)build the scene band + connector rails once the scene count is known.
  // One lane per GROUP: CODE·VOICE·VALIDATE icon discs, label shows the scene span.
  function buildBand(scenes) {
    const band = document.getElementById("scene-band");
    if (!band) return;
    const n = scenes.length;
    if (band.dataset.n !== String(n)) {
      band.dataset.n = String(n);
      const groups = sceneGroups(scenes);
      const header = `<div class="lane-head" aria-hidden="true">
        ${LANE_STAGES.map((g) => `<span class="hcol">${g.label}</span>`).join("")}
      </div>`;
      const lanes = groups.map((slice, i) => {
        const pips = LANE_STAGES.map(pipNode).join("");
        const first = slice[0].scene_id ?? (i + 1);
        const last = slice[slice.length - 1].scene_id ?? (i + slice.length);
        const label = slice.length === 1 ? `SC ${String(first).padStart(2, "0")}`
                                         : `SC ${first}–${last}`;
        return `<div class="lane" id="lane-${i}" style="--i:${i}">
          <span class="sc">${esc(label)}</span>
          <span class="pips">${pips}</span>
        </div>`;
      }).join("");
      band.innerHTML = header + lanes;
      drawRails(groups.length);
    }
  }
  // Draw fan/merge rails so each line lands on the ACTUAL vertical centre of its
  // lane. The rail box and the band have different heights (band has a label +
  // header above the lanes), so even spacing misaligns — measure instead.
  function drawRails(n) {
    const rf = document.getElementById("rail-fan"), rm = document.getElementById("rail-merge");
    const band = document.getElementById("scene-band");
    if (!rf || !rm || !band) return;
    const railBox = rf.getBoundingClientRect();
    let ys = null;
    if (railBox.height > 0) {
      const lanes = [...band.querySelectorAll(".lane")];
      if (lanes.length === n) {
        ys = lanes.map((el) => {
          const r = el.getBoundingClientRect();
          return (r.top + r.height / 2 - railBox.top) / railBox.height;  // fraction of rail height
        });
      }
    }
    rf.innerHTML = railSvg(n, "fan", ys);
    rm.innerHTML = railSvg(n, "merge", ys);
  }

  /* ── error helpers ── */
  function parseErrorSummary(err) {
    if (!err) return "";
    const lines = err.split("\n").map((l) => l.trim()).filter(Boolean);
    for (let i = lines.length - 1; i >= 0; i--) {
      const l = lines[i];
      if (!l.startsWith("File ") && !l.startsWith("During handling") && !l.startsWith("The above") && l.length < 300)
        return l;
    }
    return (lines[0] || err).slice(0, 200);
  }
  function buildErrDetail(st) {
    const c = counts(st);
    const scenes = st.script?.scenes || [];
    const errs = st.error_logs || {};
    const retries = st.retry_counts || {};
    const sceneHtml = Object.entries(errs).map(([sid, errText]) => {
      const sc = scenes.find((s) => String(s.scene_id) === String(sid));
      const name = sc?.title ? `SC ${String(sid).padStart(2, "0")} "${esc(sc.title)}"` : `SC ${String(sid).padStart(2, "0")}`;
      const tries = retries[sid] || 0;
      const summary = parseErrorSummary(errText);
      return `<div class="errbar-scene">
        <span class="es-name">${name}</span>
        <span class="es-attempt">${tries}/5 tries</span>
        ${summary ? `<span class="es-msg" title="${esc(summary)}">${esc(summary)}</span>` : ""}
      </div>`;
    }).join("");
    const notes = [];
    if (c.rendered > 0) notes.push(`keeps ${c.rendered} existing render${c.rendered !== 1 ? "s" : ""}`);
    if (c.coded > 0) notes.push(`reuses ${c.coded} code file${c.coded !== 1 ? "s" : ""}`);
    notes.push(`re-voices all ${c.scenes || "?"} scenes`);
    const note = `<div class="errbar-resume-note">↻ Resume: ${notes.join(" · ")}</div>`;
    return sceneHtml + note;
  }

  /* ════════ THE LAB (running / failed) ════════ */
  function labShell() {
    if (!jobState) {
      return `${marquee()}<div class="canvas"><div class="empty-stage">
        <h2>Nothing developing right now</h2>
        <p>Describe an idea below and watch the swarm shoot it stage by stage.</p>
      </div></div>${overlays()}`;
    }
    const st = jobState;
    const failed = st.status === "failed" || st.status === "cancelled";
    const created = createdMs ? new Date(createdMs).toLocaleString() : "—";
    return `${marquee()}
    <div class="canvas">
      <div class="proj"><div class="proj-head">
        <div>
          <div class="meta-eyebrow ${failed ? "warn" : ""}"><span class="live"></span>${failed ? "Pipeline fault" : "In the lab · developing"}</div>
          <h1>${esc(st.topic || "Untitled")}</h1>
        </div>
        <div class="facts">
          ${RUNNING.has(st.status) ? `<button class="stop-btn" id="stop-btn">■ Stop</button><br>` : ""}
          job <b class="jobid" id="jobid">${esc((st.job_id || "").slice(0, 8))}…</b><br>${esc(created)}<br>six stages, in order
        </div>
      </div></div>

      <div class="devtrack">
        <div class="strip-label" style="padding-left:0">Developing track <span class="ct" id="track-ct">·</span></div>

        <!-- fan-out: Script splits into N parallel scene agents, then converges into Assemble → Film -->
        <div class="fanout" id="fanout">
          <div class="cap-col">
            ${capNode("script", STAGES[0].ic, "Story", "develops the screenplay")}
          </div>
          <div class="rail" id="rail-fan" aria-hidden="true"></div>
          <div class="band-wrap">
            <div class="band-lbl"><span id="band-ct">Scenes in progress</span>
              <span class="band-sub">each scene developed independently</span></div>
            <div class="band" id="scene-band"><div class="band-hint">waiting for scene breakdown…</div></div>
          </div>
          <div class="rail" id="rail-merge" aria-hidden="true"></div>
          <div class="cap-col converge">
            ${capNode("assemble", STAGES[4].ic, "Finish", "puts it all together")}
            ${capNode("film", STAGES[5].ic, "Done", "your film is ready")}
          </div>
        </div>

        <div class="dev-readout">
          <div class="cell"><div class="k">Time remaining</div><div class="v lime" id="ro-eta">—</div></div>
          <div class="cell"><div class="k">Elapsed</div><div class="v" id="ro-elapsed">0:00</div></div>
          <div class="cell"><div class="k">Scenes</div><div class="v" id="ro-scenes">0<small>/0</small></div></div>
          <div class="cell"><div class="k">Auto-healed</div><div class="v" id="ro-retries">0<small> retries</small></div></div>
        </div>
      </div>

      <div class="errbar" id="errbar" ${failed && st.overall_error ? "" : "hidden"}>
        <div class="errbar-head">
          <div><b id="errbar-label">${st.status === "cancelled" ? "Stopped by user" : "Pipeline fault"}</b><span class="errbar-sum" id="errbar-sum">${esc(parseErrorSummary(st.overall_error || ""))}</span></div>
          <button class="retry-btn" id="retry-btn">↻ ${st.status === "cancelled" ? "Continue" : "Resume pipeline"}</button>
        </div>
        <div class="errbar-body" id="errbar-detail"></div>
        <details class="errbar-raw"><summary>full trace</summary><pre id="err-text">${esc(st.overall_error || "")}</pre></details>
      </div>

      <div class="log">
        <div class="h"><span class="l"></span><span class="t">Render log</span></div>
        <div class="body" id="log-body"></div>
      </div>
    </div>${overlays()}`;
  }

  function patchLab() {
    if (!jobState) return;
    const st = jobState, c = counts(st);
    const failed = st.status === "failed" || st.status === "cancelled";
    const cur = failed ? failStageIdx(st) : curStageIdx(st.status);

    // ── fan-out: endpoint caps + parallel scene band ──
    const running = RUNNING.has(st.status);
    const scenes = st.script?.scenes || [];
    const setCap = (id, state, word) => {
      const el = document.getElementById(`cap-${id}`);
      if (el) el.className = "cap-node" + (state ? " " + state : "");
      setText(`cap-${id}-st`, word);
    };
    // Script: done once the screenplay exists, else summoning
    setCap("script", st.script ? "done" : "cur", st.script ? `${scenes.length} scenes` : "writing");
    // Assemble: barrier — runs at assembly, done when completed, faults if failed there
    const asmState = st.status === "completed" ? "done"
      : st.status === "assembly" ? "cur"
      : (failed && cur >= 4) ? "fail" : "wait";
    setCap("assemble", asmState, st.status === "assembly" ? "stitching" : asmState === "done" ? "stitched" : asmState === "fail" ? "fault" : "waiting");
    setCap("film", st.status === "completed" ? "done" : "wait", st.status === "completed" ? "ready" : "—");

    // build group lanes once scenes are known, then patch each group's discs:
    // a stage is "done" only when EVERY scene in the group finished it.
    if (scenes.length) {
      buildBand(scenes);
      const groups = sceneGroups(scenes);
      drawRails(groups.length);  // re-measure: lanes are laid out now, align lines to them
      let validated = 0;  // count of fully-developed scenes (all 3 stages)
      groups.forEach((slice, i) => {
        const lane = document.getElementById(`lane-${i}`);
        if (!lane) return;
        const members = slice.map((sc, k) => lanePips(String(sc.scene_id ?? k + 1), st, running));
        validated += members.filter((m) => m.allDone).length;
        // Aggregate each stage across the group: all done -> done; any fail -> fail;
        // any in-progress -> cur; else wait.
        LANE_STAGES.forEach((g, j) => {
          const states = members.map((m) => m.states[j]);
          const agg = states.every((s) => s === "done") ? "done"
            : states.includes("fail") ? "fail"
            : states.includes("retry") ? "retry"
            : states.includes("cur") ? "cur" : "wait";
          const pip = lane.querySelector(`.pip.${g.key}`);
          if (pip) pip.className = `pip ${g.key} ${agg}`;
        });
        const allDone = members.every((m) => m.allDone);
        const anyPermFail = members.some((m) => m.err);       // permanent fail only
        const anyRetrying = members.some((m) => m.retrying);  // auto-healing
        lane.className = "lane" + (allDone ? " done" : anyPermFail ? " fail" : (anyRetrying || running) ? " live" : "");
      });
      const bs = document.querySelector(".band-sub");
      const lbl = `${validated}/${scenes.length} scenes ready`;
      if (bs) bs.textContent = lbl;
    }
    const tct = document.getElementById("track-ct");
    if (tct) tct.textContent = failed ? `· stopped at ${STAGES[cur].nm.toLowerCase()}` : st.status === "completed" ? "· complete" : `· stage ${Math.min(cur + 1, 6)} of 6`;

    // readout
    const now = Date.now(), end = completedMs || now;
    const elapsed = createdMs ? (end - createdMs) / 1000 : null;
    setText("ro-elapsed", fmtDur(elapsed));
    setText("ro-retries", "", `${c.retries}<small> retries</small>`);
    setText("ro-scenes", "", `${c.rendered}<small>/${c.scenes}</small>`);

    // eta
    let etaText;
    if (st.status === "completed") etaText = "done";
    else if (failed) etaText = "—";
    else {
      const f = pipelineFraction(st);
      if (!elapsed || elapsed < 8 || f < 0.05) etaText = "estimating…";
      else { const raw = elapsed * (1 - f) / f; etaSmooth = etaSmooth == null ? raw : etaSmooth * 0.75 + raw * 0.25; etaText = `~${fmtDur(Math.min(etaSmooth, 99 * 60))}`; }
    }
    setText("ro-eta", etaText);

    // error
    const eb = document.getElementById("errbar");
    if (eb) {
      const show = failed && st.overall_error;
      eb.hidden = !show;
      if (show) {
        setText("err-text", st.overall_error);
        setText("errbar-sum", parseErrorSummary(st.overall_error));
        const det = document.getElementById("errbar-detail");
        if (det) det.innerHTML = buildErrDetail(st);
        const rb = document.getElementById("retry-btn");
        if (rb && !rb.disabled) rb.textContent = `↻ ${st.status === "cancelled" ? "Continue" : "Resume pipeline"}`;
      }
    }

    // log
    diffToFeed(prevState, st);
    renderFeed();
    prevState = st;
  }

  /* ── live feed (lab) ── */
  function pushFeed(who, ms, tone) {
    feedLines.unshift({ t: fmtClock(new Date()), who, ms, tone: tone || "" });
    while (feedLines.length > 60) feedLines.pop();
  }
  function renderFeed() {
    const body = document.getElementById("log-body");
    if (!body) return;
    if (!feedLines.length) { body.innerHTML = `<div class="empty">listening for agent chatter…</div>`; return; }
    body.innerHTML = feedLines.map((l) =>
      `<div class="ln ${l.tone}"><span class="tm">${l.t}</span><span class="who">${esc(l.who)}</span><span class="ms">${l.ms}</span></div>`
    ).join("");
  }
  function diffToFeed(prev, cur) {
    const name = (sid) => { const sc = cur.script?.scenes?.find((s) => String(s.scene_id) === String(sid)); return sc?.title ? `scene ${sid} "${esc(sc.title)}"` : `scene ${sid}`; };
    if (!prev) { pushFeed("director", `tracking transmission · ${chipText(cur.status)}`); return; }
    if (prev.status !== cur.status) {
      const tone = cur.status === "failed" ? "bad" : cur.status === "completed" ? "good" : "";
      pushFeed("director", `phase → <b>${chipText(cur.status)}</b>`, tone);
    }
    if (!prev.script && cur.script)
      pushFeed("script-writer", `screenplay ready — ${cur.script.scenes?.length ?? 0} scenes: "${esc(cur.script.title || "")}"`, "good");
    const fresh = (a, b) => Object.keys(b || {}).filter((k) => !(k in (a || {})));
    for (const k of fresh(prev.code_paths, cur.code_paths)) pushFeed("creator", `${name(k)} — scene created`);
    for (const k of fresh(prev.render_paths, cur.render_paths)) pushFeed("renderer", `${name(k)} — <b>rendered ✓</b>`, "good");
    for (const k of fresh(prev.audio_paths, cur.audio_paths)) pushFeed("narrator", `${name(k)} — voice recorded`);
    for (const k of fresh(prev.image_paths, cur.image_paths)) pushFeed("camera", `${name(k)} — images ready`);
    for (const [k, v] of Object.entries(cur.retry_counts || {})) { const was = (prev.retry_counts || {})[k] || 0; if (v > was) pushFeed("renderer", `${name(k)} — retrying (attempt ${v})`, "bad"); }
    for (const k of fresh(prev.error_logs, cur.error_logs)) pushFeed("renderer", `${name(k)} — issue found, retrying`, "bad");
    if (!prev.final_output_path && cur.final_output_path) pushFeed("editor", "film ready ✓", "good");
    if (cur.status === "failed" && prev.status !== "failed") pushFeed("director", esc(cur.overall_error || "something went wrong"), "bad");
  }

  function setText(id, text, html) {
    const el = document.getElementById(id);
    if (!el) return;
    if (html != null) el.innerHTML = html; else el.textContent = text;
  }

  /* ════════ mount + route ════════ */
  function keyFor() {
    if (view === "home") return "home";
    if (view === "library") return "library";   // stable: poll refreshes the grid in-place
    return `${view}:${selectedId || ""}`;
  }

  function ensureMounted() {
    const k = keyFor();
    if (k === mountKey) return false;
    mountKey = k;
    root.innerHTML = view === "home" ? homeShell()
      : view === "library" ? libraryShell()
      : view === "cut" ? cutShell() : labShell();
    wire();
    if (view === "lab") { renderFeed(); patchLab(); }
    return true;
  }

  /* ── patch home chrome (no remount) ── */
  function patchChrome() {
    setText("film-count", String(jobs.length));
    const hSig = SERVICES.map((s) => (health?.[s]?.status || "down")).join(",");
    if (hSig !== lastHealthSig) {
      lastHealthSig = hSig;
      const pool = document.getElementById("pool");
      if (pool) {
        [...pool.querySelectorAll("i")].forEach((d) => d.remove());
        SERVICES.forEach((name) => {
          const h = health?.[name];
          const i = document.createElement("i");
          i.className = !h ? "down" : h.status === "ok" ? "" : h.status === "degraded" ? "amber" : "down";
          i.dataset.name = name; i.dataset.info = h ? (h.status === "ok" ? `${h.latency_ms}ms` : h.status) : "unreachable";
          pool.appendChild(i);
        });
      }
    }
    const sig = jobs.map((j) => j.job_id + j.status).join("|");
    if (sig !== lastJobsSig) {
      lastJobsSig = sig;
      const grid = document.getElementById("cs-grid");
      if (grid) { grid.innerHTML = drawerItems(); wireDrawerItems(); }
      const lib = document.getElementById("lib-grid");
      if (lib) { lib.innerHTML = libCards(); bindLibCards(); }
    }
  }

  /* ════════ wiring ════════ */
  function wire() {
    root.querySelectorAll(".switch button").forEach((b) => b.onclick = () => gotoTab(b.dataset.v));

    // drawer
    const dr = document.getElementById("drawer"), sc = document.getElementById("scrim");
    const open = () => { dr && dr.classList.add("show"); sc && sc.classList.add("show"); };
    const close = () => { dr && dr.classList.remove("show"); sc && sc.classList.remove("show"); };
    const ob = document.getElementById("open-sheet"); if (ob) ob.onclick = open;
    const cb = document.getElementById("close-sheet"); if (cb) cb.onclick = close;
    if (sc) sc.onclick = close;
    wireDrawerItems();

    // library/history grid: search, status filters, card clicks, create button
    bindLibCards();
    const ls = document.getElementById("lib-search");
    if (ls) ls.oninput = () => {
      libQuery = ls.value;
      const g = document.getElementById("lib-grid");
      if (g) { g.innerHTML = libCards(); bindLibCards(); }
    };
    document.getElementById("lib-filters")?.querySelectorAll(".lib-f").forEach((b) => b.onclick = () => {
      libFilter = b.dataset.f;
      b.parentElement.querySelectorAll(".lib-f").forEach((x) => x.classList.toggle("on", x === b));
      const g = document.getElementById("lib-grid");
      if (g) { g.innerHTML = libCards(); bindLibCards(); }
    });
    const ln = document.getElementById("lib-new");
    if (ln) ln.onclick = () => openSetup("");

    // compose entry points
    const hi = document.getElementById("home-input");
    const hm = document.getElementById("home-mode");
    if (hm) hm.onchange = () => { renderMode = hm.value; };
    const hr = document.getElementById("home-roll");
    if (hr) hr.onclick = () => openSetup(hi ? hi.value : "");
    if (hi) hi.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); openSetup(hi.value); } };
    root.querySelectorAll(".starter").forEach((s) => s.onclick = () => { if (hi) hi.value = s.dataset.q; openSetup(s.dataset.q); });

    const si = document.getElementById("slate-input"), sg = document.getElementById("slate-go");
    if (sg) sg.onclick = () => openSetup(si ? si.value : "");
    if (si) si.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); openSetup(si.value); } };
    // render-engine toggle: set the mode for the next job, restyle the segments
    root.querySelectorAll("#rm-toggle .rm-opt").forEach((b) => b.onclick = () => {
      renderMode = b.dataset.rm;
      b.parentElement.querySelectorAll(".rm-opt").forEach((x) => x.classList.toggle("on", x === b));
    });

    // youtube-style info actions
    const fc = document.getElementById("film-copy");
    if (fc) fc.onclick = async () => {
      const lbl = fc.querySelector(".lbl");
      try {
        await navigator.clipboard.writeText(`${location.origin}/video/${selectedId}`);
        fc.classList.add("done"); if (lbl) lbl.textContent = "Copied";
        setTimeout(() => { fc.classList.remove("done"); if (lbl) lbl.textContent = "Copy link"; }, 1500);
      } catch (e) {}
    };
    const fn = document.getElementById("film-new");
    if (fn) fn.onclick = () => openSetup(jobState?.topic || "");
    const ym = document.getElementById("yt-more");
    if (ym) ym.onclick = () => {
      const open = document.getElementById("yt-desc").classList.toggle("open");
      ym.textContent = open ? "show less" : "…more";
    };

    // film player (cut) — video.js <video-player> default skin handles its own controls
    // scene cards link to the real timeline: click seeks the main film to the
    // scene's cumulative start (sum of prior scene durations), no separate player.
    root.querySelectorAll(".frames .frame").forEach((f) => f.onclick = () => {
      const vid = document.querySelector("#screen video");
      if (!vid) return;
      let start = 0, p = f.previousElementSibling;
      while (p) { if (p.classList.contains("frame")) start += parseFloat(p.dataset.dur) || 0; p = p.previousElementSibling; }
      document.getElementById("screen")?.scrollIntoView({ behavior: "smooth", block: "center" });
      try { vid.currentTime = start; vid.play().catch(() => {}); } catch (e) {}
    });

    // copy job id (lab)
    const jid = document.getElementById("jobid");
    if (jid && jobState) jid.onclick = async () => {
      try { await navigator.clipboard.writeText(jobState.job_id || ""); const old = jid.textContent; jid.textContent = "copied ✓"; setTimeout(() => jid.textContent = old, 1200); } catch {}
    };

    // clip modal
    const cs = document.getElementById("clip-scrim"), cx = document.getElementById("clip-x");
    if (cs) cs.onclick = (e) => { if (e.target === cs) closeClip(); };
    if (cx) cx.onclick = closeClip;

    // retry/resume a failed job from the lab error bar
    const rb = document.getElementById("retry-btn");
    if (rb) rb.onclick = () => resumeJob(selectedId, rb);
    const sb = document.getElementById("stop-btn");
    if (sb) sb.onclick = () => cancelJob(selectedId, sb);

    wireSetup();
  }

  function wireDrawerItems() {
    root.querySelectorAll(".cs[data-id]").forEach((el) => el.onclick = () => {
      document.getElementById("drawer")?.classList.remove("show");
      document.getElementById("scrim")?.classList.remove("show");
      selectJob(el.dataset.id);
    });
    // retry buttons on failed cards — stop the click bubbling to selectJob
    root.querySelectorAll(".cs-retry[data-retry]").forEach((b) => b.onclick = (e) => {
      e.stopPropagation();
      document.getElementById("drawer")?.classList.remove("show");
      document.getElementById("scrim")?.classList.remove("show");
      resumeJob(b.dataset.retry, b);
    });
  }

  /* ── clip modal ── */
  function openClip(title, src) {
    const cs = document.getElementById("clip-scrim"), v = document.getElementById("clip-video"), t = document.getElementById("clip-title");
    if (!cs || !v) return;
    if (t) t.textContent = title;
    v.src = src; cs.classList.add("show");
  }
  function closeClip() {
    const cs = document.getElementById("clip-scrim"), v = document.getElementById("clip-video");
    if (!cs) return;
    cs.classList.remove("show");
    if (v) { v.pause(); v.removeAttribute("src"); v.load(); }
  }

  /* ════════ navigation ════════ */
  function latestByStatus(pred) { return jobs.find((j) => pred(j.status))?.job_id || null; }

  function gotoTab(v) {
    if (v === "home") { view = "home"; ensureMounted(); return; }
    if (v === "library") { view = "library"; ensureMounted(); return; }
    if (v === "cut") {
      const id = (selectedId && jobState?.status === "completed") ? selectedId : latestByStatus((s) => s === "completed");
      if (id && id !== selectedId) { selectJob(id, "cut"); return; }
      view = "cut"; ensureMounted(); return;
    }
    if (v === "lab") {
      const id = (selectedId && jobState && jobState.status !== "completed") ? selectedId
        : latestByStatus((s) => RUNNING.has(s) || s === "failed");
      if (id && id !== selectedId) { selectJob(id, "lab"); return; }
      view = "lab"; ensureMounted(); return;
    }
  }

  function selectJob(id, forceView) {
    selectedId = id;
    jobState = null; prevState = null; etaSmooth = null;
    createdMs = null; completedMs = null; feedLines = [];
    const meta = jobs.find((j) => j.job_id === id);
    if (forceView) view = forceView;
    else view = meta && meta.status === "completed" ? "cut" : "lab";
    mountKey = null;            // force remount for new job
    pollSelected(true);
  }

  /* ════════ setup / analyze / generate ════════ */
  function openSetup(promptText) {
    setupPrompt = (promptText || "").trim();
    if (!setupPrompt) { const i = document.getElementById("home-input") || document.getElementById("slate-input"); i && i.focus(); return; }
    setupOpen = true;
    const scrim = document.getElementById("setup-scrim");
    if (!scrim) return;
    setText("setup-prompt", setupPrompt);
    show("setup-load"); hide("setup-err"); hide("setup-qs"); hide("setup-foot");
    scrim.classList.add("show");
    runAnalysis();
  }
  function closeSetup() { setupOpen = false; document.getElementById("setup-scrim")?.classList.remove("show"); }

  async function runAnalysis() {
    show("setup-load"); hide("setup-err"); hide("setup-qs"); hide("setup-foot");
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 75000);
    try {
      analyzer = await api("/analyze", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ topic: setupPrompt }), signal: ctrl.signal });
      buildSetupQuestions();
      hide("setup-load"); show("setup-qs"); show("setup-foot");
    } catch (e) {
      hide("setup-load");
      setText("setup-err-msg", e.name === "AbortError" ? "The analyzer timed out." : "The analyzer didn't answer.");
      show("setup-err");
    } finally { clearTimeout(timer); }
  }

  function buildSetupQuestions() {
    const a = analyzer || {};
    const qs = (Array.isArray(a.questions) ? a.questions : []).filter((q) => q.id !== "duration" && q.id !== "style");
    setupAns = {};
    const recM = Math.round((a.recommended_duration_seconds || 300) / 60);
    const maxM = Math.max(1, Math.round((a.max_duration_seconds || 1200) / 60));
    const presets = (a.duration_presets || [90, 180, 360]).map((s) => Math.round(s / 60));

    let html = "";
    if (a.feasibility_summary) html += `<div class="q" style="margin-bottom:18px"><p class="said" style="margin:0">${esc(a.feasibility_summary)} · recommended ${recM} min · max ${maxM} min</p></div>`;

    qs.forEach((q, qi) => {
      setupAns[q.id] = { selected: q.multi_select ? [] : (q.options[0] ? [q.options[0].label] : []), custom: "" };
      html += `<div class="q" data-q="${q.id}" data-multi="${q.multi_select ? 1 : 0}">
        <div class="ql"><span class="qn">${String(qi + 1).padStart(2, "0")}</span><span class="qt">${esc(q.question || "")}</span><span class="qh">${q.multi_select ? "select any" : "pick one"}</span></div>
        <div class="opts">
          ${q.options.map((o) => `<button class="opt ${(!q.multi_select && o.label === q.options[0].label) ? "sel" : ""}" data-q="${q.id}" data-label="${esc(o.label)}"><span>${esc(o.label)}</span>${o.description ? `<span class="sub">${esc(o.description)}</span>` : ""}</button>`).join("")}
          ${q.allows_custom ? `<button class="opt opt-other" data-q="${q.id}" data-other="1"><span>Other…</span><span class="sub">describe it</span></button>` : ""}
        </div>
        ${q.allows_custom ? `<div class="other-wrap" data-q="${q.id}" hidden><input maxlength="200" placeholder="Describe it yourself"/></div>` : ""}
      </div>`;
    });

    // duration step
    setupAns.__minutes = recM;
    html += `<div class="q" data-duration="1">
      <div class="ql"><span class="qn">${String(qs.length + 1).padStart(2, "0")}</span><span class="qt">How long should it run?</span><span class="qh">target length</span></div>
      <div class="opts" id="dur-presets">
        ${presets.map((m) => `<button class="opt ${m === recM ? "sel" : ""}" data-min="${m}"><span>${m} min</span><span class="sub">${m <= 2 ? "quick take" : m <= 4 ? "standard" : "deep dive"}</span></button>`).join("")}
      </div>
      <div class="q-custom">custom <input id="dur-min" type="number" min="1" max="${maxM}" placeholder="${recM}"/> min <span style="color:var(--muted-2)">max ${maxM}</span></div>
    </div>`;

    // visual template picker (default Auto = art_director picks from topic)
    setupAns["style"] = { selected: [], custom: "" };
    html += `<div class="q" data-q="style">
      <div class="ql"><span class="qn">${String(qs.length + 2).padStart(2, "0")}</span><span class="qt">Visual template</span><span class="qh">pick a look</span></div>
      <div class="stylepick">
        <button class="styletile auto sel" data-style="">
          <div class="sp-banner sp-auto"><span class="sp-aa">Aa</span></div>
          <div class="sp-meta"><b>Auto</b><span>we pick to fit the topic</span></div>
        </button>
        ${STYLES.map((s) => `<button class="styletile" data-style="${s.k}">
          <div class="sp-banner" style="background:${s.bg}"><span class="sp-aa" style="color:${s.fg}">Aa</span><span class="sp-dot" style="background:${s.ac}"></span></div>
          <div class="sp-meta"><b>${s.n}</b><span>${s.v}</span></div>
        </button>`).join("")}
      </div>
    </div>`;

    setText("setup-qs", "", html);
    wireSetupQuestions();
  }

  function wireSetupQuestions() {
    const qroot = document.getElementById("setup-qs");
    if (!qroot) return;
    qroot.querySelectorAll(".opt[data-label], .opt[data-other]").forEach((o) => o.onclick = () => {
      const qid = o.dataset.q, block = o.closest(".q"), multi = block.dataset.multi === "1";
      const ans = setupAns[qid] || (setupAns[qid] = { selected: [], custom: "" });
      const other = qroot.querySelector(`.other-wrap[data-q="${qid}"]`);
      if (o.dataset.other) { if (other) { other.hidden = false; const inp = other.querySelector("input"); inp && inp.focus(); } o.classList.add("sel"); return; }
      const label = o.dataset.label;
      if (multi) {
        const i = ans.selected.indexOf(label);
        if (i >= 0) { ans.selected.splice(i, 1); o.classList.remove("sel"); } else { ans.selected.push(label); o.classList.add("sel"); }
      } else {
        block.querySelectorAll(".opt").forEach((x) => x.classList.remove("sel"));
        ans.selected = [label]; o.classList.add("sel");
        if (other) other.hidden = true; ans.custom = "";
      }
    });
    qroot.querySelectorAll(".styletile").forEach((t) => t.onclick = () => {
      qroot.querySelectorAll(".styletile").forEach((x) => x.classList.remove("sel"));
      t.classList.add("sel");
      const k = t.dataset.style;
      setupAns["style"] = { selected: k ? [k] : [], custom: "" };
    });
    qroot.querySelectorAll(".other-wrap input").forEach((inp) => {
      const qid = inp.closest(".other-wrap").dataset.q;
      inp.oninput = () => { (setupAns[qid] = setupAns[qid] || { selected: [], custom: "" }).custom = inp.value.trim(); };
    });
    // duration
    qroot.querySelectorAll("#dur-presets .opt").forEach((p) => p.onclick = () => {
      qroot.querySelectorAll("#dur-presets .opt").forEach((x) => x.classList.remove("sel"));
      p.classList.add("sel"); setupAns.__minutes = parseInt(p.dataset.min, 10);
      const di = document.getElementById("dur-min"); if (di) di.value = "";
    });
    const di = document.getElementById("dur-min");
    if (di) di.oninput = () => {
      const maxM = Math.max(1, Math.round((analyzer?.max_duration_seconds || 1200) / 60));
      let v = parseInt(di.value, 10);
      if (!isNaN(v)) { v = Math.min(maxM, Math.max(1, v)); setupAns.__minutes = v; qroot.querySelectorAll("#dur-presets .opt").forEach((x) => x.classList.remove("sel")); }
    };
  }

  function wireSetup() {
    const scrim = document.getElementById("setup-scrim");
    if (!scrim) return;
    scrim.onclick = (e) => { if (e.target === scrim) closeSetup(); };
    const retry = document.getElementById("setup-retry"); if (retry) retry.onclick = runAnalysis;
    const direct = document.getElementById("setup-direct"); if (direct) direct.onclick = () => startRender(null);
    const skip = document.getElementById("setup-skip"); if (skip) skip.onclick = () => startRender(buildBrief());
    const roll = document.getElementById("setup-roll"); if (roll) roll.onclick = () => startRender(buildBrief());
    document.addEventListener("keydown", escClose);
  }
  function escClose(e) {
    if (e.key !== "Escape") return;
    if (document.getElementById("clip-scrim")?.classList.contains("show")) { closeClip(); return; }
    if (setupOpen) closeSetup();
  }

  function pickAnswer(id) { const a = setupAns[id]; if (!a) return null; if (a.selected.length) return a.selected.join(", "); return a.custom || null; }
  function buildBrief() {
    const a = analyzer || {};
    const answers = Object.entries(setupAns)
      .filter(([k]) => k !== "__minutes")
      .filter(([, v]) => v && (v.selected.length || v.custom))
      .map(([question_id, v]) => ({ question_id, selected: v.selected, custom_text: v.custom || null }));
    const focusAns = setupAns["focus"];
    const focus_areas = focusAns ? focusAns.selected.concat(focusAns.custom ? [focusAns.custom] : []) : [];
    return {
      target_duration_seconds: (setupAns.__minutes || Math.round((a.recommended_duration_seconds || 300) / 60)) * 60,
      max_duration_seconds: a.max_duration_seconds,
      is_study_material: !!a.is_study_material,
      audience_level: pickAnswer("audience"),
      focus_areas,
      visual_style: pickAnswer("style"),
      pacing: pickAnswer("pacing"),
      answers,
    };
  }

  async function startRender(brief) {
    if (setupBusy) return;
    setupBusy = true;
    const roll = document.getElementById("setup-roll"), direct = document.getElementById("setup-direct");
    [roll, direct].forEach((b) => b && (b.disabled = true));
    try {
      const body = brief ? { topic: setupPrompt, brief } : { topic: setupPrompt };
      if (renderMode && renderMode !== "hybrid") body.render_mode = renderMode;
      const res = await api("/generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      closeSetup();
      await pollJobs();
      selectJob(res.job_id, "lab");
    } catch (e) {
      alert(`The swarm did not answer: ${e.message}`);
    } finally {
      setupBusy = false;
      [roll, direct].forEach((b) => b && (b.disabled = false));
    }
  }

  // Resume a failed/stalled job — backend re-runs from saved state, skipping
  // scenes already rendered/voiced. Jumps the view to the lab to watch it finish.
  async function resumeJob(jobId, btn) {
    if (!jobId) return;
    if (btn) { btn.disabled = true; btn.textContent = "↻ Resuming…"; }
    try {
      await api(`/job/${jobId}/resume`, { method: "POST" });
      await pollJobs();
      selectJob(jobId, "lab");
    } catch (e) {
      alert(`Could not resume: ${e.message}`);
      if (btn) { btn.disabled = false; btn.textContent = "↻ Retry"; }
    }
  }

  // Stop a running job. Backend halts the pipeline between graph nodes and
  // persists progress as 'cancelled' so it can be resumed later.
  async function cancelJob(jobId, btn) {
    if (!jobId) return;
    if (!confirm("Stop this job? Progress is saved — you can resume it later.")) return;
    if (btn) { btn.disabled = true; btn.textContent = "■ Stopping…"; }
    try {
      await api(`/job/${jobId}/cancel`, { method: "POST" });
      await pollJobs();
    } catch (e) {
      alert(`Could not stop: ${e.message}`);
      if (btn) { btn.disabled = false; btn.textContent = "■ Stop"; }
    }
  }

  function show(id) { const el = document.getElementById(id); if (el) el.hidden = false; }
  function hide(id) { const el = document.getElementById(id); if (el) el.hidden = true; }

  /* ════════ polling ════════ */
  async function pollFleet() { try { health = await api("/services/health"); } catch { health = null; } if (view === "home" || mountKey) patchChrome(); }
  async function pollJobs() { try { jobs = await api("/jobs?limit=60"); } catch { /* keep */ } patchChrome(); }

  async function pollSelected(force) {
    if (!selectedId) return;
    let state; try { state = await api(`/job/${selectedId}`); } catch { return; }
    jobState = state;
    const meta = jobs.find((j) => j.job_id === state.job_id);
    if (meta) { createdMs = createdMs ?? parseUtc(meta.created_at); completedMs = parseUtc(meta.completed_at); }

    // auto-route on completion (unless user is on Home, Library, or composing)
    if (!setupOpen && view !== "home" && view !== "library") {
      const desired = state.status === "completed" ? "cut" : "lab";
      if (desired !== view) { view = desired; mountKey = null; }
    }
    const remounted = ensureMounted();
    if (!remounted) {
      if (view === "lab") patchLab();
      // cut is static once mounted; video.js owns the player
    }
  }

  /* ── clock + tickers ── */
  function tick(fn, ms) { fn(); setInterval(() => { if (!document.hidden) fn(); }, ms); }

  function boot() {
    view = "home";
    ensureMounted();
    setInterval(() => { const el = document.getElementById("clock"); if (el) el.textContent = fmtClock(new Date()); }, 1000);
    tick(pollFleet, 8000);
    tick(pollJobs, 5000);
    setInterval(() => { if (!document.hidden && selectedId) pollSelected(); }, 2000);
    setInterval(() => { if (!document.hidden && view === "lab" && jobState && RUNNING.has(jobState.status)) patchLab(); }, 1000);

    // deep link ?job=
    const urlJob = new URLSearchParams(location.search).get("job");
    (async () => { await pollJobs(); if (urlJob && jobs.some((j) => j.job_id === urlJob)) selectJob(urlJob); })();
  }

  boot();
})();
