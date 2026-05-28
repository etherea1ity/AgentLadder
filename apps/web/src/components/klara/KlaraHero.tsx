import { KlaraRiveField } from "./KlaraRiveField";

export function KlaraHero({ inputActive, pulseKey }: { inputActive: boolean; pulseKey: number }) {
  return (
    <div className={`klara-hero ${inputActive ? "is-listening" : ""}`} aria-label="Klara Agent System">
      <KlaraRiveField
        phase={inputActive ? "listening" : "idle"}
        active={inputActive}
        elevated={inputActive}
        pulseKey={pulseKey}
        variant="hero"
      />
      <img src="/brand/klara/klara-poster-lockup-reference.png" alt="Klara Agent System" />
    </div>
  );
}
