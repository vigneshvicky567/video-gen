import { useState, useEffect } from 'react';
import { Link, useLocation } from 'react-router-dom';

export function Navbar({ onOpenStudio }: { onOpenStudio?: () => void }) {
  const [time, setTime] = useState(new Date());
  const location = useLocation();

  useEffect(() => {
    const timer = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const navLinks = [
    { name: 'Home', path: '/' },
    { name: 'Features', path: '/features' },
    { name: 'About', path: '/about' },
    { name: 'Contact', path: '/contact' }
  ];

  return (
    <nav className="sticky top-0 z-50 w-full backdrop-blur-[16px] bg-[var(--color-ink-2)]/80 border-b border-[var(--color-line-soft)] px-6 py-3 flex items-center justify-between">
      <div className="flex items-center gap-6">
        <Link to="/" className="font-serif font-medium text-xl tracking-tight text-[var(--color-paper)] flex items-center gap-2">
          <span className="font-sans font-bold">Kinetic</span>&nbsp;<span className="italic text-[var(--color-signal)] pr-0.5">Studio</span>
        </Link>
        <div className="hidden lg:flex font-mono text-[10px] uppercase tracking-[0.2em] text-[var(--color-muted)]">
          Multi-agent video synthesis
        </div>
      </div>

      <div className="hidden md:flex items-center bg-[var(--color-ink-3)] p-1 rounded-full border border-[var(--color-line-soft)]">
        {navLinks.map(link => (
          <Link
            key={link.path}
            to={link.path}
            className={`px-5 py-1.5 rounded-[30px] font-sans text-[13px] font-medium transition-colors ${location.pathname === link.path ? 'text-[var(--color-paper)] bg-[var(--color-ink-2)] shadow-sm' : 'text-[var(--color-muted)] hover:text-[var(--color-paper)]'}`}
          >
            {link.name}
          </Link>
        ))}
      </div>

      <div className="flex items-center gap-6">
        <div className="hidden xl:flex items-center gap-4">
          <div className="flex gap-1.5">
            <span className="w-[5px] h-[5px] rounded-full bg-[var(--color-teal)] opacity-80 animate-pulse" />
            <span className="w-[5px] h-[5px] rounded-full bg-[var(--color-amber)] opacity-40" />
            <span className="w-[5px] h-[5px] rounded-full bg-[var(--color-rose)] opacity-40" />
          </div>
          <div className="font-mono text-[10px] text-[var(--color-muted)] uppercase tracking-widest w-[65px]">
            {time.toISOString().split('T')[1].slice(0, 8)}
          </div>
        </div>

        <button 
          onClick={onOpenStudio} 
          className="border border-[var(--color-line)] bg-[var(--color-ink)] text-[var(--color-paper)] hover:text-[var(--color-ink)] hover:bg-[var(--color-signal)] hover:border-[var(--color-signal)] font-sans font-semibold text-sm px-5 py-1.5 rounded-[7px] transition-all duration-200"
        >
          Open Studio
        </button>
      </div>
    </nav>
  );
}

