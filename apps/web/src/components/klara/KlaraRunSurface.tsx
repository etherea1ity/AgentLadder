import { CheckCircle2, ChevronDown, ChevronRight, CircleDashed, Wrench, XCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { Run, RunEvent } from "../../types/domain";
import { isKlaraRunActive } from "./useKlaraRunMotion";

type ToolCard = {
  id: string;
  name: string;
  status: "running" | "completed" | "failed";
  preview: string;
  error: string;
  contentLength: number | null;
};

export function KlaraRunSurface({ run }: { run?: Run }) {
  const active = isKlaraRunActive(run);
  const [expanded, setExpanded] = useState(active);

  useEffect(() => {
    setExpanded(active);
  }, [active, run?.run_id]);

  const visibleEvents = useMemo(
    () => (run?.events ?? []).filter((event) => event.event_type !== "answer_delta"),
    [run?.events],
  );
  const toolCards = useMemo(() => buildToolCards(visibleEvents), [visibleEvents]);
  const hookBadges = useMemo(() => buildHookBadges(visibleEvents), [visibleEvents]);
  const workstreamNotes = useMemo(() => buildWorkstreamNotes(visibleEvents), [visibleEvents]);
  const timeline = useMemo(() => buildTimeline(visibleEvents), [visibleEvents]);
  const traceSaved = Boolean(
    run?.trace_saved ||
      visibleEvents.some(
        (event) =>
          event.event_type === "trace_saved" ||
          (event.event_type === "run_completed" && event.payload?.trace_saved === true),
      ),
  );

  if (!run) return null;

  const title = `Run trace · ${visibleEvents.length} events · ${toolCards.length} ${toolCards.length === 1 ? "tool" : "tools"}`;

  return (
    <section className={`klara-run-surface ${active ? "is-active" : "is-compact"}`} aria-label="Run trace">
      <button
        className="klara-run-surface-toggle"
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
      >
        {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        <span>{title}</span>
        <small>{traceSaved ? "Trace saved" : active ? "Tracing" : "Trace unavailable"}</small>
      </button>
      {expanded ? (
        <div className="klara-run-surface-body">
          {workstreamNotes.length ? (
            <div className="klara-workstream-notes" aria-label="Runtime notes">
              {workstreamNotes.map((note) => (
                <p key={note.key}>{note.text}</p>
              ))}
            </div>
          ) : null}
          {hookBadges.length ? (
            <div className="klara-hook-badges" aria-label="Hook placement events">
              {hookBadges.map((badge) => (
                <span className={badge.blocked ? "is-blocked" : ""} key={badge.key}>
                  {badge.label}
                </span>
              ))}
            </div>
          ) : null}
          {toolCards.length ? (
            <div className="klara-tool-card-grid">
              {toolCards.map((tool) => (
                <ToolRunCard key={tool.id} tool={tool} />
              ))}
            </div>
          ) : null}
          {timeline.length ? (
            <ol className="klara-run-timeline" aria-label="Lifecycle timeline">
              {timeline.map((item) => (
                <li className={`is-${item.status}`} key={item.key}>
                  <span aria-hidden="true" />
                  <p>{item.label}</p>
                </li>
              ))}
            </ol>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function ToolRunCard({ tool }: { tool: ToolCard }) {
  const Icon =
    tool.status === "completed" ? CheckCircle2 : tool.status === "failed" ? XCircle : CircleDashed;
  const detail = tool.status === "failed" ? tool.error : tool.preview;
  return (
    <article className={`klara-tool-card is-${tool.status}`}>
      <span className="klara-tool-icon" aria-hidden="true">
        <Wrench size={15} />
      </span>
      <div>
        <header>
          <h4>{tool.name}</h4>
          <span>
            <Icon size={14} />
            {tool.status}
          </span>
        </header>
        {detail ? <p>{detail}</p> : <p className="is-muted">No preview returned.</p>}
        {tool.contentLength != null ? <small>{tool.contentLength} chars</small> : null}
      </div>
    </article>
  );
}

function buildToolCards(events: RunEvent[]): ToolCard[] {
  const cards = new Map<string, ToolCard>();
  events.forEach((event) => {
    if (event.event_type === "tool_call_started") {
      const call = event.payload?.tool_call as { id?: string; name?: string } | undefined;
      const id = call?.id ?? event.event_id;
      cards.set(id, {
        id,
        name: call?.name ?? "tool",
        status: "running",
        preview: "",
        error: "",
        contentLength: null,
      });
      return;
    }
    if (event.event_type !== "tool_call_completed" && event.event_type !== "tool_call_failed") return;
    const result = event.payload?.tool_result as {
      tool_call_id?: string;
      name?: string;
      content_preview?: string;
      content_length?: number;
      error?: string;
    } | undefined;
    const id = result?.tool_call_id ?? event.event_id;
    const existing = cards.get(id);
    cards.set(id, {
      id,
      name: result?.name ?? existing?.name ?? "tool",
      status: event.event_type === "tool_call_failed" ? "failed" : "completed",
      preview: result?.content_preview ?? existing?.preview ?? "",
      error: result?.error ?? "",
      contentLength: typeof result?.content_length === "number" ? result.content_length : null,
    });
  });
  return Array.from(cards.values());
}

function buildHookBadges(events: RunEvent[]) {
  return events
    .filter(
      (event) =>
        event.event_type === "hook_placement_started" ||
        event.event_type === "hook_placement_completed",
    )
    .map((event) => {
      const placement = String(event.payload?.placement ?? "Hook");
      const allowed = event.payload?.allowed;
      const completed = event.event_type === "hook_placement_completed";
      const blocked = completed && allowed === false;
      const status = completed
        ? blocked
          ? "blocked"
          : allowed === true
            ? "allowed"
            : "completed"
        : "started";
      return {
        key: event.event_id,
        blocked,
        label: `${placement} ${status}`,
      };
    });
}

function buildWorkstreamNotes(events: RunEvent[]) {
  return events
    .filter((event) => event.event_type === "workstream_note")
    .map((event) => ({
      key: event.event_id,
      text: String(event.payload?.text ?? event.message),
    }))
    .filter((note) => note.text.trim());
}

function buildTimeline(events: RunEvent[]) {
  return events
    .filter(
      (event) =>
        event.event_type === "llm_call_started" ||
        event.event_type === "llm_call_completed" ||
        event.event_type === "policy_stop" ||
        event.event_type === "run_completed",
    )
    .map((event) => {
      if (event.event_type === "llm_call_started") {
        return {
          key: event.event_id,
          status: "running",
          label: `${String(event.payload?.model ?? "Model")} started`,
        };
      }
      if (event.event_type === "llm_call_completed") {
        return {
          key: event.event_id,
          status: "completed",
          label: "Model call completed",
        };
      }
      if (event.event_type === "policy_stop") {
        return {
          key: event.event_id,
          status: "completed",
          label: String(event.payload?.reason ?? "Tool policy stopped"),
        };
      }
      return {
        key: event.event_id,
        status: "completed",
        label: "Run completed",
      };
    });
}
