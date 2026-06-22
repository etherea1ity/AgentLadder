import { ChevronDown, ChevronRight } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { Run, RunEvent } from "../../types/domain";
import { isKlaraRunActive } from "./useKlaraRunMotion";

type StreamItem = {
  key: string;
  label: string;
  detail?: string;
  status: "running" | "completed" | "failed";
};

export function KlaraThinkingBlock({ run }: { run?: Run }) {
  const active = isKlaraRunActive(run);
  const [expanded, setExpanded] = useState(active);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    setExpanded(active);
  }, [active, run?.run_id]);

  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(timer);
  }, [active]);

  const events = useMemo(
    () => [...(run?.events ?? [])].sort((a, b) => a.created_at.localeCompare(b.created_at)),
    [run?.events],
  );
  const summaryText = useMemo(() => latestThinkingSummary(events), [events]);
  const completionEvent = useMemo(
    () => [...events].reverse().find((event) => event.event_type === "thinking_summary_completed"),
    [events],
  );
  const streamItems = useMemo(() => buildThinkingStream(events), [events]);

  if (!run) return null;

  const durationMs = thinkingDurationMs(run, events, completionEvent, active, now);
  const hasSummary =
    Boolean(summaryText) || completionEvent?.payload?.has_summary === true;
  const label = active ? `Thinking... ${formatThoughtDuration(durationMs)}` : `Thought for ${formatThoughtDuration(durationMs)}`;
  const showEmptySummary = !active && !hasSummary;

  return (
    <section
      className={`klara-thinking-block ${active ? "is-active" : "is-completed"}`}
      aria-label="Thinking summary"
    >
      <div className="klara-thinking-row">
        <div className="klara-thinking-title">
          <span className="klara-thinking-pulse" aria-hidden="true" />
          <span>{label}</span>
        </div>
        <button
          type="button"
          className="klara-thinking-toggle"
          aria-label={expanded ? "Collapse thinking summary" : "Expand thinking summary"}
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        </button>
      </div>
      {expanded ? (
        <div className="klara-thinking-body">
          {summaryText ? <p className="klara-thinking-summary">{summaryText}</p> : null}
          {streamItems.length ? (
            <ol className="klara-thinking-stream" aria-label="Runtime event stream">
              {streamItems.map((item) => (
                <li className={`is-${item.status}`} key={item.key}>
                  <span aria-hidden="true" />
                  <div>
                    <p>{item.label}</p>
                    {item.detail ? <small>{item.detail}</small> : null}
                  </div>
                </li>
              ))}
            </ol>
          ) : showEmptySummary ? (
            <p className="klara-thinking-empty">No visible thinking summary was generated for this run.</p>
          ) : null}
          {showEmptySummary && streamItems.length ? (
            <p className="klara-thinking-empty">No visible thinking summary was generated for this run.</p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function latestThinkingSummary(events: RunEvent[]) {
  const summaries = events
    .filter((event) => event.event_type === "thinking_summary_delta")
    .map((event) => String(event.payload?.text ?? event.message ?? "").trim())
    .filter(Boolean);
  return summaries[summaries.length - 1];
}

function thinkingDurationMs(
  run: Run,
  events: RunEvent[],
  completionEvent: RunEvent | undefined,
  active: boolean,
  now: number,
) {
  const explicitDuration = numberFrom(completionEvent?.payload?.duration_ms);
  if (explicitDuration != null) return explicitDuration;
  if (run.latency_ms != null) return run.latency_ms;
  if (run.live?.elapsed_ms != null) return run.live.elapsed_ms;
  const startEvent =
    events.find((event) => event.event_type === "thinking_summary_started") ?? events[0];
  if (active && startEvent) {
    const startedAt = Date.parse(startEvent.created_at);
    if (!Number.isNaN(startedAt)) return Math.max(0, now - startedAt);
  }
  return 0;
}

function buildThinkingStream(events: RunEvent[]) {
  const items = events
    .map((event) => streamItemForEvent(event))
    .filter((item): item is StreamItem => Boolean(item));
  return items.slice(-8);
}

function streamItemForEvent(event: RunEvent): StreamItem | null {
  switch (event.event_type) {
    case "run_created":
      return item(event, "Received the request.", undefined, "completed");
    case "thinking_started":
      return item(event, "Prepared the runtime state.", undefined, "completed");
    case "thinking_summary_started":
      return item(event, "Started visible thinking tracking.", undefined, "running");
    case "llm_call_started":
      return item(event, "Called the selected model.", String(event.payload?.model ?? ""), "running");
    case "llm_call_completed":
      return item(event, "The model returned a response.", durationDetail(event), "completed");
    case "tool_call_started": {
      const toolName = toolCallName(event);
      return item(event, `Called ${toolName}.`, undefined, "running");
    }
    case "tool_call_completed": {
      const toolName = toolResultName(event);
      return item(event, `${toolName} returned an observation.`, durationDetail(event), "completed");
    }
    case "tool_call_failed": {
      const toolName = toolResultName(event);
      return item(event, `${toolName} failed.`, errorDetail(event) || durationDetail(event), "failed");
    }
    case "hook_placement_started":
      return item(event, `${placementName(event)} hook started.`, undefined, "running");
    case "hook_placement_completed":
      return item(
        event,
        `${placementName(event)} hook completed.`,
        event.payload?.allowed === false ? String(event.payload?.reason ?? "Blocked by hook.") : undefined,
        event.payload?.allowed === false ? "failed" : "completed",
      );
    case "policy_stop":
      return item(event, "Stopped additional tool calls.", String(event.payload?.reason ?? ""), "completed");
    case "workstream_note": {
      const text = String(event.payload?.text ?? event.message ?? "").trim();
      return text ? item(event, text, undefined, "completed") : null;
    }
    case "thinking_summary_completed":
      return item(event, "Finished the visible thinking summary.", durationDetail(event), "completed");
    case "run_completed":
      return item(event, "Completed the run.", undefined, "completed");
    case "run_failed":
      return item(event, "The run failed.", String(event.payload?.error ?? event.message ?? ""), "failed");
    case "run_cancelled":
      return item(event, "The run was stopped.", undefined, "failed");
    default:
      return null;
  }
}

function item(
  event: RunEvent,
  label: string,
  detail?: string,
  status: StreamItem["status"] = "completed",
): StreamItem {
  return {
    key: event.event_id,
    label,
    detail: detail?.trim() || undefined,
    status,
  };
}

function toolCallName(event: RunEvent) {
  const toolCall = event.payload?.tool_call as { name?: string } | undefined;
  return toolCall?.name ?? "tool";
}

function toolResultName(event: RunEvent) {
  const toolResult = event.payload?.tool_result as { name?: string } | undefined;
  return toolResult?.name ?? "tool";
}

function placementName(event: RunEvent) {
  return String(event.payload?.placement ?? "Hook");
}

function durationDetail(event: RunEvent) {
  const metrics = event.payload?.metrics as { duration_ms?: number } | undefined;
  const duration = numberFrom(event.payload?.duration_ms) ?? numberFrom(metrics?.duration_ms);
  return duration != null ? `${formatThoughtDuration(duration)} elapsed` : undefined;
}

function errorDetail(event: RunEvent) {
  const toolResult = event.payload?.tool_result as { error?: string } | undefined;
  return toolResult?.error;
}

function numberFrom(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function formatThoughtDuration(ms: number) {
  if (!Number.isFinite(ms) || ms <= 0) return "0s";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1).replace(/\.0$/, "")}s`;
  const minutes = Math.floor(ms / 60000);
  const seconds = Math.round((ms % 60000) / 1000);
  return `${minutes}m ${seconds}s`;
}
