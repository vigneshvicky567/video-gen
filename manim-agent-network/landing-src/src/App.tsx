import { useEffect } from 'react';
import { Routes, Route, useLocation } from 'react-router-dom';
import { Navbar } from './components/Navbar';
import { Footer } from './components/Footer';

// Pages
import { HomePage } from './pages/HomePage';
import { FeaturesPage } from './pages/FeaturesPage';
import { AboutPage } from './pages/AboutPage';
import { ContactPage } from './pages/ContactPage';

function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);
  return null;
}

export default function App() {
  // The real, backend-wired control room lives at /studio.html (the REEL SPA).
  // exactpage is the landing page, so its CTAs hand off to that tool.
  const openStudio = () => { window.location.href = '/studio.html'; };

  return (
    <div className="min-h-screen bg-[var(--color-ink)] text-[var(--color-paper)] selection:bg-[var(--color-signal)] selection:text-[var(--color-ink)] flex flex-col font-sans relative overflow-x-hidden">
      <ScrollToTop />
      {/* Global Ambient Animations */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden z-0">
         {/* Faint lime glow top right */}
         <div className="absolute top-0 right-0 w-[800px] h-[800px] bg-[var(--color-signal)]/5 rounded-full blur-[150px] -translate-y-1/2 translate-x-1/3" />
      </div>

      <div className="relative z-10 flex flex-col min-h-screen">
        <Navbar onOpenStudio={openStudio} />

        <main className="flex-1">
          <Routes>
            <Route path="/" element={<HomePage onOpenStudio={openStudio} />} />
            <Route path="/features" element={<FeaturesPage />} />
            <Route path="/about" element={<AboutPage />} />
            <Route path="/contact" element={<ContactPage />} />
          </Routes>
        </main>

        <Footer />
      </div>
    </div>
  );
}

