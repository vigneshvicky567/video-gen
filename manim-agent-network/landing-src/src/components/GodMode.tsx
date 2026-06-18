import { motion } from 'motion/react';
import { Terminal } from 'lucide-react';

export function GodMode({ onOpenStudio }: { onOpenStudio?: () => void }) {
  const logs = [
    { type: 'info', agent: 'orchestrator', msg: 'Job started. Expanding prompt into 8 scenes.' },
    { type: 'ok', agent: 'script', msg: 'Screenplay parsed. Dispatching tasks.' },
    { type: 'ok', agent: 'code', msg: 'scene_4 render ok · 1080p · 14.2s' },
    { type: 'warn', agent: 'code', msg: 'scene_7 retry 1 — NameError healed' },
    { type: 'info', agent: 'voice', msg: 'kokoro af_sarah warming…' },
    { type: 'ok', agent: 'validate', msg: 'scene_7 validation passed after retry.' },
  ];

  return (
    <section id="god-mode" className="relative w-full py-24 z-10 overflow-hidden">
      <div className="max-w-[1500px] mx-auto px-6 mb-12 text-left">
        <h2 className="font-mono text-[10px] sm:text-[11px] text-[var(--color-muted)] uppercase tracking-[0.2em] mb-4 flex items-center gap-4">
          <span className="text-[var(--color-signal)]">03</span>
          GOD MODE
          <div className="h-px bg-[var(--color-line-soft)] flex-1" />
        </h2>
        
        <h3 className="font-serif font-medium text-4xl sm:text-[50px] text-[var(--color-paper)] tracking-tight leading-[1] mb-6">
          Watch the swarm <span className="italic text-[var(--color-signal)] pr-2">think.</span>
        </h3>
        
        <div className="flex flex-col md:flex-row md:items-end justify-between gap-8">
           <p className="text-[var(--color-muted)] text-[15px] max-w-xl leading-relaxed">
             The Studio is a live control room: every agent's heartbeat, every scene's status, every retry — streaming in real time from the pipeline.
           </p>
           
           <button onClick={onOpenStudio} className="bg-transparent border border-[var(--color-line)] text-[var(--color-paper)] hover:text-[var(--color-ink)] hover:bg-[var(--color-signal)] hover:border-[var(--color-signal)] font-sans font-semibold text-sm px-6 py-3 rounded-[4px] transition-all flex items-center gap-2 w-fit">
             <Terminal size={16} /> Enter God Mode
           </button>
        </div>
      </div>

      {/* Terminal Preview */}
      <div className="max-w-[1500px] mx-auto px-6">
         <div className="w-full bg-[var(--color-ink-2)] border border-[var(--color-line)] rounded-[6px] overflow-hidden shadow-[0_40px_100px_rgba(0,0,0,0.6)] font-mono text-[11px] sm:text-[13px]">
            {/* Terminal Header */}
            <div className="bg-[var(--color-ink)] border-b border-[var(--color-line)] px-4 py-3 flex items-center justify-between">
               <div className="flex gap-2">
                 <div className="w-3 h-3 rounded-full bg-[var(--color-line)]" />
                 <div className="w-3 h-3 rounded-full bg-[var(--color-line)]" />
                 <div className="w-3 h-3 rounded-full bg-[var(--color-line)]" />
               </div>
               <div className="text-[var(--color-muted)] tracking-widest uppercase text-[10px]">studio — manim agent network</div>
               <div className="w-10"></div>
            </div>

            {/* Terminal Body splits into list of jobs and logs */}
            <div className="flex flex-col md:flex-row h-[350px]">
               {/* Left sidebar jobs */}
               <div className="w-full md:w-[30%] border-b md:border-b-0 md:border-r border-[var(--color-line)] p-4 flex flex-col gap-1 overflow-y-auto bg-[var(--color-ink-3)]/50">
                  <div className="text-[var(--color-muted)] uppercase tracking-widest text-[9px] mb-2 px-2">Active Generations</div>
                  
                  <div className="px-3 py-2 rounded-[4px] border border-[var(--color-line-soft)] flex justify-between items-center bg-[var(--color-ink-2)]">
                     <span className="text-[var(--color-paper)] truncate">how gradient descent finds minima</span>
                     <span className="text-[var(--color-teal)] shrink-0 ml-2">completed</span>
                  </div>
                  
                  <div className="px-3 py-2 rounded-[4px] border border-[var(--color-signal)]/30 bg-[var(--color-signal)]/5 flex justify-between items-center text-[var(--color-signal)]">
                     <span className="truncate">fourier intuition</span>
                     <span className="shrink-0 ml-2 flex items-center gap-2"><span className="w-1.5 h-1.5 rounded-full bg-[var(--color-signal)] animate-pulse" /> rendering</span>
                  </div>

                  <div className="px-3 py-2 rounded-[4px] border border-[var(--color-line-soft)] flex justify-between items-center bg-[var(--color-ink-2)] opacity-50">
                     <span className="text-[var(--color-paper)] truncate">bayes theorem</span>
                     <span className="text-[var(--color-teal)] shrink-0 ml-2">completed</span>
                  </div>
               </div>

               {/* Right main log */}
               <div className="w-full md:w-[70%] p-4 sm:p-6 overflow-y-auto flex flex-col gap-2">
                  <div className="flex gap-4 mb-4 text-[9px] uppercase tracking-widest text-[var(--color-muted)]">
                    <span className="text-[var(--color-signal)]">script</span>
                    <span className="text-[var(--color-signal)]">code</span>
                    <span className="text-[var(--color-signal)]">validate</span>
                    <span className="text-[var(--color-signal)]">voice</span>
                    <span className="text-[var(--color-muted)]">assemble</span>
                  </div>
                  
                  {logs.map((log, i) => (
                    <div key={i} className="flex gap-4 items-start font-mono">
                       <span className="text-[var(--color-muted-2)] shrink-0 w-[45px] text-right">0:0{i+1}</span>
                       <span className={`px-2 py-0.5 rounded-[3px] border uppercase text-[9px] tracking-widest w-[100px] text-center shrink-0
                         ${log.agent === 'orchestrator' ? 'text-white border-white/20' : ''}
                         ${log.agent === 'script' ? 'text-[#C9A3FF] border-[#C9A3FF]/20' : ''}
                         ${log.agent === 'code' ? 'text-[var(--color-signal)] border-[var(--color-signal)]/20' : ''}
                         ${log.agent === 'validate' ? 'text-[var(--color-teal)] border-[var(--color-teal)]/20' : ''}
                         ${log.agent === 'voice' ? 'text-[var(--color-amber)] border-[var(--color-amber)]/20' : ''}
                       `}>
                         {log.agent}
                       </span>
                       <span className={`
                         ${log.type === 'ok' ? 'text-[var(--color-teal)]' : ''}
                         ${log.type === 'warn' ? 'text-[var(--color-amber)]' : ''}
                         ${log.type === 'info' ? 'text-[var(--color-paper)]' : ''}
                       `}>
                         {log.msg}
                       </span>
                    </div>
                  ))}
                  <div className="flex gap-4 items-start font-mono mt-2 animate-pulse">
                     <span className="text-[var(--color-muted-2)] shrink-0 w-[45px] text-right">0:07</span>
                     <span className="px-2 py-0.5 rounded-[3px] border uppercase text-[9px] tracking-widest w-[100px] text-center shrink-0 text-[var(--color-signal)] border-[var(--color-signal)]/20">
                       code
                     </span>
                     <span className="text-[var(--color-paper)]">
                       rendering scene_5... <span className="text-[var(--color-signal)]">_</span>
                     </span>
                  </div>
               </div>
            </div>
         </div>
      </div>
    </section>
  );
}
