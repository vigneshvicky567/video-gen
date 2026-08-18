export function Pipeline() {
  const agents = [
    { title: "Script Writer", port: ":8001", desc: "Turns your sentence into a structured screenplay — scene by scene, with narration, visual direction, and timing." },
    { title: "Code Generator", port: ":8002", desc: "Writes real Manim Python for every scene in parallel, with API-key pooling to survive rate limits." },
    { title: "Validator", port: ":8003", desc: "Renders each scene in a sandbox, catches every NameError and API drift, and sends bad code back with the stack trace." },
    { title: "Voiceover", port: ":8004", desc: "Narrates every scene with Kokoro neural TTS — with an espeak fallback so a film never ships silent." },
    { title: "Image Fetcher", port: ":8006", desc: "Pulls supporting visuals when a scene calls for the real world instead of pure mathematics." },
    { title: "Compositor", port: ":8005", desc: "Aligns audio to animation, burns native captions, and cuts the scenes into one seamless film." },
    { title: "Orchestrator", port: ":8010", desc: "The conductor. A LangGraph state machine that routes work, counts retries, and never loses a job — even through a restart." },
  ];

  return (
    <section id="pipeline" className="py-24 relative z-20">
      <div className="max-w-[1500px] mx-auto px-6">
        <h2 className="font-mono text-[10px] sm:text-[11px] text-[var(--color-muted)] uppercase tracking-[0.2em] mb-4 flex items-center gap-4">
          <span className="text-[var(--color-signal)]">01</span>
          THE PIPELINE
          <div className="h-px bg-[var(--color-line-soft)] flex-1" />
        </h2>
        
        <div className="mb-16 max-w-2xl mt-12 text-left">
          <h3 className="font-serif text-3xl md:text-4xl text-[var(--color-paper)] tracking-tight mb-8 leading-snug">
            A self-healing swarm of seven AI agents writes the script, generates the mathematics, renders every scene, records the narration, and cuts the final film — while you watch it happen.
          </h3>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-px bg-[var(--color-line-soft)] border border-[var(--color-line)] rounded-[8px] overflow-hidden">
           {agents.map((agent, i) => (
             <div key={i} className="bg-[var(--color-ink-2)] p-8 flex flex-col hover:bg-[var(--color-ink-3)] transition-colors group relative overflow-hidden min-h-[220px]">
               <div className="absolute top-0 right-0 w-32 h-32 bg-[var(--color-signal)]/5 blur-2xl rounded-full opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none" />
               
               <div className="flex justify-between items-start mb-6">
                 <div className="font-serif text-2xl text-[var(--color-paper)]">0{i+1}</div>
                 <div className="font-mono text-[10px] text-[var(--color-muted-2)] px-2 py-1 border border-[var(--color-line)] rounded bg-[var(--color-ink)]">
                   {agent.title.toLowerCase().replace(' ', '-')} {agent.port}
                 </div>
               </div>
               
               <h4 className="font-sans font-bold text-lg text-[var(--color-paper)] mb-3">{agent.title}</h4>
               <p className="font-sans text-[13px] text-[var(--color-muted)] leading-relaxed flex-1">
                 {agent.desc}
               </p>
             </div>
           ))}
           <div className="hidden xl:block bg-[var(--color-ink-2)] bg-[radial-gradient(ellipse_at_center,rgba(216,255,62,0.05)_0%,transparent_70%)] relative flex items-center justify-center pointer-events-none">
             <div className="font-mono text-[10px] uppercase text-[var(--color-signal)]/40 tracking-widest border border-[var(--color-signal)]/10 px-4 py-2 rounded-full">
               System Ready
             </div>
           </div>
        </div>
      </div>
    </section>
  );
}
