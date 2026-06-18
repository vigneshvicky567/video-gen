import React, { useState, useEffect } from 'react';
import { X, Play, Loader2, Disc, Box, Check } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';

type Stage = 'idle' | 'parsing' | 'storyboard' | 'generating' | 'audio' | 'finalizing' | 'done';

export function Studio({ onClose }: { onClose: () => void }) {
  const [topic, setTopic] = useState('');
  const [stage, setStage] = useState<Stage>('idle');
  const [sceneProgress, setSceneProgress] = useState(0);

  useEffect(() => {
    if (stage === 'idle' || stage === 'done') return;

    let timer: NodeJS.Timeout;

    const advance = (nextStage: Stage, delay: number) => {
      timer = setTimeout(() => setStage(nextStage), delay);
    };

    switch (stage) {
      case 'parsing':
        advance('storyboard', 2000);
        break;
      case 'storyboard':
        advance('generating', 2500);
        break;
      case 'generating':
        // Scene progress simulation
        const interval = setInterval(() => {
          setSceneProgress(p => {
            if (p >= 8) {
              clearInterval(interval);
              setStage('audio');
              return 8;
            }
            return p + 1;
          });
        }, 800);
        return () => clearInterval(interval);
      case 'audio':
        advance('finalizing', 2000);
        break;
      case 'finalizing':
        advance('done', 3000);
        break;
    }

    return () => clearTimeout(timer);
  }, [stage]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!topic.trim()) return;
    setStage('parsing');
    setSceneProgress(1);
  };

  const getStatus = (currentStageId: Stage) => {
    const order: Stage[] = ['idle', 'parsing', 'storyboard', 'generating', 'audio', 'finalizing', 'done'];
    const currentIndex = order.indexOf(currentStageId);
    const stageIndex = order.indexOf(stage);

    if (stage === 'idle') return 'pending';
    if (stageIndex > currentIndex) return 'complete';
    if (stageIndex === currentIndex) return 'active';
    return 'pending';
  };

  const stages: {id: Stage, label: string}[] = [
    { id: 'parsing', label: 'Parse Topic' },
    { id: 'storyboard', label: 'Storyboard' },
    { id: 'generating', label: 'Render Scenes' },
    { id: 'audio', label: 'Audio Synth' },
    { id: 'finalizing', label: 'Composite' },
  ];

  return (
    <motion.div 
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.98 }}
      transition={{ type: "spring", damping: 25, stiffness: 200 }}
      className="fixed inset-0 z-50 bg-[var(--color-ink)]/90 backdrop-blur-md flex flex-col font-sans text-[var(--color-paper)] p-0 sm:p-4 md:p-8"
    >
      <div className="bg-[var(--color-film)] border border-[var(--color-line)] rounded-[8px] h-full flex flex-col overflow-hidden shadow-[0_40px_120px_rgba(0,0,0,0.8)] relative ring-1 ring-white/5">
        
        {/* Header Marquee */}
        <header className="border-b border-[var(--color-line)] bg-[var(--color-ink-2)] flex items-center justify-between px-6 py-4 shrink-0 relative z-30">
          <div className="flex items-center gap-6">
            <div className="font-serif font-medium text-2xl tracking-tight text-[var(--color-paper)] flex items-center">
               RE<span className="italic text-[var(--color-signal)]">E</span>L<span className="font-sans font-light tracking-widest text-[var(--color-muted)] text-[11px] uppercase ml-4">Studio</span>
            </div>
            {stage !== 'idle' && stage !== 'done' && (
              <div className="hidden md:flex font-mono text-[10px] uppercase font-bold tracking-widest text-[var(--color-signal)] items-center gap-2">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-signal)] animate-pulse" />
                Processing
              </div>
            )}
          </div>
          <button onClick={onClose} className="text-[var(--color-muted)] hover:text-[var(--color-signal)] transition-colors">
            <X size={24} strokeWidth={1} />
          </button>
        </header>

        <div className="flex-1 flex flex-col lg:flex-row overflow-hidden relative">
          
          {/* Left Panel - Composer */}
          <div className="w-full lg:w-[480px] border-b lg:border-b-0 lg:border-r border-[var(--color-line)] bg-[var(--color-ink-2)] flex flex-col shrink-0">
             
             {/* Prompt Input */}
             <div className="p-6 md:p-8 border-b border-[var(--color-line)] bg-[var(--color-ink)]">
                <label className="block font-mono text-[10px] uppercase tracking-widest text-[var(--color-muted)] mb-4">Prompt Sequence</label>
                <form onSubmit={handleSubmit} className="flex flex-col gap-4">
                  <textarea 
                     value={topic}
                     onChange={e=>setTopic(e.target.value)}
                     disabled={stage !== 'idle'}
                     placeholder="Euler's identity from first principles..."
                     className="w-full bg-[var(--color-film)] border border-[var(--color-line-soft)] rounded-[4px] p-5 font-sans text-base text-[var(--color-paper)] focus:outline-none focus:border-[var(--color-signal)] focus:shadow-[0_0_12px_rgba(216,255,62,0.1)] resize-none h-32 disabled:opacity-50 transition-all placeholder:text-[var(--color-muted-2)] font-medium"
                  />
                  <div className="flex justify-between items-center mt-2">
                    <span className="font-mono text-[10px] text-[var(--color-muted-2)] uppercase">{topic.length} Chars</span>
                    <button 
                       type="submit"
                       disabled={stage !== 'idle' || !topic.trim()}
                       className="bg-[var(--color-signal-dim)] hover:bg-[var(--color-signal)] text-[var(--color-ink)] font-sans font-semibold text-sm px-6 py-2.5 rounded-[4px] disabled:opacity-50 transition-all flex items-center justify-center min-w-[140px]"
                    >
                       {stage === 'idle' ? 'Summon the swarm' : 'Running...'}
                    </button>
                  </div>
                </form>
             </div>

             {/* Execution Tree */}
             <div className="flex-1 p-6 md:p-8 overflow-y-auto bg-[var(--color-ink-2)] custom-scrollbar">
                <div className="font-mono text-[10px] uppercase tracking-widest text-[var(--color-muted)] mb-8">Pipeline Trace</div>
                
                <div className="pl-2 border-l border-[var(--color-line)] ml-2 flex flex-col gap-6 relative">
                   {stages.map((s, index) => {
                     const status = getStatus(s.id);
                     const isActive = status === 'active';
                     const isComplete = status === 'complete';
                     
                     return (
                       <div key={s.id} className="pl-6 relative">
                          <div className={`absolute -left-[5px] top-1.5 w-[9px] h-[9px] rounded-full border border-[var(--color-ink-2)] flex items-center justify-center
                            ${isActive ? 'bg-[var(--color-signal)] shadow-[0_0_8px_rgba(216,255,62,0.5)]' : isComplete ? 'bg-[var(--color-teal)]' : 'bg-[var(--color-line)]'}
                          `}>
                            {isActive && <div className="absolute inset-0 rounded-full bg-[var(--color-signal)] animate-ping" />}
                          </div>

                          <div className={`font-mono text-[11px] font-medium tracking-widest uppercase mb-1
                            ${isActive ? 'text-[var(--color-signal)]' : isComplete ? 'text-[var(--color-teal)]' : 'text-[var(--color-muted)]'}
                          `}>
                            {s.label}
                          </div>
                          
                          {/* Details */}
                          <div className="text-[13px] text-[var(--color-muted-2)] font-sans mt-2 min-h-[1.5rem]">
                            {isActive && s.id === 'parsing' && <span>Analyzing semantic structures...</span>}
                            {isActive && s.id === 'storyboard' && <span>Plotting 8 structural keyframes...</span>}
                            {isActive && s.id === 'generating' && <span className="text-[var(--color-paper)]">Rendering frame {sceneProgress} / 8...</span>}
                            {isActive && s.id === 'audio' && <span>Synthesizing voice tracks...</span>}
                            {isActive && s.id === 'finalizing' && <span>Multiplexing streams...</span>}
                            {isComplete && <span className="text-[var(--color-muted)] flex items-center gap-1"><Check size={12}/> Done</span>}
                          </div>
                       </div>
                     );
                   })}
                </div>
             </div>

          </div>

          {/* Right Panel - Viewport */}
          <div className="flex-1 bg-[var(--color-ink)] p-4 md:p-8 flex flex-col items-center justify-center relative overflow-hidden">
             
             {/* Stage */}
             <div className="w-full max-w-4xl aspect-[21/9] bg-[var(--color-ink-2)] rounded-[4px] border border-[var(--color-line)] relative flex items-center justify-center overflow-hidden shadow-[0_0_40px_rgba(0,0,0,0.5)]">
                
                {/* Backlight glow */}
                {stage !== 'idle' && stage !== 'done' && (
                  <div className={`absolute inset-0 bg-[var(--color-signal)]/5 blur-3xl pointer-events-none transition-opacity duration-1000`} />
                )}

                <AnimatePresence mode="wait">
                   {stage === 'idle' && (
                      <motion.div key="idle" initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}} className="flex flex-col items-center">
                         <div className="w-16 h-16 border border-[var(--color-line)] rounded-full flex items-center justify-center mb-6">
                           <Box size={24} className="text-[var(--color-muted)]" strokeWidth={1} />
                         </div>
                         <div className="font-mono text-[11px] text-[var(--color-muted)] uppercase tracking-widest">Type a topic.</div>
                      </motion.div>
                   )}

                   {stage === 'parsing' && (
                      <motion.div key="parsing" initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}} className="flex flex-col items-center">
                         <Loader2 size={32} className="animate-spin text-[var(--color-muted)] mb-4" strokeWidth={1.5} />
                         <div className="font-mono text-[10px] text-[var(--color-muted)] uppercase tracking-widest">Parsing Vector</div>
                      </motion.div>
                   )}

                   {stage === 'generating' && (
                      <motion.div key="generating" initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}} className="flex flex-col items-center w-full px-12">
                         <div className="font-mono text-[54px] text-[var(--color-signal)] font-light mb-2">{sceneProgress}</div>
                         <div className="font-mono text-[10px] text-[var(--color-muted)] uppercase tracking-widest mb-8">Frames Rendered</div>
                         
                         {/* Scrub bar styling */}
                         <div className="w-full max-w-md h-[2px] bg-[var(--color-film)] relative overflow-hidden">
                            <motion.div 
                               className="absolute top-0 left-0 bottom-0 bg-[var(--color-signal)] shadow-[0_0_8px_rgba(216,255,62,0.8)]"
                               initial={{ width: 0 }}
                               animate={{ width: `${(sceneProgress/8)*100}%` }}
                            />
                         </div>
                      </motion.div>
                   )}

                   {(stage === 'storyboard' || stage === 'audio' || stage === 'finalizing') && (
                      <motion.div key="middle" initial={{opacity:0}} animate={{opacity:1}} exit={{opacity:0}} className="flex flex-col items-center">
                         <Disc size={40} className="animate-spin text-[var(--color-muted)] mb-6 opacity-30" strokeWidth={1} style={{ animationDuration: '3s' }} />
                         <div className="font-mono text-[10px] text-[var(--color-muted)] uppercase tracking-[0.2em]">{stage}</div>
                      </motion.div>
                   )}

                   {stage === 'done' && (
                      <motion.div key="done" initial={{scale:0.95, opacity:0}} animate={{scale:1, opacity:1}} className="w-full h-full relative cursor-pointer group bg-[url('https://images.unsplash.com/photo-1440407876336-62333a6f010f?q=80&w=2074&auto=format&fit=crop')] bg-cover bg-center">
                         <div className="absolute inset-0 bg-black/40 backdrop-blur-[2px] group-hover:backdrop-blur-0 transition-all duration-700" />
                         
                         <div className="absolute inset-0 flex items-center justify-center">
                            <div className="w-20 h-20 rounded-full bg-[var(--color-signal)] flex items-center justify-center text-[var(--color-ink)] shadow-[0_0_30px_rgba(216,255,62,0.4)] group-hover:scale-105 transition-transform duration-300">
                               <Play fill="currentColor" size={28} className="ml-2" />
                            </div>
                         </div>
                         
                         <div className="absolute bottom-6 left-0 right-0 flex justify-center z-10 pointer-events-none">
                            <div className="bg-[var(--color-ink)]/80 backdrop-blur px-4 py-1.5 border border-[var(--color-line)] rounded font-mono text-[10px] text-[var(--color-paper)] uppercase tracking-widest">
                               Receive a film.
                            </div>
                         </div>
                      </motion.div>
                   )}
                </AnimatePresence>
             </div>

             {/* Footer metadata */}
             <div className="absolute bottom-6 right-8 font-mono text-[10px] text-[var(--color-muted-2)] uppercase tracking-widest hidden md:flex items-center gap-4">
                <span>Viewport: 21:9</span>
                <span>Bitrate: Variable</span>
             </div>

          </div>
        </div>
      </div>
    </motion.div>
  );
}
