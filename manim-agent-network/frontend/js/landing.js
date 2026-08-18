/* Landing — hero canvas (animated chalkboard math) + reveals + nav state */

(() => {
  "use strict";

  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  /* ── nav scrolled state ── */
  const nav = document.getElementById("nav");
  const onScroll = () => nav.classList.toggle("scrolled", window.scrollY > 24);
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  /* ── scroll reveals ── */
  const revealed = document.querySelectorAll(".reveal");
  const io = new IntersectionObserver(
    (entries) => {
      for (const e of entries) {
        if (e.isIntersecting) {
          e.target.classList.add("in");
          io.unobserve(e.target);
        }
      }
    },
    { threshold: 0.18, rootMargin: "0px 0px -40px 0px" }
  );
  revealed.forEach((el, i) => {
    el.style.setProperty("--rd", `${(i % 4) * 0.08}s`);
    io.observe(el);
  });

  /* ── marquee: duplicate track for seamless loop ── */
  const track = document.getElementById("marquee-track");
  if (track) track.innerHTML += track.innerHTML;

  /* ── hero canvas ── */
  const canvas = document.getElementById("hero-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");

  let W = 0, H = 0, dpr = 1;
  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = canvas.clientWidth;
    H = canvas.clientHeight;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }
  resize();
  window.addEventListener("resize", resize);

  const GOLD = "242, 201, 76";
  const BLUE = "143, 179, 255";
  const CHALK = "200, 210, 235";

  /* particles: drifting motes */
  const motes = Array.from({ length: 46 }, () => ({
    x: Math.random(),
    y: Math.random(),
    r: 0.6 + Math.random() * 1.6,
    s: 0.02 + Math.random() * 0.06,
    p: Math.random() * Math.PI * 2,
  }));

  /* curve definitions — blend between function families over time */
  function curveY(x, t, k) {
    // x in [0,1] → math domain [-3.2, 3.2]
    const u = (x - 0.5) * 6.4;
    const a = Math.sin(u * (1.1 + k * 0.4) + t * (0.5 + k * 0.13));
    const b = (u * u * u) / 18 - u / 2.2;
    const c = Math.exp(-u * u / 3.4) * Math.cos(u * 2.2 + t * 0.8);
    const mix = (Math.sin(t * 0.21 + k * 2.1) + 1) / 2; // slow morph 0..1
    const m2 = (Math.cos(t * 0.13 + k) + 1) / 2;
    return a * (1 - mix) * 0.55 + b * mix * 0.5 + c * m2 * 0.65;
  }

  function drawGrid() {
    ctx.strokeStyle = `rgba(${CHALK}, 0.045)`;
    ctx.lineWidth = 1;
    const step = Math.max(44, W / 26);
    ctx.beginPath();
    for (let x = (W / 2) % step; x < W; x += step) {
      ctx.moveTo(x, 0); ctx.lineTo(x, H);
    }
    for (let y = (H / 2) % step; y < H; y += step) {
      ctx.moveTo(0, y); ctx.lineTo(W, y);
    }
    ctx.stroke();

    // axes, slightly brighter
    ctx.strokeStyle = `rgba(${CHALK}, 0.10)`;
    ctx.beginPath();
    ctx.moveTo(0, H * 0.62); ctx.lineTo(W, H * 0.62);
    ctx.moveTo(W * 0.5, 0); ctx.lineTo(W * 0.5, H);
    ctx.stroke();
  }

  function drawCurve(t, k, color, alpha, lw) {
    const yMid = H * 0.62;
    const amp = Math.min(H * 0.16, 150);
    ctx.strokeStyle = `rgba(${color}, ${alpha})`;
    ctx.lineWidth = lw;
    ctx.shadowColor = `rgba(${color}, ${alpha * 0.9})`;
    ctx.shadowBlur = 14;
    ctx.beginPath();
    const N = 140;
    for (let i = 0; i <= N; i++) {
      const x = i / N;
      const y = yMid - curveY(x, t, k) * amp;
      if (i === 0) ctx.moveTo(x * W, y);
      else ctx.lineTo(x * W, y);
    }
    ctx.stroke();
    ctx.shadowBlur = 0;

    // draw-head: glowing dot travelling the curve
    const hx = ((t * (0.06 + k * 0.018)) % 1.2) - 0.1;
    if (hx >= 0 && hx <= 1) {
      const hy = yMid - curveY(hx, t, k) * amp;
      const grd = ctx.createRadialGradient(hx * W, hy, 0, hx * W, hy, 26);
      grd.addColorStop(0, `rgba(${color}, ${alpha * 1.4})`);
      grd.addColorStop(1, `rgba(${color}, 0)`);
      ctx.fillStyle = grd;
      ctx.beginPath();
      ctx.arc(hx * W, hy, 26, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = `rgba(${color}, 0.95)`;
      ctx.beginPath();
      ctx.arc(hx * W, hy, 2.6, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  function drawMotes(t) {
    for (const m of motes) {
      const x = (m.x + Math.sin(t * m.s + m.p) * 0.012) * W;
      const y = (m.y + Math.cos(t * m.s * 0.8 + m.p) * 0.012) * H;
      const tw = 0.25 + 0.45 * Math.abs(Math.sin(t * 0.6 + m.p));
      ctx.fillStyle = `rgba(${CHALK}, ${0.12 * tw})`;
      ctx.beginPath();
      ctx.arc(x, y, m.r, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  let start = performance.now();
  function frame(now) {
    const t = (now - start) / 1000;
    ctx.clearRect(0, 0, W, H);
    drawGrid();
    drawMotes(t);
    drawCurve(t, 0, GOLD, 0.5, 1.8);
    drawCurve(t + 4.2, 1, BLUE, 0.3, 1.3);
    drawCurve(t + 9.1, 2, CHALK, 0.14, 1.1);
    requestAnimationFrame(frame);
  }

  if (reduceMotion) {
    // single static frame
    drawGrid();
    drawCurve(3, 0, GOLD, 0.5, 1.8);
    drawCurve(7.2, 1, BLUE, 0.3, 1.3);
  } else {
    requestAnimationFrame(frame);
  }
})();
