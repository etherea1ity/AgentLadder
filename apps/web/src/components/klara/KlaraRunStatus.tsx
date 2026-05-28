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
  expanded,
  handoffActive = false,
  visuallyActive = true,
  arrivalActive = false,
  onOpen,
}: {
  run?: Run;
  expanded: boolean;
  handoffActive?: boolean;
  visuallyActive?: boolean;
  arrivalActive?: boolean;
  onOpen: () => void;
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
    <button
      data-klara-run-anchor={run.run_id}
      className={`klara-status-row ${showActivePresence ? "is-active" : "is-stamp"} ${active && !showActivePresence ? "is-background-run" : ""} ${handoffActive ? "is-receiving-handoff" : ""} phase-${view.phase}`}
      onClick={onOpen}
      aria-expanded={expanded}
      aria-controls="run-margin-panel"
      aria-label={
        expanded
          ? "Run trace is open for this answer"
          : "Open run trace for this answer"
      }
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
            capabilities={active ? view.capabilities : ["trace"]}
            elevated={expanded || active || arrivalActive}
            pulseKey={active ? run.events.length : arrivalActive ? 1 : 0}
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
    </button>
  );
}
