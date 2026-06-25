import type { Run, RunEvent } from "../../types/domain";

export function thinkingDurationMs(run: Run, events: RunEvent[]) {
  const completedSummary = [...events]
    .reverse()
    .find((event) => event.event_type === "thinking_summary_completed");
  const summaryDuration = numericPayload(completedSummary?.payload?.duration_ms);
  return (
    numericPayload(run.latency_ms) ??
    summaryDuration ??
    numericPayload(run.live?.elapsed_ms) ??
    null
  );
}

export function formatThinkingDuration(ms?: number | null) {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return "";
  if (ms < 60_000) {
    const seconds = ms / 1000;
    return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)}s`;
  }
  const totalSeconds = Math.round(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return seconds ? `${minutes}m ${seconds}s` : `${minutes}m`;
}

function numericPayload(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
