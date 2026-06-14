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
    { nm: "Script",   ic: '<path d="M5 4h14M5 9h14M5 14h9"/>',                 keys: ["starting", "pending", "script_generation"] },
    { nm: "Code",     ic: '<path d="M8 6l-4 6 4 6M16 6l4 6-4 6"/>',           keys: ["code_generation"] },
    { nm: "Validate", ic: '<path d="M5 12l4 4L19 6"/>',                        keys: ["validation"] },
    { nm: "Voice",    ic: '<path d="M12 4v16M7 9v6M17 9v6"/>',                 keys: ["voiceover", "voiceover_and_images"] },
    { nm: "Assemble", ic: '<path d="M4 7h7v7H4zM13 10h7v7h-7z"/>',            keys: ["assembly"] },
    { nm: "Film",     ic: '<circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2"/>', keys: ["completed"] },
  ];

  /* ── state ── */
  let jobs = [], health = null;
  let selectedId = null, jobState = null, prevState = null;
  let view = "home";
  let etaSmooth = null, createdMs = null, completedMs = null;
  let feedLines = [];                 // accumulated live log lines for the lab
  let mountKey = null;                // what shell is currently rendered
  let lastJobsSig = "", lastHealthSig = "";
  let filmMounted = false;            // cut: video src set once
  let setupOpen = false;

  /* setup/analyze working state */
  let analyzer = null, setupAns = {}, setupPrompt = "", setupBusy = false;

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
      starting: "summoning", pending: "summoning", script_generation: "writing script",
      code_generation: "writing code", validation: "validating", voiceover: "narrating",
      voiceover_and_images: "narrating", assembly: "assembling",
      completed: "ready", failed: "failed",
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
    const c = counts(state);
    let idx = 0;
    if (c.coded) idx = 1;
    if (c.rendered) idx = 2;
    if (c.voiced) idx = 3;
    if (state.final_output_path) idx = 4;
    return idx;
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
      <div class="switch">${tab("home", "Home")}${tab("cut", "The cut")}${tab("lab", "The lab")}</div>
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

  function slate() {
    return `<div class="slate">
      <span class="clap">Roll camera —</span>
      <input id="slate-input" maxlength="300" placeholder="Describe an idea to film… e.g. how a hash map handles collisions"/>
      <button class="go" id="slate-go">Make it <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#0a0b0e" stroke-width="2.4"><path d="M5 12h14M13 6l6 6-6 6"/></svg></button>
    </div>`;
  }

  function drawerItems() {
    if (!jobs.length) return `<p class="cs-empty">No films yet.<br/>The swarm awaits its first command.</p>`;
    return jobs.map((f) => {
      const kind = f.status === "completed" ? "ready" : f.status === "failed" ? "fail" : "render";
      const badge = f.status === "completed" ? "Ready" : f.status === "failed" ? "Failed" : "Rendering";
      const meta = `${chipText(f.status)} · ${timeAgo(parseUtc(f.created_at))}`;
      return `<div class="cs ${f.job_id === selectedId ? "on" : ""}" data-id="${f.job_id}">
        <div class="ti">${esc(f.topic)}</div>
        <div class="ti-meta">${esc(meta)}</div>
        <span class="bd bd-${kind}">${badge}</span>
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
        <span class="model">Standard <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg></span>
        <button class="roll" id="home-roll" aria-label="Set up the shot"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#0a0b0e" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg></button>
      </div>
      <div class="starters">
        ${STARTERS.map((s, i) => `<button class="starter" data-q="${esc(s)}" style="--i:${i}">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="9"/><path d="M10 8l6 4-6 4z" fill="currentColor" stroke="none"/></svg>${esc(s)}</button>`).join("")}
      </div>
      <div class="home-foot">8 scenes · 1080p · narrated · captions baked in</div>
    </div>${overlaysNoSlate()}`;
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
    return `${marquee()}
    <div class="canvas">
      <div class="proj">
        <div class="proj-head">
          <div>
            <div class="meta-eyebrow"><span class="live"></span>Ready to watch · final cut</div>
            <h1>${esc(st.topic || "Untitled")}</h1>
          </div>
          <div class="facts">
            <b>≈ ${fmtDur(runtime)}</b> runtime<br><b>${c.scenes}</b> scenes · 1080p<br><b>${c.retries}</b> retries auto-healed
          </div>
        </div>
        <div class="screen" id="screen">
          <video class="screenvid" id="film-video" playsinline preload="metadata"></video>
          <div class="grain"></div>
          ${cap ? `<div class="cap"><p>“${esc(cap)}”</p></div>` : ""}
          <button class="bigplay" id="bigplay"><svg width="26" height="28" viewBox="0 0 22 24" fill="#ECE7DA"><path d="M2 2L20 12L2 22V2Z"/></svg></button>
          <div class="scrub">
            <span class="tm" id="film-tm">0:00 / ${fmtDur(runtime)}</span>
            <div class="track"><i id="film-prog"></i></div>
          </div>
        </div>
        <div class="canister">
          <a class="dl" id="film-dl" href="/video/${selectedId}" download><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#0a0b0e" stroke-width="2.2"><path d="M12 3v12m0 0l-4-4m4 4l4-4M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2"/></svg>Download film</a>
          <div class="fmt"><b>1080p</b> MP4 · <b>captions</b> baked in · <b>Kokoro</b> voice</div>
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

  function frameHtml(s, st, i) {
    const sid = String(s.scene_id);
    const state = sceneState(sid, st);
    const type = (s.content_type || "manim").toLowerCase();
    const anim = type === "manim";
    const title = s.title || (s.visual_description || "").slice(0, 80) || `Scene ${sid}`;
    return `<div class="frame" data-st="${state}" data-id="${sid}" data-title="${esc(s.title || ("Scene " + sid))}" style="--i:${i || 0}">
      <div class="pic">
        <span class="n">SC ${sid.padStart(2, "0")}</span>
        <span class="eng ${anim ? "e-anim" : "e-frame"}">${anim ? "animated" : "frames"}</span>
        <div class="mini"><svg width="9" height="11" viewBox="0 0 10 12" fill="#ece7da"><path d="M0 0l10 6-10 6z"/></svg></div>
      </div>
      <div class="cap2"><div class="ti">${esc(title)}</div>
        <div class="fr"><span class="ok">${SCENE_LABEL[state]}</span><span class="du">${s.estimated_duration_seconds ?? "–"}s</span></div></div>
    </div>`;
  }

  function synthCutLog(st) {
    const c = counts(st);
    const rows = [
      ["director", `final cut assembled — <b>ready to watch</b>`, "good"],
      ["narrator", `voice track synced across ${c.scenes} scenes`, ""],
      c.retries ? ["validator", `${c.retries} frame error${c.retries > 1 ? "s" : ""} caught and <b>healed</b>`, "bad"] : null,
      ["camera", `${c.rendered} of ${c.scenes} scenes developed`, ""],
      ["script-writer", `screenplay: “${esc(st.script?.title || st.topic || "")}”`, ""],
    ].filter(Boolean);
    return rows.map(([who, ms, tone], i) =>
      `<div class="ln ${tone}"><span class="tm">${String(i).padStart(2, "0")}:00</span><span class="who">${who}</span><span class="ms">${ms}</span></div>`
    ).join("");
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
    const failed = st.status === "failed";
    const created = createdMs ? new Date(createdMs).toLocaleString() : "—";
    return `${marquee()}
    <div class="canvas">
      <div class="proj"><div class="proj-head">
        <div>
          <div class="meta-eyebrow ${failed ? "warn" : ""}"><span class="live"></span>${failed ? "Pipeline fault" : "In the lab · developing"}</div>
          <h1>${esc(st.topic || "Untitled")}</h1>
        </div>
        <div class="facts">
          job <b class="jobid" id="jobid">${esc((st.job_id || "").slice(0, 8))}…</b><br>${esc(created)}<br>six stages, in order
        </div>
      </div></div>

      <div class="devtrack">
        <div class="strip-label" style="padding-left:0">Developing track <span class="ct" id="track-ct">·</span></div>
        <div class="dev-stages" id="dev-stages">
          <div class="conn"><i id="conn-fill"></i></div>
          ${STAGES.map((s, i) => `<div class="dev-node" id="node-${i}" style="--i:${i}">
            <div class="orb"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${s.ic}</svg></div>
            <div class="nm">${s.nm}</div><div class="st" id="node-st-${i}"></div>
          </div>`).join("")}
        </div>

        <div class="dev-readout">
          <div class="cell"><div class="k">Time remaining</div><div class="v lime" id="ro-eta">—</div></div>
          <div class="cell"><div class="k">Elapsed</div><div class="v" id="ro-elapsed">0:00</div></div>
          <div class="cell"><div class="k">Scenes</div><div class="v" id="ro-scenes">0<small>/0</small></div>
            <div class="scenebar" id="scenebar"></div></div>
          <div class="cell"><div class="k">Auto-healed</div><div class="v" id="ro-retries">0<small> retries</small></div></div>
        </div>
      </div>

      <div class="errbar" id="errbar" ${failed && st.overall_error ? "" : "hidden"}>
        <b>Pipeline fault</b><pre id="err-text">${esc(st.overall_error || "")}</pre>
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
    const failed = st.status === "failed";
    const cur = failed ? failStageIdx(st) : curStageIdx(st.status);

    // stages
    STAGES.forEach((s, i) => {
      const node = document.getElementById(`node-${i}`);
      if (!node) return;
      let cls = "dev-node", label = "";
      if (st.status === "completed" || i < cur) { cls += " done"; label = "done"; }
      else if (failed && i === cur) { cls += " fail"; label = "fault"; }
      else if (i === cur) { cls += " cur"; label = "in progress"; }
      else { label = "waiting"; }
      node.className = cls;
      const stEl = document.getElementById(`node-st-${i}`);
      if (stEl) stEl.textContent = label;
    });
    const cf = document.getElementById("conn-fill");
    if (cf) cf.style.width = (st.status === "completed" ? 100 : (cur / (STAGES.length - 1)) * 100) + "%";
    const tct = document.getElementById("track-ct");
    if (tct) tct.textContent = failed ? `· stopped at ${STAGES[cur].nm.toLowerCase()}` : `· stage ${Math.min(cur + 1, 6)} of 6`;

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

    // scenebar
    const bar = document.getElementById("scenebar");
    if (bar) {
      const scenes = st.script?.scenes || [];
      if (bar.children.length !== scenes.length) { bar.innerHTML = ""; scenes.forEach(() => bar.appendChild(document.createElement("i"))); }
      scenes.forEach((sc, i) => {
        const stt = sceneState(String(sc.scene_id), st);
        const b = bar.children[i]; if (!b) return;
        b.className = stt === "rendered" ? "done" : stt === "error" ? "fail" : (stt === "coding" || stt === "retry") ? "live" : "";
      });
    }

    // error
    const eb = document.getElementById("errbar");
    if (eb) { const show = failed && st.overall_error; eb.hidden = !show; if (show) setText("err-text", st.overall_error); }

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
    const name = (sid) => { const sc = cur.script?.scenes?.find((s) => String(s.scene_id) === String(sid)); return sc?.title ? `scene ${sid} “${esc(sc.title)}”` : `scene ${sid}`; };
    if (!prev) { pushFeed("director", `tracking transmission · ${chipText(cur.status)}`); return; }
    if (prev.status !== cur.status) {
      const tone = cur.status === "failed" ? "bad" : cur.status === "completed" ? "good" : "";
      pushFeed("director", `phase → <b>${chipText(cur.status)}</b>`, tone);
    }
    if (!prev.script && cur.script)
      pushFeed("script-writer", `screenplay ready — ${cur.script.scenes?.length ?? 0} scenes: “${esc(cur.script.title || "")}”`, "good");
    const fresh = (a, b) => Object.keys(b || {}).filter((k) => !(k in (a || {})));
    for (const k of fresh(prev.code_paths, cur.code_paths)) pushFeed("coder", `${name(k)} — animation written`);
    for (const k of fresh(prev.render_paths, cur.render_paths)) pushFeed("validator", `${name(k)} — <b>developed ✓</b>`, "good");
    for (const k of fresh(prev.audio_paths, cur.audio_paths)) pushFeed("narrator", `${name(k)} — narration recorded`);
    for (const k of fresh(prev.image_paths, cur.image_paths)) pushFeed("camera", `${name(k)} — visuals fetched`);
    for (const [k, v] of Object.entries(cur.retry_counts || {})) { const was = (prev.retry_counts || {})[k] || 0; if (v > was) pushFeed("coder", `${name(k)} — retry #${v}, <b>healing</b>`, "bad"); }
    for (const k of fresh(prev.error_logs, cur.error_logs)) pushFeed("validator", `${name(k)} — fault captured, sent back`, "bad");
    if (!prev.final_output_path && cur.final_output_path) pushFeed("assembler", "final cut stitched + encoded ✓", "good");
    if (cur.status === "failed" && prev.status !== "failed") pushFeed("director", esc(cur.overall_error || "pipeline failed"), "bad");
  }

  function setText(id, text, html) {
    const el = document.getElementById(id);
    if (!el) return;
    if (html != null) el.innerHTML = html; else el.textContent = text;
  }

  /* ════════ mount + route ════════ */
  function keyFor() { return view === "home" ? "home" : `${view}:${selectedId || ""}`; }

  function ensureMounted() {
    const k = keyFor();
    if (k === mountKey) return false;
    mountKey = k; filmMounted = false;
    root.innerHTML = view === "home" ? homeShell() : view === "cut" ? cutShell() : labShell();
    wire();
    if (view === "cut") mountFilm();
    if (view === "lab") { renderFeed(); patchLab(); }
    return true;
  }

  function mountFilm() {
    if (filmMounted || !jobState || jobState.status !== "completed") return;
    const v = document.getElementById("film-video");
    if (!v) return;
    v.src = `/video/${selectedId}`;
    filmMounted = true;
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

    // compose entry points
    const hi = document.getElementById("home-input");
    const hr = document.getElementById("home-roll");
    if (hr) hr.onclick = () => openSetup(hi ? hi.value : "");
    if (hi) hi.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); openSetup(hi.value); } };
    root.querySelectorAll(".starter").forEach((s) => s.onclick = () => { if (hi) hi.value = s.dataset.q; openSetup(s.dataset.q); });

    const si = document.getElementById("slate-input"), sg = document.getElementById("slate-go");
    if (sg) sg.onclick = () => openSetup(si ? si.value : "");
    if (si) si.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); openSetup(si.value); } };

    // film player (cut)
    const bp = document.getElementById("bigplay"), v = document.getElementById("film-video"), screen = document.getElementById("screen");
    if (bp && v) bp.onclick = () => v.play().catch(() => {});
    if (v && screen) {
      v.onplay = () => { screen.classList.add("played"); v.setAttribute("controls", ""); };
      v.ontimeupdate = () => {
        if (!v.duration) return;
        const p = document.getElementById("film-prog"); if (p) p.style.width = (v.currentTime / v.duration) * 100 + "%";
        const tm = document.getElementById("film-tm"); if (tm) tm.textContent = `${fmtDur(v.currentTime)} / ${fmtDur(v.duration)}`;
      };
    }
    // scene clips (cut)
    root.querySelectorAll('.frame[data-st="rendered"]').forEach((f) =>
      f.onclick = () => openClip(`SC ${f.dataset.id} — ${f.dataset.title}`, `/video/${selectedId}/scene/${f.dataset.id}`));

    // copy job id (lab)
    const jid = document.getElementById("jobid");
    if (jid && jobState) jid.onclick = async () => {
      try { await navigator.clipboard.writeText(jobState.job_id || ""); const old = jid.textContent; jid.textContent = "copied ✓"; setTimeout(() => jid.textContent = old, 1200); } catch {}
    };

    // clip modal
    const cs = document.getElementById("clip-scrim"), cx = document.getElementById("clip-x");
    if (cs) cs.onclick = (e) => { if (e.target === cs) closeClip(); };
    if (cx) cx.onclick = closeClip;

    wireSetup();
  }

  function wireDrawerItems() {
    root.querySelectorAll(".cs[data-id]").forEach((el) => el.onclick = () => {
      document.getElementById("drawer")?.classList.remove("show");
      document.getElementById("scrim")?.classList.remove("show");
      selectJob(el.dataset.id);
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
    const qs = (Array.isArray(a.questions) ? a.questions : []).filter((q) => q.id !== "duration");
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

    // auto-route on completion (unless user is on Home or composing)
    if (!setupOpen && view !== "home") {
      const desired = state.status === "completed" ? "cut" : "lab";
      if (desired !== view) { view = desired; mountKey = null; }
    }
    const remounted = ensureMounted();
    if (!remounted) {
      if (view === "lab") patchLab();
      else if (view === "cut") { mountFilm(); }
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
