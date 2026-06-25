import { fireEvent, render, screen, within } from "@testing-library/react";
import { useRef, useState } from "react";
import { describe, expect, it, vi } from "vitest";
import type { Run, RunEvent } from "../../types/domain";
import { KlaraThinkingDrawer } from "./KlaraThinkingDrawer";
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
  it("does not show active thinking before visible activity exists", () => {
    const { container } = render(
      <KlaraThinkingBlock
        run={{
          ...baseRun,
          events: [evt("thinking_summary_started", { started_at: "2026-06-18T12:00:00Z" })],
        }}
      />,
    );

    expect(screen.queryByText(/Thinking\.\.\./)).not.toBeInTheDocument();
    expect(screen.queryByText(/Thought for/)).not.toBeInTheDocument();
    expect(screen.queryByRole("img", { name: /mini klara/i })).not.toBeInTheDocument();
    expect(container.querySelector(".klara-thinking-mini .klara-presence")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /toggle thinking details/i })).not.toBeInTheDocument();
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
    expect(screen.queryByRole("button", { name: /toggle thinking details/i })).not.toBeInTheDocument();
  });

  it("shows active public commentary inline before the answer", () => {
    const { container } = render(
      <KlaraThinkingBlock
        run={{
          ...baseRun,
          events: [
            evt("thinking_summary_started", { started_at: "2026-06-18T12:00:00Z" }),
            assistantActivityEvent(
              "I will check current sources before answering.",
            ),
            assistantActivityEvent("Then I will separate confirmed facts from unknowns."),
          ],
        }}
      />,
    );

    expect(
      screen.queryByText("I will check current sources before answering."),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("Then I will separate confirmed facts from unknowns."),
    ).toBeInTheDocument();
    expect(container.querySelector(".klara-thinking-current")).toBeTruthy();
    expect(container.querySelector(".klara-thinking-cursor .klara-presence")).toBeTruthy();
    expect(
      screen.getByText("Then I will separate confirmed facts from unknowns."),
    ).toHaveClass("is-current");
    expect(screen.queryByText(/web_search/)).not.toBeInTheDocument();
  });

  it("shows only the latest repeated thinking update inline", () => {
    const { container } = render(
      <KlaraThinkingBlock
        run={{
          ...baseRun,
          events: [
            evt("thinking_summary_started", { started_at: "2026-06-18T12:00:00Z" }),
            assistantActivityEvent(
              "I will search recent World Model papers before answering.",
            ),
            assistantActivityEvent(
              "I will search the latest World Model papers before answering.",
            ),
          ],
        }}
      />,
    );

    expect(
      screen.queryByText("I will search recent World Model papers before answering."),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText("I will search the latest World Model papers before answering."),
    ).toBeInTheDocument();
    expect(container.querySelectorAll(".klara-thinking-current")).toHaveLength(1);
  });

  it("does not show active thinking when only runtime action transcript exists", () => {
    render(
      <KlaraThinkingBlock
        run={{
          ...baseRun,
          events: [
            activityFactEvent({
              id: "fact_tool",
              kind: "tool_call",
              status: "started",
              source_event_type: "tool_call_started",
              evidence_event_ids: ["evt_tool"],
              tool: { name: "web_search" },
            }),
          ],
        }}
      />,
    );

    expect(screen.queryByText(/Working\.\.\./)).not.toBeInTheDocument();
    expect(screen.queryByText(/Thinking\.\.\./)).not.toBeInTheDocument();
  });

  it("shows completed provider reasoning without a timer label", () => {
    render(
      <KlaraThinkingBlock
        run={completedRun([
          providerReasoningEvent("The provider returned a safe reasoning summary."),
          evt("provider_reasoning_completed", {}),
          evt("thinking_summary_completed", { duration_ms: 800, has_summary: false }),
        ])}
      />,
    );

    expect(screen.getByText("The provider returned a safe reasoning summary.")).toBeInTheDocument();
    expect(screen.queryByText(/Thought for/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /toggle thinking details/i })).toBeInTheDocument();
  });

  it("shows completed main-model commentary without a timer label", () => {
    render(
      <KlaraThinkingBlock
        run={completedRun([
          assistantActivityEvent("I will use a tool before answering."),
          evt("thinking_summary_completed", { duration_ms: 900, has_summary: false }),
        ])}
      />,
    );

    expect(screen.getByText("I will use a tool before answering.")).toBeInTheDocument();
    expect(screen.queryByText(/Thought for/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /toggle thinking details/i })).toBeInTheDocument();
  });

  it("does not show completed Thought when only runtime action transcript exists", () => {
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

    expect(screen.queryByText(/Worked for/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Thought for/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /toggle thinking details/i })).not.toBeInTheDocument();
  });

  it("toggles thinking when the visible thinking text is clicked", () => {
    const onToggleThinking = vi.fn();
    render(
      <KlaraThinkingBlock
        run={completedRun([
          providerReasoningEvent("The provider returned a safe reasoning summary."),
          evt("thinking_summary_completed", { duration_ms: 800, has_summary: false }),
        ])}
        onToggleThinking={onToggleThinking}
      />,
    );

    fireEvent.click(screen.getByText("The provider returned a safe reasoning summary."));
    expect(onToggleThinking).toHaveBeenCalledTimes(1);
  });

  it("renders drawer as a simple thinking list without runtime action sections", () => {
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

    fireEvent.click(screen.getByRole("button", { name: /toggle thinking details/i }));

    const drawer = screen.getByRole("dialog", { name: /thinking/i });
    const commentary = within(drawer).getByText("I will use a tool before answering.");
    expect(commentary).toBeInTheDocument();
    expect(within(drawer).getByText("The provider returned a safe reasoning summary.")).toBeInTheDocument();
    expect(drawer).toBeInTheDocument();
    expect(within(drawer).getByRole("heading", { name: "Thinking" })).toBeInTheDocument();
    expect(commentary.closest("li")).toHaveClass("is-current");
    expect(screen.queryByText("Actions")).not.toBeInTheDocument();
    expect(screen.queryByText("Klara activity")).not.toBeInTheDocument();
    expect(screen.queryByText("Agent activity")).not.toBeInTheDocument();
    expect(screen.queryByText("Provider reasoning")).not.toBeInTheDocument();
    expect(screen.queryByText("Original model reasoning")).not.toBeInTheDocument();
    expect(screen.queryByText("Before tools")).not.toBeInTheDocument();
    expect(screen.queryByText("web_fetch")).not.toBeInTheDocument();
    expect(screen.queryByText(/FIFA match schedule/)).not.toBeInTheDocument();
    expect(screen.queryByText(/fifa\.com/)).not.toBeInTheDocument();
    expect(screen.queryByText(/https:\/\//)).not.toBeInTheDocument();
    expect(screen.queryByText(/raw payload/i)).not.toBeInTheDocument();
  });

  it("strips internal activity field labels from visible thinking", () => {
    const run = completedRun([
      assistantActivityEvent(
        "update_activity.text: I will check public sources before answering.",
      ),
      evt("thinking_summary_completed", { duration_ms: 900, has_summary: false }),
    ]);
    render(<ActivityHarness runs={[run]} />);

    fireEvent.click(screen.getByRole("button", { name: /toggle thinking details/i }));

    expect(
      within(screen.getByRole("dialog", { name: /thinking/i })).getByText(
        "I will check public sources before answering.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/update_activity\.text/i)).not.toBeInTheDocument();
  });

  it("keeps a single thinking drawer when multiple thinking blocks exist", () => {
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

    const buttons = screen.getAllByRole("button", { name: /toggle thinking details/i });
    fireEvent.click(buttons[0]);
    expect(screen.getAllByRole("dialog", { name: /thinking/i })).toHaveLength(1);
    expect(
      within(screen.getByRole("dialog", { name: /thinking/i })).getByText(
        "First provider reasoning.",
      ),
    ).toBeInTheDocument();

    fireEvent.click(buttons[1]);
    expect(screen.getAllByRole("dialog", { name: /thinking/i })).toHaveLength(1);
    const drawerAfterSwitch = within(screen.getByRole("dialog", { name: /thinking/i }));
    expect(drawerAfterSwitch.queryByText("First provider reasoning.")).not.toBeInTheDocument();
    expect(drawerAfterSwitch.getByText("Second provider reasoning.")).toBeInTheDocument();
  });

  it("closes the singleton drawer from close button, backdrop, and Escape", () => {
    const run = completedRun([
      providerReasoningEvent("The provider returned a safe reasoning summary."),
      evt("thinking_summary_completed", { duration_ms: 800, has_summary: false }),
    ]);
    const { container } = render(<ActivityHarness runs={[run]} />);

    fireEvent.click(screen.getByRole("button", { name: /toggle thinking details/i }));
    expect(screen.getByRole("dialog", { name: /thinking/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /toggle thinking details/i }));
    expect(screen.queryByRole("dialog", { name: /thinking/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /toggle thinking details/i }));
    expect(screen.getByRole("dialog", { name: /thinking/i })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /close thinking/i }));
    expect(screen.queryByRole("dialog", { name: /thinking/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /toggle thinking details/i }));
    const layer = container.querySelector(".klara-thinking-drawer-layer");
    expect(layer).toBeTruthy();
    fireEvent.mouseDown(layer as Element);
    expect(screen.queryByRole("dialog", { name: /thinking/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /toggle thinking details/i }));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog", { name: /thinking/i })).not.toBeInTheDocument();
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
          isThinkingOpen={activeRunId === run.run_id}
          onToggleThinking={(runId, trigger) => {
            triggerRef.current = trigger;
            setActiveRunId((current) => (current === runId ? null : runId));
          }}
        />
      ))}
      <KlaraThinkingDrawer
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
        title: "Provider reasoning",
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
