import type { KlaraVisualPhase } from "../../types/domain";
import { KlaraPresence } from "./KlaraPresence";

export function KlaraOrbLayer({
  visible,
  phase = "idle",
  inputActive,
  pulseKey,
}: {
  visible: boolean;
  phase?: KlaraVisualPhase;
  inputActive: boolean;
  pulseKey: number;
}) {
  if (!visible) return null;
  return (
    <div
      className={`klara-orb-layer ${inputActive ? "is-listening" : ""}`}
      aria-hidden="true"
    >
      <KlaraPresence active={inputActive} phase={inputActive ? "listening" : phase} size="orb" pulseKey={pulseKey} />
    </div>
  );
}
