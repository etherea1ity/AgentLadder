import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Run, RunEvent } from "../../types/domain";
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
  it("shows active thinking with a timer", () => {
    render(
      <KlaraThinkingBlock
        run={{
          ...baseRun,
          events: [evt("thinking_summary_started", { started_at: "2026-06-18T12:00:00Z" })],
        }}
      />,
    );

    expect(screen.getByText(/Thinking\.\.\. 1\.2s/)).toBeInTheDocument();
  });

  it("shows completed thought duration", () => {
    render(
      <KlaraThinkingBlock
        run={{
          ...baseRun,
          status: "completed",
          events: [evt("thinking_summary_completed", { duration_ms: 23900, has_summary: false })],
        }}
      />,
    );

    expect(screen.getByText("Thought for 23.9s")).toBeInTheDocument();
  });

  it("expands summary only from the right chevron", () => {
    render(
      <KlaraThinkingBlock
        run={{
          ...baseRun,
          status: "completed",
          events: [
            evt("thinking_summary_delta", {
              text: "Klara checked the public trace and summarized the verified tool flow.",
            }),
            evt("thinking_summary_completed", { duration_ms: 4200, has_summary: true }),
          ],
        }}
      />,
    );

    expect(screen.queryByText(/summarized the verified tool flow/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Thought for 4.2s"));

    expect(screen.queryByText(/summarized the verified tool flow/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /expand thinking summary/i }));

    expect(screen.getByText(/summarized the verified tool flow/)).toBeInTheDocument();
  });

  it("renders a live event-grounded stream without answer delta text", () => {
    render(
      <KlaraThinkingBlock
        run={{
          ...baseRun,
          events: [
            evt("llm_call_started", { model: "qwen/qwen-flash" }),
            evt("tool_call_started", { tool_call: { id: "call_1", name: "web_search" } }),
            evt("tool_call_completed", {
              tool_result: { tool_call_id: "call_1", name: "web_search", ok: true },
              metrics: { duration_ms: 900 },
            }),
            evt("answer_delta", { delta: "This is the assistant answer." }),
          ],
        }}
      />,
    );

    expect(screen.getByText("Called web_search.")).toBeInTheDocument();
    expect(screen.getByText("web_search returned an observation.")).toBeInTheDocument();
    expect(screen.queryByText("This is the assistant answer.")).not.toBeInTheDocument();
  });

  it("shows an empty completed state when no narrator summary exists", () => {
    render(
      <KlaraThinkingBlock
        run={{
          ...baseRun,
          status: "completed",
          events: [evt("thinking_summary_completed", { duration_ms: 800, has_summary: false })],
        }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /expand thinking summary/i }));

    expect(
      screen.getByText("No visible thinking summary was generated for this run."),
    ).toBeInTheDocument();
  });
});

function evt(event_type: RunEvent["event_type"], payload: RunEvent["payload"]): RunEvent {
  return {
    event_id: `evt_${event_type}_${Math.random()}`,
    run_id: "run_1",
    event_type,
    message: event_type,
    payload,
    created_at: new Date().toISOString(),
  };
}
