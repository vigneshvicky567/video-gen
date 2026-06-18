import { motion } from 'motion/react';
import { Mail, MessageSquare, ShieldAlert } from 'lucide-react';

export function ContactPage() {
  return (
    <div className="w-full max-w-[1500px] mx-auto px-6 py-24 relative z-10 min-h-screen pt-32">
      <div className="flex flex-col lg:flex-row gap-16 max-w-6xl mx-auto">
        <motion.div
           initial={{ opacity: 0, x: -20 }}
           animate={{ opacity: 1, x: 0 }}
           className="w-full lg:w-1/3 flex flex-col gap-6"
        >
          <div className="mb-4">
             <h2 className="font-mono text-[10px] sm:text-[11px] text-[var(--color-muted)] uppercase tracking-[0.2em] mb-4">
               <span className="text-[var(--color-signal)] mr-4">06</span>
               ESTABLISH UPLINK
             </h2>
             <h1 className="text-4xl font-serif font-medium text-[var(--color-paper)] tracking-tight mb-4">
               Communications
             </h1>
             <p className="text-[var(--color-muted)] text-sm leading-relaxed">
               Open a dedicated channel with our engineering or support teams.
             </p>
          </div>

          <div className="bg-[var(--color-ink-2)] p-6 rounded-[6px] border border-[var(--color-line)] flex items-start gap-4 hover:border-[var(--color-signal)] transition-colors group">
            <div className="text-[var(--color-signal)] shrink-0 mt-1">
               <Mail size={18} />
            </div>
            <div>
              <h3 className="font-mono text-[10px] uppercase tracking-widest text-[var(--color-muted)] mb-1">Partnerships</h3>
              <p className="text-[var(--color-paper)] font-sans text-sm">hello@manim.network</p>
            </div>
          </div>
          <div className="bg-[var(--color-ink-2)] p-6 rounded-[6px] border border-[var(--color-line)] flex items-start gap-4 hover:border-[var(--color-signal)] transition-colors group">
            <div className="text-[var(--color-signal)] shrink-0 mt-1">
               <MessageSquare size={18} />
            </div>
            <div>
              <h3 className="font-mono text-[10px] uppercase tracking-widest text-[var(--color-muted)] mb-1">Developer Comm</h3>
              <p className="text-[var(--color-paper)] font-sans text-sm">Discord Terminal</p>
            </div>
          </div>
          <div className="bg-[var(--color-ink-2)] p-6 rounded-[6px] border border-[var(--color-line)] flex items-start gap-4 hover:border-[var(--color-signal)] transition-colors group">
            <div className="text-[var(--color-signal)] shrink-0 mt-1">
               <ShieldAlert size={18} />
            </div>
            <div>
              <h3 className="font-mono text-[10px] uppercase tracking-widest text-[var(--color-muted)] mb-1">System Status</h3>
              <p className="text-[var(--color-paper)] font-sans text-sm">All Systems Nominal</p>
            </div>
          </div>
        </motion.div>

        <motion.div
           initial={{ opacity: 0, x: 20 }}
           animate={{ opacity: 1, x: 0 }}
           className="w-full lg:w-2/3 bg-[var(--color-ink-2)] p-8 lg:p-12 rounded-[6px] border border-[var(--color-line)] relative overflow-hidden"
        >
           {/* ambient light */}
           <div className="absolute top-0 right-0 w-[500px] h-[500px] bg-[var(--color-signal)]/5 blur-[100px] rounded-full pointer-events-none -translate-y-1/2 translate-x-1/3" />
           
           <form className="flex flex-col gap-6 relative z-10" onSubmit={(e) => e.preventDefault()}>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                 <div className="flex flex-col gap-2">
                   <label className="font-mono text-[10px] uppercase tracking-widest text-[var(--color-muted)]">Identification</label>
                   <input type="text" className="bg-[var(--color-ink)] border border-[var(--color-line)] rounded-[4px] px-4 py-3 font-sans text-sm text-[var(--color-paper)] outline-none focus:border-[var(--color-signal)] focus:shadow-[0_0_12px_rgba(216,255,62,0.1)] transition-all placeholder:text-[var(--color-muted-2)]" placeholder="Name" />
                 </div>
                 <div className="flex flex-col gap-2">
                   <label className="font-mono text-[10px] uppercase tracking-widest text-[var(--color-muted)]">Vector</label>
                   <input type="email" className="bg-[var(--color-ink)] border border-[var(--color-line)] rounded-[4px] px-4 py-3 font-sans text-sm text-[var(--color-paper)] outline-none focus:border-[var(--color-signal)] focus:shadow-[0_0_12px_rgba(216,255,62,0.1)] transition-all placeholder:text-[var(--color-muted-2)]" placeholder="Email Address" />
                 </div>
              </div>
              <div className="flex flex-col gap-2">
                <label className="font-mono text-[10px] uppercase tracking-widest text-[var(--color-muted)]">Payload</label>
                <textarea rows={6} className="bg-[var(--color-ink)] border border-[var(--color-line)] rounded-[4px] px-4 py-3 font-sans text-sm text-[var(--color-paper)] outline-none focus:border-[var(--color-signal)] focus:shadow-[0_0_12px_rgba(216,255,62,0.1)] transition-all resize-none placeholder:text-[var(--color-muted-2)]" placeholder="Transmit your inquiry..." />
              </div>
              <button type="submit" className="mt-4 border border-[var(--color-line)] bg-[var(--color-ink)] text-[var(--color-paper)] hover:text-[var(--color-signal)] hover:border-[var(--color-signal)] font-sans font-semibold text-sm px-6 py-4 rounded-[4px] transition-all hover:shadow-[0_4px_16px_rgba(216,255,62,0.1)] w-full sm:w-auto self-start">
                 Initiate Transfer
              </button>
           </form>
        </motion.div>
      </div>
    </div>
  );
}
