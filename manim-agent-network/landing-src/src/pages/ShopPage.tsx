import { motion } from 'motion/react';
import { Package, Check, Zap } from 'lucide-react';

const products = [
  { id: 1, name: "Indie Creator", price: "$29", desc: "For independent filmmakers and hobbyists.", features: ["1,000 Compute Credits", "720p Render Quality", "Standard TTS Voices", "Community Support"] },
  { id: 2, name: "Studio Pro", price: "$99", desc: "For professional agencies and small teams.", features: ["5,000 Compute Credits", "1080p Render Quality", "Premium Neural TTS", "Priority Queue"] },
  { id: 3, name: "Enterprise API", price: "$499", desc: "High-volume generation for automated systems.", features: ["50,000 Compute Credits", "4K Render Quality", "Custom Voice Cloning", "Dedicated Account Manager"] },
];

export function ShopPage() {
  return (
    <div className="w-full max-w-[1500px] mx-auto px-6 py-24 relative z-10 min-h-screen">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="text-left mb-16 max-w-2xl"
      >
        <h2 className="font-mono text-[10px] sm:text-[11px] text-[var(--color-muted)] uppercase tracking-[0.2em] mb-4 flex items-center gap-4">
          <span className="text-[var(--color-signal)]">05</span>
          COMPUTE ALLOCATIONS
          <div className="h-px bg-[var(--color-line-soft)] flex-1" />
        </h2>
        <h1 className="text-[clamp(40px,5vw,60px)] font-serif font-medium text-[var(--color-paper)] tracking-tight mb-6 leading-[1.05]">
          Procure <span className="italic text-[var(--color-signal)]">Compute</span>
        </h1>
        <p className="text-[var(--color-muted)] text-[15px] sm:text-[17px] leading-relaxed">
          Acquire rendering credits for the generative engine. All plans include continuous updates and seamless API access.
        </p>
      </motion.div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {products.map((p, i) => (
          <motion.div
            key={p.id}
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            transition={{ delay: i * 0.1 }}
            viewport={{ once: true }}
            className="bg-[var(--color-ink-2)] border border-[var(--color-line)] rounded-[6px] p-8 hover:border-[var(--color-signal)] transition-all flex flex-col group relative overflow-hidden"
          >
            <div className="absolute top-0 right-0 w-64 h-64 bg-[var(--color-signal)]/5 blur-3xl rounded-full opacity-0 group-hover:opacity-100 transition-opacity duration-700 pointer-events-none" />
            
            <div className="relative z-10">
               <div className="flex items-center gap-3 mb-6 font-mono text-[11px] tracking-widest uppercase text-[var(--color-muted)]">
                 <Package size={16} className="text-[var(--color-signal)]" />
                 {p.name}
               </div>
               
               <div className="flex items-end gap-2 mb-4">
                 <span className="text-4xl font-serif text-[var(--color-paper)] leading-none">{p.price}</span>
                 <span className="text-[var(--color-muted)] font-mono text-[10px] uppercase tracking-widest pb-1">/ Month</span>
               </div>
               
               <p className="text-[var(--color-muted-2)] font-sans text-sm mb-8 h-10">
                 {p.desc}
               </p>

               <div className="w-full h-px bg-[var(--color-line-soft)] mb-8" />

               <ul className="flex flex-col gap-4 mb-10">
                  {p.features.map((f, j) => (
                     <li key={j} className="flex items-start gap-3 text-sm text-[var(--color-muted)] font-sans">
                        <Check size={16} className="text-[var(--color-signal)] shrink-0 mt-0.5" />
                        <span>{f}</span>
                     </li>
                  ))}
               </ul>
            </div>

            <button className="mt-auto w-full border border-[var(--color-line)] bg-[var(--color-ink)] text-[var(--color-paper)] hover:border-[var(--color-signal)] hover:text-[var(--color-signal)] hover:shadow-[0_4px_16px_rgba(216,255,62,0.1)] font-sans font-semibold text-sm px-6 py-3 rounded-[4px] transition-all relative z-10 flex items-center justify-center gap-2">
              <Zap size={16} /> Deploy Plan
            </button>
          </motion.div>
        ))}
      </div>
    </div>
  );
}
