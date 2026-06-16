import type { Run } from "../../types/domain";
import { KlaraPresence } from "./KlaraPresence";
import { KlaraStamp } from "./KlaraStamp";
import {
  formatLatency,
  isKlaraRunActive,
  useKlaraRunMotion,
} from "./useKlaraRunMotion";

export function KlaraRunStatus({
  run,
  handoffActive = false,
  visuallyActive = true,
  arrivalActive = false,
}: {
  run?: Run;
  handoffActive?: boolean;
  visuallyActive?: boolean;
  arrivalActive?: boolean;
}) {
  if (!run)
    return (
      <div className="klara-status-row">
        <KlaraStamp />
        <span className="klara-status-name">Klara</span>
      </div>
    );
  const view = useKlaraRunMotion(run);
  const active = isKlaraRunActive(run);
  const showActivePresence = (active && visuallyActive) || arrivalActive;
  const visualPhase = active ? view.phase : arrivalActive ? "completed" : view.phase;
  const duration =
    formatLatency(run.latency_ms) ||
    (run.live?.elapsed_ms ? formatLatency(run.live.elapsed_ms) : "");
  const statusText = active
    ? view.label
    : run.status === "completed"
      ? "Completed"
      : run.status === "cancelled"
        ? "Stopped"
        : "Failed";
  const accessibleText = statusText;
  return (
    <div
      data-klara-run-anchor={run.run_id}
      className={`klara-status-row ${showActivePresence ? "is-active" : "is-stamp"} ${active && !showActivePresence ? "is-background-run" : ""} ${handoffActive ? "is-receiving-handoff" : ""} phase-${view.phase}`}
      aria-label={`Klara status: ${accessibleText}`}
    >
      <span
        className="klara-status-presence-slot"
        data-klara-run-presence-anchor={run.run_id}
        aria-hidden="true"
      >
        {showActivePresence ? (
          <KlaraPresence
            active
            phase={visualPhase}
            size="status"
            capabilities={active ? view.capabilities : ["model"]}
            elevated={active || arrivalActive}
            pulseKey={active ? semanticPulseKey(run) : arrivalActive ? 1 : 0}
          />
        ) : (
          <KlaraStamp label="" />
        )}
      </span>
      <span className="klara-status-name">Klara</span>
      <span className="klara-status-dot">·</span>
      <span className="klara-status-copy">{statusText}</span>
      <span className="klara-status-plain">{accessibleText}</span>
      {duration ? <span className="klara-status-time">{duration}</span> : null}
    </div>
  );
}
function semanticPulseKey(run: Run) {
  const semanticEvents = run.events.filter(
    (event) => event.event_type !== "answer_delta",
  ).length;
  const streamedBucket = Math.floor((run.live?.streamed_chars ?? 0) / 180);
  return semanticEvents + streamedBucket;
}
