import { motion } from 'motion/react';
import { Camera, Cpu, Zap, Activity } from 'lucide-react';

const stats = [
  { icon: Camera, label: "FRAMES RENDERED", value: "1.2B+" },
  { icon: Cpu, label: "GPU CLUSTERS", value: "48+" },
  { icon: Zap, label: "AVG LATENCY", value: "<15ms" },
  { icon: Activity, label: "SYSTEM UPTIME", value: "99.9%" },
];

export function AboutPage() {
  return (
    <div className="w-full max-w-[1500px] mx-auto px-6 py-24 relative z-10 min-h-screen">
      <div className="flex flex-col lg:flex-row gap-20 items-center pt-12">
        <motion.div
           initial={{ opacity: 0, x: -20 }}
           animate={{ opacity: 1, x: 0 }}
           className="lg:w-1/2"
        >
          <h2 className="font-mono text-[10px] sm:text-[11px] text-[var(--color-muted)] uppercase tracking-[0.2em] mb-6 flex items-center gap-4">
            <span className="text-[var(--color-signal)]">04</span>
            ABOUT THE ENGINE
            <div className="h-px bg-[var(--color-line-soft)] flex-1" />
          </h2>
          <h1 className="text-[clamp(40px,5vw,60px)] font-serif font-medium text-[var(--color-paper)] tracking-tight mb-8 leading-[1.05]">
            Bridging the gap <br/><span className="italic text-[var(--color-signal)] pr-1">between</span> text and motion.
          </h1>
          <p className="text-[var(--color-muted)] text-[15px] sm:text-[17px] mb-12 leading-relaxed max-w-lg">
            REEL began as a research experiment in continuous generative video pipelines, mapping semantic instructions to coherent structural motion graphs. We believe the future of interfaces isn't static—it's cinematic.
          </p>
          <button className="bg-transparent border border-[var(--color-line)] text-[var(--color-paper)] hover:text-[var(--color-signal)] hover:border-[var(--color-signal)] hover:shadow-[0_4px_16px_rgba(216,255,62,0.1)] font-sans font-semibold text-sm px-6 py-3 rounded-[4px] transition-all duration-300">
            Read the Whitepaper
          </button>
        </motion.div>
        
        <motion.div
           initial={{ opacity: 0, x: 20 }}
           animate={{ opacity: 1, x: 0 }}
           className="lg:w-1/2 w-full grid grid-cols-2 gap-px bg-[var(--color-line-soft)] border border-[var(--color-line-soft)] rounded-[8px] overflow-hidden"
        >
           {stats.map((stat, i) => (
             <div key={i} className="bg-[var(--color-ink-2)] p-8 flex flex-col justify-between hover:bg-[var(--color-ink-3)] transition-colors h-40 relative group overflow-hidden">
                <div className="absolute top-0 right-0 w-32 h-32 bg-[var(--color-signal)]/5 blur-2xl rounded-full opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none" />
                <div className="text-[var(--color-signal)] relative z-10">
                  <stat.icon size={20} strokeWidth={1.5} />
                </div>
                <div className="relative z-10">
                   <div className="text-[28px] font-serif text-[var(--color-paper)] mb-2 leading-none">{stat.value}</div>
                   <div className="font-mono text-[9px] uppercase tracking-widest text-[var(--color-muted)]">{stat.label}</div>
                </div>
             </div>
           ))}
        </motion.div>
      </div>
    </div>
  );
}
