import { motion } from 'motion/react';

export function Hero({ onOpenStudio }: { onOpenStudio?: () => void }) {
  const marqueeItems = [
    { text: "How gradient descent finds minima", sym: "∮" },
    { text: "Why the Fourier transform works", sym: "Σ" },
    { text: "The geometry of eigenvectors", sym: "λ" },
    { text: "Bayes' theorem, visually", sym: "∂" },
    { text: "How neural networks learn", sym: "∇" },
    { text: "Euler's identity from first principles", sym: "π" },
    { text: "The central limit theorem in motion", sym: "μ" },
    { text: "What curvature actually measures", sym: "κ" }
  ];

  return (
    <section className="relative w-full max-w-[1500px] mx-auto px-6 pt-20 pb-20">
      <div className="absolute top-1/4 right-1/4 w-[60vw] h-[60vw] bg-[var(--color-signal)]/10 rounded-full blur-[200px] pointer-events-none" />

      {/* Headlines */}
      <div className="relative z-10 w-full pt-12 pb-16 flex flex-col lg:flex-row gap-12 lg:gap-24">
        
        <div className="lg:w-3/5 text-left">
          <h1 className="font-serif font-medium text-[clamp(44px,7vw,84px)] tracking-[-0.03em] leading-[0.95] text-[var(--color-paper)] mb-8">
            Where concepts become <span className="italic text-[var(--color-signal)] pr-2">understanding.</span>
          </h1>

          <p className="font-sans text-[15px] sm:text-[17px] text-[var(--color-muted)] max-w-xl leading-relaxed">
            Animated lessons created on demand for any topic.
          </p>

          <div className="flex items-center gap-4 mt-12">
            <button onClick={onOpenStudio} className="bg-[var(--color-signal)] text-[var(--color-ink)] font-sans font-semibold text-sm px-6 py-3 rounded-[10px] hover:scale-105 hover:shadow-[0_8px_24px_-4px_rgba(216,255,62,0.25)] transition-all">
              Summon the swarm
            </button>
            <a href="#pipeline" className="border border-[var(--color-line)] bg-transparent text-[var(--color-paper)] hover:text-[var(--color-signal)] hover:border-[var(--color-signal)] font-sans font-semibold text-sm px-6 py-3 rounded-[10px] transition-all">
              See how it works
            </a>
          </div>
        </div>

        {/* Stats Grid */}
        <div className="lg:w-2/5 grid grid-cols-2 gap-px bg-[var(--color-line-soft)] border border-[var(--color-line)] rounded-[8px] overflow-hidden self-start">
          {[
            { label: 'agents', value: '07' },
            { label: 'scenes / film', value: '~08' },
            { label: 'human input', value: '1 sentence' },
            { label: 'render target', value: '1080p · 30fps' }
          ].map((stat, i) => (
            <div key={i} className="bg-[var(--color-ink-2)] p-6 hover:bg-[var(--color-ink-3)] transition-colors">
              <div className="font-mono text-[10px] uppercase font-bold tracking-widest text-[var(--color-muted)] mb-3">{stat.label}</div>
              <div className="font-serif text-[26px] text-[var(--color-paper)] leading-none">{stat.value}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Marquee */}
      <div className="relative z-10 w-full overflow-hidden border-y border-[var(--color-line)] py-4 flex mt-8">
        <div className="absolute inset-y-0 left-0 w-24 bg-gradient-to-r from-[var(--color-ink)] to-transparent z-10" />
        <div className="absolute inset-y-0 right-0 w-24 bg-gradient-to-l from-[var(--color-ink)] to-transparent z-10" />
        
        <motion.div 
          className="flex gap-16 whitespace-nowrap items-center shrink-0"
          animate={{ x: [0, -1000] }}
          transition={{ duration: 30, repeat: Infinity, ease: 'linear' }}
        >
          {marqueeItems.concat(marqueeItems).map((item, i) => (
             <div key={i} className="flex items-center gap-4 font-mono text-sm tracking-widest text-[var(--color-muted-2)] uppercase">
               <span className="text-[var(--color-signal)]/60 text-lg">{item.sym}</span>
               {item.text}
             </div>
          ))}
        </motion.div>
      </div>

    </section>
  );
}
