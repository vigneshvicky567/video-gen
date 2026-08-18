import { Hero } from '../components/Hero';
import { GodMode } from '../components/GodMode';
import { Architecture } from '../components/Architecture';

export function HomePage({ onOpenStudio }: { onOpenStudio: () => void }) {
  return (
    <>
      <Hero onOpenStudio={onOpenStudio} />
      <Architecture />
      <GodMode onOpenStudio={onOpenStudio} />
    </>
  );
}
