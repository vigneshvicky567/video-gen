import { motion } from 'motion/react';

export function Footer() {
  return (
    <section className="bg-[var(--color-ink)] pb-12 px-6 relative overflow-hidden">
      <div className="max-w-[1500px] mx-auto bg-[var(--color-film)] border border-[var(--color-line)] rounded-[8px] p-8 md:p-16 flex flex-col lg:flex-row justify-between gap-16 relative z-10 shadow-[0_40px_120px_rgba(0,0,0,0.8)]">
         
         {/* Left col */}
         <div className="lg:w-[50%] flex flex-col justify-between z-10">
            <div className="flex gap-6 uppercase font-mono tracking-[0.1em] text-[10px] md:text-xs text-[var(--color-muted)]">
              <a href="#pipeline" className="hover:text-[var(--color-signal)] transition-colors">Pipeline</a>
              <a href="#god-mode" className="hover:text-[var(--color-signal)] transition-colors">Studio</a>
              <a href="#capabilities" className="hover:text-[var(--color-signal)] transition-colors">Capabilities</a>
            </div>

            <div className="mt-16 mb-20 relative">
               <h2 className="font-serif font-medium text-4xl md:text-[50px] tracking-tight leading-[0.95] text-[var(--color-paper)]">
                 System<br/>
                 compilation<br/>
                 targets.
               </h2>
               <p className="font-sans text-[15px] mt-6 text-[var(--color-muted)] leading-relaxed max-w-sm">Kinetic Studio is a conceptual generative rendering framework for cinematic visual ideas.</p>
            </div>

            <div className="flex items-center gap-4 text-[var(--color-muted)]">
              <span className="font-mono text-[10px] font-bold tracking-widest uppercase">System Repositories:</span>
              <a href="#" className="w-10 h-10 border border-[var(--color-line)] rounded-[4px] border-dashed flex items-center justify-center hover:bg-[var(--color-ink-2)] hover:border-[var(--color-signal)] hover:text-[var(--color-signal)] transition-colors font-mono hover:shadow-[0_0_12px_rgba(216,255,62,0.15)]">
                GH
              </a>
              <a href="#" className="w-10 h-10 border border-[var(--color-line)] rounded-[4px] border-dashed flex items-center justify-center hover:bg-[var(--color-ink-2)] hover:border-[var(--color-signal)] hover:text-[var(--color-signal)] transition-colors font-mono hover:shadow-[0_0_12px_rgba(216,255,62,0.15)]">
                X
              </a>
            </div>
         </div>

         {/* Right Col */}
         <div className="lg:w-[45%] flex flex-col justify-between z-10 p-8 rounded-[6px] bg-[var(--color-ink-2)] border border-[var(--color-line-soft)] relative overflow-hidden group">
            {/* Hover glow */}
            <div className="absolute top-0 right-0 w-64 h-64 bg-[var(--color-signal)]/10 blur-[80px] rounded-full pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity duration-700" />
            
            <div className="relative z-10">
               <h3 className="font-mono uppercase tracking-[0.2em] text-[var(--color-muted)] mb-8 text-[10px]">Kinetic Studio Subsystem API</h3>
               
               <div className="space-y-4 font-mono text-[11px] text-[var(--color-muted)]">
                 <div className="flex justify-between items-center border-b border-[var(--color-line)] pb-3 hover:text-[var(--color-signal)] transition-colors cursor-pointer group/link">
                   <span>GET /orchestrator/jobs</span>
                   <span className="opacity-0 -translate-x-2 group-hover/link:opacity-100 group-hover/link:translate-x-0 transition-all font-sans">→</span>
                 </div>
                 <div className="flex justify-between items-center border-b border-[var(--color-line)] pb-3 hover:text-[var(--color-signal)] transition-colors cursor-pointer group/link">
                   <span>POST /engine/compile</span>
                   <span className="opacity-0 -translate-x-2 group-hover/link:opacity-100 group-hover/link:translate-x-0 transition-all font-sans">→</span>
                 </div>
                 <div className="flex justify-between items-center border-b border-[var(--color-line)] pb-3 hover:text-[var(--color-signal)] transition-colors cursor-pointer group/link">
                   <span>GET /engine/job/{'{id}'}</span>
                   <span className="opacity-0 -translate-x-2 group-hover/link:opacity-100 group-hover/link:translate-x-0 transition-all font-sans">→</span>
                 </div>
                 <div className="flex justify-between items-center border-b border-[var(--color-line)] pb-3 hover:text-[var(--color-signal)] transition-colors cursor-pointer group/link">
                   <span>GET /stream/{'{id}'}/h264</span>
                   <span className="opacity-0 -translate-x-2 group-hover/link:opacity-100 group-hover/link:translate-x-0 transition-all font-sans">→</span>
                 </div>
               </div>
               
               <button className="bg-[var(--color-ink)] hover:bg-[var(--color-signal)] text-[var(--color-muted)] hover:text-[var(--color-ink)] font-sans font-semibold text-[13px] px-6 py-3 rounded-[4px] transition-all mt-10 block w-full text-center border border-[var(--color-line)] hover:border-[var(--color-signal)] hover:shadow-[0_0_16px_rgba(216,255,62,0.2)]">
                 Initialize Developer Docs
               </button>
            </div>

            <div className="flex flex-col justify-between items-start mt-12 gap-2 text-[var(--color-muted-2)] border-t border-[var(--color-line)] pt-6 relative z-10">
               <div>
                  <p className="font-mono text-[9px] uppercase tracking-widest">© KINETIC STUDIO. Orchestrating concept into film.</p>
               </div>
            </div>
         </div>
         
      </div>
    </section>
  );
}
