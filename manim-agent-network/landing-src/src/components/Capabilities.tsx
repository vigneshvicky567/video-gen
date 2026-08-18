import React, { useState } from 'react';
import { ChevronDown } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';

export function Capabilities() {
  const faqs = [
    { q: "Built for complex architectures", a: "Transform abstract technical and mathematical schemas into intuitive multidimensional visual structures." },
    { q: "Execution in motion", a: "Observe mathematics, physics, computing, and multidimensional logic execute step by step visually." },
    { q: "Resilient compilation", a: "Automatically recovers from interruptions to maintain stream continuity and compilation targets." },
    { q: "High-fidelity rendering", a: "Outputs ultra-smooth 60fps animations, synchronized TTS voice, robust typography, and H264 high-definition streams." },
    { q: "Instant compilation", a: "Iterate and re-compile entirely new outputs from adjusted prompt vectors in mere moments." },
  ];

  return (
    <section id="capabilities" className="py-24 relative overflow-hidden">
      <div className="max-w-[1500px] mx-auto px-6">
        
        {/* Header */}
        <h2 className="font-mono text-[10px] sm:text-[11px] text-[var(--color-muted)] uppercase tracking-[0.2em] mb-4 flex items-center gap-4">
          <span className="text-[var(--color-signal)]">03</span>
          SYSTEM CAPABILITIES
          <div className="h-px bg-[var(--color-line-soft)] flex-1" />
        </h2>

        <div className="flex flex-col md:flex-row gap-16 relative z-10 mt-12">
          
          <div className="md:w-1/3 relative">
            <h2 className="font-serif font-medium text-4xl md:text-[50px] tracking-tight leading-[0.95] text-[var(--color-paper)]">
              Intelligent<br />
              <span className="italic text-[var(--color-signal)] pr-1">generation</span><br />
              framework.
            </h2>
          </div>

          {/* Accordions */}
          <div className="md:w-2/3">
            <div className="border-t border-[var(--color-line-soft)]">
              {faqs.map((faq, i) => (
                <AccordionItem key={i} question={faq.q} answer={faq.a} />
              ))}
            </div>
          </div>

        </div>
      </div>
    </section>
  );
}

function AccordionItem({ question, answer }: { question: string, answer: string, key?: React.Key }) {
  const [isOpen, setIsOpen] = useState(false);

  return (
     <div className="border-b border-[var(--color-line-soft)] relative bg-[var(--color-ink)] hover:bg-[var(--color-ink-2)] transition-colors">
        <button 
          onClick={() => setIsOpen(!isOpen)}
          className="w-full py-6 pr-4 flex items-center justify-between text-left group"
        >
           <span className="font-sans text-xl font-medium tracking-tight text-[var(--color-paper)] group-hover:text-[var(--color-signal)] transition-colors">{question}</span>
           <span className="w-8 shrink-0 flex items-center justify-end">
             <ChevronDown size={20} className={`transition-transform duration-300 text-[var(--color-muted)] group-hover:text-[var(--color-signal)] ${isOpen ? 'rotate-180 text-[var(--color-signal)]' : ''}`} />
           </span>
        </button>
        <AnimatePresence>
          {isOpen && (
             <motion.div 
               initial={{ height: 0, opacity: 0 }}
               animate={{ height: "auto", opacity: 1 }}
               exit={{ height: 0, opacity: 0 }}
               className="overflow-hidden"
             >
                <div className="pb-8 pt-2 text-[var(--color-muted)] font-sans leading-relaxed text-[15px] max-w-2xl border-l border-[var(--color-signal)]/30 ml-2 pl-6">
                  {answer}
                </div>
             </motion.div>
          )}
        </AnimatePresence>
     </div>
  );
}
