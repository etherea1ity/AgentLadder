import { fireEvent, render, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import { describe, expect, it, vi } from "vitest";
import type { Run, RunEvent } from "../../types/domain";
import { KlaraActivityDrawer } from "./KlaraActivityDrawer";
import { KlaraThinkingBlock } from "./KlaraThinkingBlock";

const baseRun: Run = {
  run_id: "run_1",
  session_id: "sess_1",
  user_message_id: "msg_u",
  assistant_message_id: "msg_a",
  status: "thinking",
  model: "qwen/qwen-flash",
  events: [],
  live: { streamed_chars: 0, current_label: "Calling model...", elapsed_ms: 1200 },
};

describe("KlaraThinkingBlock", () => {
  it("shows active thinking with a timer and real mini Klara marker", () => {
    const { container } = render(
      <KlaraThinkingBlock
        run={{
          ...baseRun,
          events: [evt("thinking_summary_started", { started_at: "2026-06-18T12:00:00Z" })],
        }}
      />,
    );

    expect(screen.getByText(/Thinking\.\.\. 1\.2s/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /mini klara/i })).toBeInTheDocument();
    expect(container.querySelector(".klara-thinking-mini .klara-presence")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /open activity/i })).not.toBeInTheDocument();
  });

  it("does not show completed Thought when provider reasoning is absent", () => {
    render(
      <KlaraThinkingBlock
        run={{
          ...baseRun,
          status: "completed",
          events: [evt("thinking_summary_completed", { duration_ms: 23900, has_summary: false })],
        }}
      />,
    );

    expect(screen.queryByText(/Thought for/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /open activity/i })).not.toBeInTheDocument();
  });

  it("shows active public commentary inline before the answer", () => {
    render(
      <KlaraThinkingBlock
        run={{
          ...baseRun,
          events: [
            evt("thinking_summary_started", { started_at: "2026-06-18T12:00:00Z" }),
            assistantActivityEvent(
              "I will check current sources before answering.",
            ),
          ],
        }}
      />,
    );

    expect(
      screen.getByText("I will check current sources before answering."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/web_search ·/)).not.toBeInTheDocument();
  });

  it("shows completed Thought when provider reasoning exists", () => {
    render(
      <KlaraThinkingBlock
        run={completedRun([
          providerReasoningEvent("The provider returned a safe reasoning summary."),
          evt("provider_reasoning_completed", {}),
          evt("thinking_summary_completed", { duration_ms: 800, has_summary: false }),
        ])}
      />,
    );

    expect(screen.getByText("Thought for 800ms")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /open activity/i })).toBeInTheDocument();
  });

  it("shows completed Thought when main-model commentary exists", () => {
    render(
      <KlaraThinkingBlock
        run={completedRun([
          assistantActivityEvent("I will use a tool before answering."),
          evt("thinking_summary_completed", { duration_ms: 900, has_summary: false }),
        ])}
      />,
    );

    expect(screen.getByText("Thought for 900ms")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /open activity/i })).toBeInTheDocument();
  });

  it("shows completed Thought when runtime action transcript exists", () => {
    render(
      <KlaraThinkingBlock
        run={completedRun([
          activityFactEvent({
            id: "fact_tool",
            kind: "web_search_result",
            status: "completed",
            source_event_type: "tool_call_completed",
            evidence_event_ids: ["evt_tool"],
            tool: { name: "web_search" },
            web: { result_count: 8, top_domains: ["fifa.com"] },
          }),
          evt("thinking_summary_completed", { duration_ms: 1000, has_summary: false }),
        ])}
      />,
    );

    expect(screen.getByText("Thought for 1s")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /open activity/i })).toBeInTheDocument();
  });

  it("does not open activity when the label is clicked", () => {
    const onOpenActivity = vi.fn();
    render(
      <KlaraThinkingBlock
        run={completedRun([
          providerReasoningEvent("The provider returned a safe reasoning summary."),
          evt("thinking_summary_completed", { duration_ms: 800, has_summary: false }),
        ])}
        onOpenActivity={onOpenActivity}
      />,
    );

    fireEvent.click(screen.getByText("Thought for 800ms"));
    expect(onOpenActivity).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /open activity/i }));
    expect(onOpenActivity).toHaveBeenCalledTimes(1);
  });

  it("renders drawer sections for provider, commentary, and agent transcript", () => {
    const run = completedRun([
      providerReasoningEvent("The provider returned a safe reasoning summary."),
      assistantActivityEvent("I will use a tool before answering."),
      activityFactEvent({
        id: "fact_fetch",
        kind: "web_fetch_result",
        status: "completed",
        source_event_type: "tool_call_completed",
        evidence_event_ids: ["evt_fetch"],
        tool: { name: "web_fetch" },
        web: {
          title_preview: "FIFA match schedule",
          source_domain: "fifa.com",
          text_length: 2300,
        },
      }),
      evt("thinking_summary_completed", { duration_ms: 800, has_summary: false }),
    ]);
    render(<ActivityHarness runs={[run]} />);

    fireEvent.click(screen.getByRole("button", { name: /open activity/i }));

    expect(screen.getAllByText("Model thinking").length).toBeGreaterThan(0);
    expect(screen.getByText("Klara activity")).toBeInTheDocument();
    expect(screen.getByText("Agent activity")).toBeInTheDocument();
    expect(screen.getByText("I will use a tool before answering.")).toBeInTheDocument();
    expect(screen.getByText("web_fetch")).toBeInTheDocument();
    expect(screen.getByText(/FIFA match schedule/)).toBeInTheDocument();
    expect(screen.getByText(/fifa\.com/)).toBeInTheDocument();
    expect(screen.queryByText(/https:\/\//)).not.toBeInTheDocument();
    expect(screen.queryByText(/raw payload/i)).not.toBeInTheDocument();
  });

  it("keeps a single activity drawer when multiple thinking blocks exist", () => {
    const runOne = completedRun(
      [
        providerReasoningEvent("First provider reasoning.", "run_1"),
        evt("thinking_summary_completed", { duration_ms: 800, has_summary: false }),
      ],
      "run_1",
    );
    const runTwo = completedRun(
      [
        providerReasoningEvent("Second provider reasoning.", "run_2"),
        evt("thinking_summary_completed", { duration_ms: 1400, has_summary: false }),
      ],
      "run_2",
    );

    render(<ActivityHarness runs={[runOne, runTwo]} />);

    const buttons = screen.getAllByRole("button", { name: /open activity/i });
    fireEvent.click(buttons[0]);
    expect(screen.getAllByRole("dialog", { name: /activity/i })).toHaveLength(1);
    expect(screen.getByText("First provider reasoning.")).toBeInTheDocument();

    fireEvent.click(buttons[1]);
    expect(screen.getAllByRole("dialog", { name: /activity/i })).toHaveLength(1);
    expect(screen.queryByText("First provider reasoning.")).not.toBeInTheDocument();
    expect(screen.getByText("Second provider reasoning.")).toBeInTheDocument();
  });

  it("closes the singleton drawer from close button, backdrop, and Escape", () => {
    const run = completedRun([
      providerReasoningEvent("The provider returned a safe reasoning summary."),
      evt("thinking_summary_completed", { duration_ms: 800, has_summary: false }),
    ]);
    const { container } = render(<ActivityHarness runs={[run]} />);

    fireEvent.click(screen.getByRole("button", { name: /open activity/i }));
    expect(screen.getByRole("dialog", { name: /activity/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /close activity/i }));
    expect(screen.queryByRole("dialog", { name: /activity/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /open activity/i }));
    const layer = container.querySelector(".klara-activity-layer");
    expect(layer).toBeTruthy();
    fireEvent.mouseDown(layer as Element);
    expect(screen.queryByRole("dialog", { name: /activity/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /open activity/i }));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: /activity/i })).not.toBeInTheDocument();
  });
});

