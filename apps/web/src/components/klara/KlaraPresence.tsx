import type { KlaraCapabilityChip, KlaraVisualPhase } from "../../types/domain";
import { KlaraRiveField } from "./KlaraRiveField";

type Props = {
  phase?: KlaraVisualPhase;
  active?: boolean;
  size?: "hero" | "orb" | "status" | "stamp" | "panel";
  capabilities?: KlaraCapabilityChip[];
  elevated?: boolean;
  pulseKey?: number;
};

export function KlaraPresence({
  phase = "idle",
  active = false,
  size = "status",
  capabilities = [],
  elevated = false,
  pulseKey = 0,
}: Props) {
  const showCapabilities = size === "panel" ? capabilities : [];
  return (
    <span
      className={`klara-presence klara-${size} phase-${phase} ${active ? "is-active" : "is-static"} ${elevated ? "is-elevated" : ""}`}
      aria-hidden="true"
    >
      <KlaraRiveField
        phase={phase}
        active={active}
        elevated={elevated}
        pulseKey={pulseKey}
        variant={size === "hero" ? "hero" : "presence"}
        capabilities={showCapabilities}
      />
      <img
        className="klara-mark"
        src="/brand/klara/klara-mark-light.png"
        alt=""
      />
    </span>
  );
}
