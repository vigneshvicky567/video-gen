import { useMemo } from 'react';

export function Architecture() {
  const styleContent = `
#diagram-root{
  font-family:var(--font-sans);
  background: radial-gradient(1100px 560px at 50% -12%,rgba(216,255,62,.055),transparent 58%),
              radial-gradient(800px 500px at 50% 120%,rgba(79,209,197,.04),transparent 55%),
              var(--color-ink);
  color:var(--color-paper);
  padding:54px 40px 64px;
  -webkit-font-smoothing:antialiased;
}
@media (prefers-reduced-motion:reduce){
  #diagram-root *{animation:none!important}
  #diagram-root .draw{stroke-dashoffset:0!important}
  #diagram-root .fade{opacity:1!important}
}
#diagram-root .head{max-width:1200px;margin:0 auto}
#diagram-root .eye{font-family:var(--font-mono);font-size:11px;letter-spacing:.26em;text-transform:uppercase;color:var(--color-signal);display:flex;align-items:center;gap:11px;margin-bottom:18px}
#diagram-root .eye .d{width:6px;height:6px;border-radius:50%;background:var(--color-signal);box-shadow:0 0 9px var(--color-signal);animation:arch-beat 1.7s ease-in-out infinite}
@keyframes arch-beat{50%{opacity:.45;transform:scale(.82)}}
#diagram-root .eye .ln{flex:1;height:1px;background:linear-gradient(90deg,var(--color-line),transparent)}
#diagram-root .head h1{font-family:var(--font-serif);font-size:clamp(28px,3.6vw,44px);font-weight:500;letter-spacing:-.025em;line-height:1.02;margin-bottom:13px}
#diagram-root .head h1 em{font-style:italic;color:var(--color-signal)}
#diagram-root .head p{font-size:15px;color:var(--color-muted);max-width:64ch;line-height:1.6}
#diagram-root .head p b{color:var(--color-paper);font-weight:500}

#diagram-root .canvas{max-width:1200px;margin:34px auto 0;border:1px solid var(--color-line);border-radius:18px;
  background:linear-gradient(180deg,rgba(22,25,34,.42),rgba(15,17,22,.42));
  padding:10px;overflow-x:auto;box-shadow:0 40px 110px -50px rgba(216,255,62,.14), inset 0 1px 0 rgba(236,231,218,.03)}
#diagram-root .canvas::-webkit-scrollbar{height:6px}
#diagram-root .canvas::-webkit-scrollbar-thumb{background:var(--color-line);border-radius:9px}
#diagram-root svg{display:block;width:100%;height:auto;min-width:1000px}

#diagram-root .legend{max-width:1200px;margin:24px auto 0;display:flex;flex-wrap:wrap;gap:24px;align-items:center}
#diagram-root .legend .it{display:flex;align-items:center;gap:9px;font-family:var(--font-mono);font-size:11.5px;color:var(--color-muted);letter-spacing:.02em}
#diagram-root .legend .sw{width:24px;height:4px;border-radius:9px;flex:0 0 24px}
#diagram-root .legend .ring{width:13px;height:13px;border-radius:50%;border:1.6px solid;flex:0 0 13px}

#diagram-root .notes{max-width:1200px;margin:34px auto 0;display:grid;grid-template-columns:repeat(3,1fr);gap:14px}
#diagram-root .note{position:relative;border:1px solid var(--color-line-soft);border-radius:14px;background:var(--color-ink-2);padding:20px 20px 22px;overflow:hidden}
#diagram-root .note::before{content:"";position:absolute;left:0;top:0;bottom:0;width:2px}
#diagram-root .note.fan::before{background:var(--color-signal)}
#diagram-root .note.par::before{background:var(--color-teal)}
#diagram-root .note.mrg::before{background:var(--color-amber)}
#diagram-root .note .n{font-family:var(--font-mono);font-size:10px;letter-spacing:.18em;text-transform:uppercase;color:var(--color-muted-2);margin-bottom:11px}
#diagram-root .note h3{font-size:15px;font-weight:600;margin-bottom:8px;letter-spacing:-.01em;display:flex;align-items:center;gap:8px}
#diagram-root .note h3 .tag{font-family:var(--font-mono);font-size:8.5px;letter-spacing:.08em;text-transform:uppercase;padding:3px 7px;border-radius:4px;font-weight:400}
#diagram-root .t-fan{color:var(--color-signal);background:rgba(216,255,62,.1)}
#diagram-root .t-par{color:var(--color-teal);background:rgba(79,209,197,.1)}
#diagram-root .t-mrg{color:var(--color-amber);background:rgba(245,183,61,.1)}
#diagram-root .note p{font-size:13px;color:var(--color-muted);line-height:1.55}
#diagram-root .note p b{color:var(--color-paper);font-weight:500}

@media(max-width:760px){
  #diagram-root .notes{grid-template-columns:1fr}
}

#diagram-root .lbl{font-family:var(--font-mono);font-size:12.5px;letter-spacing:.13em;fill:var(--color-paper);text-transform:uppercase;font-weight:500}
#diagram-root .sub{font-family:var(--font-mono);font-size:10px;fill:var(--color-muted-2);letter-spacing:.05em}
#diagram-root .band-lbl{font-family:var(--font-mono);font-size:10.5px;letter-spacing:.2em;fill:var(--color-teal);text-transform:uppercase}
#diagram-root .stage-lbl{font-family:var(--font-mono);font-size:9px;letter-spacing:.1em;fill:var(--color-muted);text-transform:uppercase}
#diagram-root .scene-tag{font-family:var(--font-mono);font-size:9.5px;fill:var(--color-muted);letter-spacing:.06em}
#diagram-root .cap{font-family:var(--font-mono);font-size:10.5px;letter-spacing:.2em;fill:var(--color-muted-2);text-transform:uppercase}
#diagram-root .statev{font-family:var(--font-mono);font-size:9px;letter-spacing:.04em}

#diagram-root .draw{stroke-dasharray:var(--len);stroke-dashoffset:var(--len);animation:arch-draw 1.1s cubic-bezier(.4,0,.2,1) forwards}
@keyframes arch-draw{to{stroke-dashoffset:0}}
#diagram-root .fade{opacity:0;animation:arch-fade .6s ease forwards}
@keyframes arch-fade{to{opacity:1}}
#diagram-root .pulse-dot{opacity:0}
  `;

  const htmlContent = useMemo(() => {
    /* ---------- geometry ---------- */
    const W=1200, H=600;
    const cy=H/2, R=36, r2=23;
    const SCENES=4;

    const xScript   = 132;
    const xBandL    = 410;
    const xBandR    = 770;
    const xAssemble = 952;
    const xFilm     = W-92;

    const laneGap = 96;
    const laneTop = cy - laneGap*(SCENES-1)/2;
    const lanes   = Array.from({length:SCENES},(_,i)=>laneTop+i*laneGap);

    const subX=[xBandL+34, (xBandL+xBandR)/2, xBandR-34];
    const subStages=['code','voice','validate'];
    const subLabels=['Code','Voice','Validate'];

    /* ---------- crafted icons (1.8 stroke, 24-box, centered) ---------- */
    const ICON: Record<string, string> ={
      script:'<path d="M-7 -6h14M-7 -1h14M-7 4h9"/>',
      code:'<path d="M-3.5 -6l-5.5 6 5.5 6M3.5 -6l5.5 6-5.5 6"/>',
      voice:'<path d="M0 -8v16M-4.5 -4.5v9M4.5 -4.5v9M-9 -2v4M9 -2v4"/>',
      validate:'<path d="M-7 0.5l4.5 4.5L8 -6"/>',
      assemble:'<rect x="-9" y="-7" width="8" height="8" rx="1.4"/><rect x="1" y="-1" width="8" height="8" rx="1.4"/>',
      film:'<circle cx="0" cy="0" r="7.5"/><circle cx="0" cy="0" r="2.4" fill="currentColor" stroke="none"/>'
    };

    function node(x: number, y: number, r: number, icon: string, state: string, delay: number){
      const stroke = state==='cur'?'var(--color-signal)':state==='done'?'var(--color-teal)':'var(--color-muted-2)';
      const ring = state==='cur'?`<circle cx="${x}" cy="${y}" r="${r+9}" fill="none" stroke="${stroke}" stroke-width="1" opacity=".22"><animate attributeName="r" values="${r+6};${r+13};${r+6}" dur="2.4s" repeatCount="indefinite"/><animate attributeName="opacity" values=".28;0;.28" dur="2.4s" repeatCount="indefinite"/></circle>`:'';
      const glow = state==='cur'?'filter="url(#glow)"':'';
      return `
      <g class="fade" style="animation-delay:${delay}ms">
        ${ring}
        <circle cx="${x}" cy="${y}" r="${r}" fill="url(#nodeFill)" stroke="${stroke}" stroke-width="1.7" ${glow}/>
        <circle cx="${x}" cy="${y}" r="${r}" fill="none" stroke="${stroke}" stroke-width="1" opacity=".25"/>
        <g transform="translate(${x},${y})" fill="none" stroke="${stroke}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${icon}</g>
      </g>`;
    }

    function approxLen(x1: number, y1: number, x2: number, y2: number){const dx=x2-x1,dy=y2-y1;return Math.hypot(dx,dy)*1.18;}

    function curve(x1: number, y1: number, x2: number, y2: number, stroke: string, delay: number, withPulse: boolean, pulseColor: string){
      const mx=(x1+x2)/2;
      const d=`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`;
      const len=approxLen(x1,y1,x2,y2);
      const pulse = withPulse?`
        <circle r="2.6" fill="${pulseColor}" class="pulse-dot" filter="url(#glow)">
          <animateMotion dur="2.2s" begin="${(delay+900)/1000}s" repeatCount="indefinite" path="${d}" keyPoints="0;1" keyTimes="0;1" calcMode="spline" keySplines="0.4 0 0.6 1"/>
          <animate attributeName="opacity" values="0;1;1;0" keyTimes="0;0.1;0.85;1" dur="2.2s" begin="${(delay+900)/1000}s" repeatCount="indefinite"/>
        </circle>`:'';
      return `<path d="${d}" fill="none" stroke="${stroke}" stroke-width="1.7" opacity=".85" class="draw" style="--len:${len};animation-delay:${delay}ms"/>${pulse}`;
    }

    function build(){
      const bandTop=laneTop-laneGap*0.5, bandH=laneGap*(SCENES-1)+laneGap;

      const fan = lanes.map((y,i)=>curve(xScript+R, cy, xBandL-28, y, 'url(#fanGrad)', 200+i*90, true, 'var(--color-signal)')).join('');
      const merge = lanes.map((y,i)=>curve(xBandR+28, y, xAssemble-R, cy, 'url(#mergeGrad)', 1300+i*80, true, 'var(--color-teal)')).join('');
      const tail = `<path d="M${xAssemble+R},${cy} L${xFilm-R},${cy}" stroke="url(#tailGrad)" stroke-width="1.7" class="draw" style="--len:${xFilm-R-(xAssemble+R)};animation-delay:1900ms"/>
        <circle r="2.6" fill="var(--color-amber)" class="pulse-dot" filter="url(#glow)">
          <animateMotion dur="2s" begin="2.8s" repeatCount="indefinite" path="M${xAssemble+R},${cy} L${xFilm-R},${cy}"/>
          <animate attributeName="opacity" values="0;1;1;0" keyTimes="0;0.1;0.85;1" dur="2s" begin="2.8s" repeatCount="indefinite"/>
        </circle>`;

      const laneGfx = lanes.map((y,i)=>{
        const line=`<line x1="${subX[0]}" y1="${y}" x2="${subX[2]}" y2="${y}" stroke="var(--color-line)" stroke-width="1.3" class="fade" style="animation-delay:${700+i*90}ms"/>`;
        const nodes=subStages.map((s,j)=>node(subX[j],y,r2,ICON[s],'done',800+i*90+j*60)).join('');
        const tag=`<text class="scene-tag fade" x="${subX[0]}" y="${y-r2-9}" text-anchor="middle" style="animation-delay:${800+i*90}ms">SC ${String(i+1).padStart(2,'0')}</text>`;
        const flowPath=`M${subX[0]-r2},${y} L${subX[2]+r2},${y}`;
        const begin=(1.4+i*0.55).toFixed(2);
        const flow=`<circle r="2.4" fill="var(--color-teal)" class="pulse-dot" filter="url(#glow)">
            <animateMotion dur="2.6s" begin="${begin}s" repeatCount="indefinite" path="${flowPath}" calcMode="spline" keyPoints="0;1" keyTimes="0;1" keySplines="0.45 0 0.55 1"/>
            <animate attributeName="opacity" values="0;1;1;0" keyTimes="0;0.12;0.8;1" dur="2.6s" begin="${begin}s" repeatCount="indefinite"/>
          </circle>`;
        const pathStart=subX[0]-r2, pathEnd=subX[2]+r2, span=pathEnd-pathStart, dur=2.6;
        const flickers=subX.map((sx)=>{
          const frac=(sx-pathStart)/span;
          const fb=(1.4+i*0.55 + frac*dur - 0.1).toFixed(2);
          return `<circle cx="${sx}" cy="${y}" r="${r2}" fill="none" stroke="var(--color-teal)" stroke-width="1.7" opacity="0">
            <animate attributeName="opacity" values="0;0.9;0" keyTimes="0;0.5;1" dur="0.55s" begin="${fb}s" repeatCount="indefinite"/>
            <animate attributeName="r" values="${r2};${r2+5};${r2}" keyTimes="0;0.5;1" dur="0.55s" begin="${fb}s" repeatCount="indefinite"/>
          </circle>`;
        }).join('');
        return line+nodes+tag+flow+flickers;
      }).join('');

      const colLabels = subStages.map((_,j)=>
        `<text class="stage-lbl fade" x="${subX[j]}" y="${bandTop-20}" text-anchor="middle" style="animation-delay:700ms">${subLabels[j]}</text>`
      ).join('');

      return `
      <svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Kinetic parallel render pipeline">
        <defs>
          <filter id="glow" x="-80%" y="-80%" width="260%" height="260%">
            <feGaussianBlur stdDeviation="3.4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
          </filter>
          <radialGradient id="nodeFill" cx="0.5" cy="0.35" r="0.7">
            <stop offset="0" stop-color="#1a1e29"/><stop offset="1" stop-color="#0d0f15"/>
          </radialGradient>
          <linearGradient id="fanGrad" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stop-color="var(--color-signal)"/><stop offset="1" stop-color="var(--color-teal)"/>
          </linearGradient>
          <linearGradient id="mergeGrad" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stop-color="var(--color-teal)"/><stop offset="1" stop-color="var(--color-amber)"/>
          </linearGradient>
          <linearGradient id="tailGrad" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0" stop-color="var(--color-amber)"/><stop offset="1" stop-color="var(--color-paper)"/>
          </linearGradient>
        </defs>

        <!-- parallel band -->
        <rect class="fade" style="animation-delay:600ms" x="${xBandL-62}" y="${bandTop}" width="${xBandR-xBandL+124}" height="${bandH}" rx="16"
          fill="rgba(79,209,197,.035)" stroke="var(--color-teal)" stroke-opacity=".22" stroke-width="1" stroke-dasharray="2 6"/>
        <text class="band-lbl fade" x="${(xBandL+xBandR)/2}" y="${bandTop-56}" text-anchor="middle" style="animation-delay:650ms">parallel scene agents</text>
        <text class="scene-tag fade" x="${(xBandL+xBandR)/2}" y="${bandTop-56+15}" text-anchor="middle" style="animation-delay:650ms" fill="var(--color-muted-2)">one independent agent per scene · stages 2–4</text>

        ${fan}${merge}${tail}
        ${colLabels}
        ${laneGfx}

        <!-- single-track nodes -->
        ${node(xScript, cy, R, ICON.script, 'cur', 100)}
        ${node(xAssemble, cy, R, ICON.assemble, 'wait', 1700)}
        ${node(xFilm, cy, R, ICON.film, 'wait', 2000)}

        <!-- labels -->
        <g class="fade" style="animation-delay:200ms">
          <text class="lbl" x="${xScript}" y="${cy+R+26}" text-anchor="middle">Script</text>
          <text class="sub" x="${xScript}" y="${cy+R+42}" text-anchor="middle">splits prompt → N scenes</text>
          <text class="statev" x="${xScript}" y="${cy-R-16}" text-anchor="middle" fill="var(--color-signal)">● in progress</text>
        </g>
        <g class="fade" style="animation-delay:1750ms">
          <text class="lbl" x="${xAssemble}" y="${cy+R+26}" text-anchor="middle">Assemble</text>
          <text class="sub" x="${xAssemble}" y="${cy+R+42}" text-anchor="middle">stitch + caption</text>
          <text class="statev" x="${xAssemble}" y="${cy-R-16}" text-anchor="middle" fill="var(--color-muted-2)">barrier · waits on all</text>
        </g>
        <g class="fade" style="animation-delay:2050ms">
          <text class="lbl" x="${xFilm}" y="${cy+R+26}" text-anchor="middle">Film</text>
          <text class="sub" x="${xFilm}" y="${cy+R+42}" text-anchor="middle">signed URL</text>
        </g>

        <!-- flow captions under the band -->
        <text class="cap fade" x="${(xScript+xBandL)/2-6}" y="${bandTop+bandH+34}" text-anchor="middle" style="animation-delay:500ms">fan-out</text>
        <text class="cap fade" x="${(xBandR+xAssemble)/2+6}" y="${bandTop+bandH+34}" text-anchor="middle" style="animation-delay:1600ms">converge</text>
      </svg>`;
    }

    return `
      <div class="head">
        <div class="eye"><span class="d"></span>Kinetic · render architecture<span class="ln"></span></div>
        <h1>The pipeline isn't a line — it's a <em>fan-out</em>.</h1>
        <p><b>Script</b> splits one prompt into N scenes. Each scene is handed to its <b>own agent</b> that runs Code → Voice → Validate <b>in parallel</b> with the rest. When every lane passes validation, the work <b>converges</b> through a barrier into Assemble, then Film.</p>
      </div>

      <div class="canvas">${build()}</div>

      <div class="legend">
        <div class="it"><span class="ring" style="border-color:var(--color-signal)"></span>active</div>
        <div class="it"><span class="ring" style="border-color:var(--color-teal)"></span>parallel agent</div>
        <div class="it"><span class="ring" style="border-color:var(--color-muted-2)"></span>waiting</div>
        <div class="it"><span class="sw" style="background:linear-gradient(90deg,var(--color-signal),var(--color-teal))"></span>fan-out</div>
        <div class="it"><span class="sw" style="background:linear-gradient(90deg,var(--color-teal),var(--color-amber))"></span>converge</div>
      </div>

      <div class="notes">
        <div class="note fan">
          <div class="n">Stage 1</div>
          <h3>Script splits the work <span class="tag t-fan">fan-out</span></h3>
          <p>One call turns prompt + setup into a scene list. The scene count — <b>5 to 12</b>, set by chosen length — becomes the fan-out width.</p>
        </div>
        <div class="note par">
          <div class="n">Stages 2–4 · ×N</div>
          <h3>Agents run concurrently <span class="tag t-par">parallel</span></h3>
          <p>Each scene gets an independent agent: Code → Voice → Validate. Lanes never block each other, and a failed scene <b>re-runs only its own lane</b>.</p>
        </div>
        <div class="note mrg">
          <div class="n">Stages 5–6</div>
          <h3>Everything converges <span class="tag t-mrg">barrier</span></h3>
          <p>Assemble waits until <b>every lane validates</b>, then a single track stitches the cut, bakes captions, and issues the signed URL.</p>
        </div>
      </div>
    `;
  }, []);

  return (
    <section className="relative z-10 w-full overflow-hidden bg-[var(--color-ink)] border-t border-b border-[var(--color-line)]">
      <style dangerouslySetInnerHTML={{ __html: styleContent }} />
      <div id="diagram-root" dangerouslySetInnerHTML={{ __html: htmlContent }} />
    </section>
  );
}