function ActivityHarness({ runs }: { runs: Run[] }) {
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const activeRun = runs.find((run) => run.run_id === activeRunId) ?? null;
  return (
    <>
      {runs.map((run) => (
        <KlaraThinkingBlock
          key={run.run_id}
          run={run}
          isActivityOpen={activeRunId === run.run_id}
          onOpenActivity={(runId, trigger) => {
            triggerRef.current = trigger;
            setActiveRunId(runId);
          }}
        />
      ))}
      <KlaraActivityDrawer
        run={activeRun}
        open={Boolean(activeRun)}
        onClose={() => {
          setActiveRunId(null);
          window.setTimeout(() => triggerRef.current?.focus(), 0);
        }}
      />
    </>
  );
}

function completedRun(events: RunEvent[], runId = "run_1"): Run {
  return {
    ...baseRun,
    run_id: runId,
    status: "completed",
    latency_ms: 800,
    events: events.map((event, index) => ({
      ...event,
      run_id: runId,
      created_at: `2026-06-18T12:00:0${index}.000Z`,
    })),
  };
}

function providerReasoningEvent(body: string, runId = "run_1"): RunEvent {
  return evt("provider_reasoning_delta", {
    items: [
      {
        id: `provider_${runId}`,
        title: "Model thinking",
        body,
        status: "completed",
        kind: "orientation",
        source: "provider_reasoning",
        evidence_event_ids: [`evt_${runId}`],
        confidence: 1,
      },
    ],
  });
}

function assistantActivityEvent(text: string): RunEvent {
  return evt("assistant_activity_delta", {
    text,
    source: "main_model_commentary",
    phase: "before_tool",
    evidence_event_ids: ["evt_llm"],
  });
}

function activityFactEvent(fact: Record<string, unknown>): RunEvent {
  return evt("activity_fact_recorded", { fact });
}

function evt(
  event_type: RunEvent["event_type"],
  payload: Record<string, unknown>,
): RunEvent {
  return {
    event_id: `evt_${event_type}_${Math.random().toString(16).slice(2)}`,
    run_id: "run_1",
    event_type,
    message: event_type,
    payload,
    created_at: "2026-06-18T12:00:00.000Z",
  };
}
