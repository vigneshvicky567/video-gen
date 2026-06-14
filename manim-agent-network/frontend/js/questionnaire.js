/* Pre-submit questionnaire modal.
 * Analyzes a topic (POST /analyze) and collects a generation brief via a
 * Claude-design-question style stepper before the job is created.
 *
 * Public API:  window.Questionnaire.open(topic, { onConfirm, onDirect, onCancel })
 *   onConfirm(brief) — user finished the stepper; brief matches GenerationBrief
 *   onDirect()       — user chose to skip analysis and generate from topic alone
 *   onCancel()       — user dismissed without starting a job
 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const anim = (targets, params) => {
    if (reduceMotion || typeof anime === "undefined" || !anime.animate) return;
    try { anime.animate(targets, params); } catch (_) { /* non-fatal */ }
  };

  let els = null;
  let state = null;

  function cacheEls() {
    if (els) return els;
    els = {
      modal: $("q-modal"), backdrop: $("q-backdrop"), close: $("q-x"),
      skeleton: $("q-skeleton"), error: $("q-error"), errorMsg: $("q-error-msg"),
      retry: $("q-retry"), direct: $("q-direct"),
      flow: $("q-flow"), feas: $("q-feas"), progress: $("q-progress"),
      chip: $("q-chip"), question: $("q-question"), options: $("q-options"),
      other: $("q-other"), otherInput: $("q-other-input"),
      duration: $("q-duration"), presets: $("q-presets"), minutes: $("q-minutes"), max: $("q-max"),
      prev: $("q-prev"), next: $("q-next"), count: $("q-count"),
    };
    wireStaticHandlers();
    return els;
  }

  function wireStaticHandlers() {
    els.close.addEventListener("click", cancel);
    els.backdrop.addEventListener("click", cancel);
    els.direct.addEventListener("click", () => { close(); state.cbs.onDirect && state.cbs.onDirect(); });
    els.retry.addEventListener("click", () => runAnalysis());
    els.prev.addEventListener("click", () => { if (state.idx > 0) { state.idx--; render(); } });
    els.next.addEventListener("click", onNext);
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && els.modal && !els.modal.hidden) { e.stopPropagation(); cancel(); }
    });
  }

  function open(topic, cbs) {
    cacheEls();
    state = { topic, analyzer: null, steps: [], idx: 0, answers: {}, minutes: null, busy: false, cbs: cbs || {} };
    show(els.skeleton); hide(els.error); hide(els.flow);
    els.modal.hidden = false;
    anim(".q-card", { opacity: [0, 1], translateY: [18, 0], scale: [0.98, 1], duration: 360, ease: "outExpo" });
    runAnalysis();
  }

  async function runAnalysis() {
    show(els.skeleton); hide(els.error); hide(els.flow);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 75000);  // analyzer LLM call runs 20-50s on kimi
    try {
      const resp = await fetch("/analyze", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic: state.topic }), signal: controller.signal,
      });
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      state.analyzer = await resp.json();
      buildSteps();
      hide(els.skeleton); show(els.flow);
      state.idx = 0; render();
    } catch (e) {
      hide(els.skeleton);
      els.errorMsg.textContent = e.name === "AbortError"
        ? "Analysis timed out."
        : "The analyzer did not answer.";
      show(els.error);
    } finally {
      clearTimeout(timer);
    }
  }

  function buildSteps() {
    const a = state.analyzer;
    const questions = Array.isArray(a.questions) ? a.questions.slice() : [];
    // Pull the duration question out; it gets a dedicated final step with presets.
    const nonDuration = questions.filter((q) => q.id !== "duration");
    state.steps = nonDuration.map((q) => ({ kind: "question", q })).concat([{ kind: "duration" }]);
    state.minutes = Math.round((a.recommended_duration_seconds || 300) / 60);
    // Feasibility banner (persistent).
    const recM = Math.round((a.recommended_duration_seconds || 300) / 60);
    const maxM = Math.round((a.max_duration_seconds || 1200) / 60);
    els.feas.textContent = `${a.feasibility_summary || ""}  ·  recommended ${recM} min · max ${maxM} min`;
  }

  function render() {
    const step = state.steps[state.idx];
    // progress dots
    els.progress.innerHTML = "";
    state.steps.forEach((_, i) => {
      const dot = document.createElement("span");
      dot.className = "q-dot" + (i === state.idx ? " active" : i < state.idx ? " done" : "");
      els.progress.appendChild(dot);
    });
    els.count.textContent = `${state.idx + 1} / ${state.steps.length}`;
    els.prev.disabled = state.idx === 0;
    const last = state.idx === state.steps.length - 1;
    els.next.textContent = last ? "Start generation" : "Next";

    if (step.kind === "duration") return renderDuration();
    renderQuestion(step.q);
    anim("#q-step", { opacity: [0, 1], translateX: [12, 0], duration: 240, ease: "outExpo" });
  }

  function renderQuestion(q) {
    els.options.hidden = false;
    show(els.chip); show(els.question); hide(els.duration);
    els.chip.textContent = q.header || "";
    els.question.textContent = q.question || "";
    els.options.innerHTML = "";
    hide(els.other);
    const ans = state.answers[q.id] || { selected: [], custom: "" };
    state.answers[q.id] = ans;

    q.options.forEach((opt) => {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "q-opt" + (ans.selected.includes(opt.label) ? " selected" : "");
      card.innerHTML = `<b>${escapeHtml(opt.label)}</b>${opt.description ? `<span>${escapeHtml(opt.description)}</span>` : ""}`;
      card.addEventListener("click", () => {
        if (q.multi_select) {
          const i = ans.selected.indexOf(opt.label);
          if (i >= 0) ans.selected.splice(i, 1); else ans.selected.push(opt.label);
        } else {
          ans.selected = ans.selected[0] === opt.label ? [] : [opt.label];
        }
        renderQuestion(q); updateNext();
      });
      els.options.appendChild(card);
    });

    if (q.allows_custom) {
      const otherActive = !!ans.custom;
      const card = document.createElement("button");
      card.type = "button";
      card.className = "q-opt q-opt-other" + (otherActive ? " selected" : "");
      card.innerHTML = `<b>Other…</b><span>Describe it yourself</span>`;
      card.addEventListener("click", () => {
        show(els.other); els.otherInput.value = ans.custom || ""; els.otherInput.focus();
      });
      els.options.appendChild(card);
      if (otherActive) show(els.other); else hide(els.other);
      els.otherInput.oninput = () => { ans.custom = els.otherInput.value.trim(); updateNext(); };
    }
    updateNext();
  }

  function renderDuration() {
    els.options.innerHTML = "";
    els.options.hidden = true;
    hide(els.other); show(els.chip); show(els.question); show(els.duration);
    els.chip.textContent = "Target length";
    els.question.textContent = "How long should the video be?";
    const a = state.analyzer;
    const maxM = Math.max(1, Math.round((a.max_duration_seconds || 1200) / 60));
    els.max.textContent = `max ${maxM} min`;
    els.presets.innerHTML = "";
    (a.duration_presets || []).forEach((sec) => {
      const m = Math.round(sec / 60);
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "q-preset" + (state.minutes === m ? " selected" : "");
      chip.textContent = `${m} min`;
      chip.addEventListener("click", () => { state.minutes = m; els.minutes.value = ""; renderDuration(); updateNext(); });
      els.presets.appendChild(chip);
    });
    els.minutes.max = String(maxM);
    els.minutes.oninput = () => {
      let v = parseInt(els.minutes.value, 10);
      if (!isNaN(v)) { v = Math.min(maxM, Math.max(1, v)); state.minutes = v; renderDuration(); }
      updateNext();
    };
    updateNext();
    anim("#q-step", { opacity: [0, 1], translateX: [12, 0], duration: 240, ease: "outExpo" });
  }

  function stepAnswered() {
    const step = state.steps[state.idx];
    if (step.kind === "duration") return !!state.minutes;
    const ans = state.answers[step.q.id] || { selected: [], custom: "" };
    return ans.selected.length > 0 || !!ans.custom;
  }

  function updateNext() { els.next.disabled = !stepAnswered(); }

  function onNext() {
    if (!stepAnswered()) return;
    if (state.idx < state.steps.length - 1) { state.idx++; render(); return; }
    confirm();
  }

  function pickAnswer(id) {
    const ans = state.answers[id];
    if (!ans) return null;
    if (ans.selected.length) return ans.selected.join(", ");
    return ans.custom || null;
  }

  function buildBrief() {
    const a = state.analyzer;
    const answers = Object.entries(state.answers)
      .filter(([, v]) => v.selected.length || v.custom)
      .map(([question_id, v]) => ({ question_id, selected: v.selected, custom_text: v.custom || null }));
    const focusAns = state.answers["focus"];
    const focus_areas = focusAns
      ? focusAns.selected.concat(focusAns.custom ? [focusAns.custom] : [])
      : [];
    return {
      target_duration_seconds: state.minutes * 60,
      max_duration_seconds: a.max_duration_seconds,
      is_study_material: !!a.is_study_material,
      audience_level: pickAnswer("audience"),
      focus_areas,
      visual_style: pickAnswer("style"),
      pacing: pickAnswer("pacing"),
      answers,
    };
  }

  function confirm() {
    const brief = buildBrief();
    close();
    state.cbs.onConfirm && state.cbs.onConfirm(brief);
  }

  function cancel() { close(); state.cbs.onCancel && state.cbs.onCancel(); }

  function close() { if (els && els.modal) els.modal.hidden = true; }

  function show(el) { if (el) el.hidden = false; }
  function hide(el) { if (el) el.hidden = true; }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  window.Questionnaire = { open };
})();
