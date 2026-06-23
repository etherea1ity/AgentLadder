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

  it("opens activity only from the right chevron", () => {
    render(
      <KlaraThinkingBlock
        run={{
          ...baseRun,
          status: "completed",
          events: [
            evt("thinking_summary_delta", {
              text: "Klara summarized the public trace.",
              items: [
                activity("act_1", "Preparing the run", "Klara set up the runtime.", "narrator_model"),
                activity("act_2", "Writing the answer", "Klara composed the final response.", "narrator_model"),
              ],
            }),
            evt("thinking_summary_completed", { duration_ms: 4200, has_summary: true }),
          ],
        }}
      />,
    );

    expect(screen.queryByText("Klara thinking")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Thought for 4.2s"));

    expect(screen.queryByText("Klara thinking")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /open activity/i }));

    expect(screen.getByText("Klara thinking")).toBeInTheDocument();
    expect(screen.getByText("Preparing the run")).toBeInTheDocument();
  });

  it("renders narrator and runtime activity inside the drawer", () => {
    render(
      <KlaraThinkingBlock
        run={{
          ...baseRun,
          status: "completed",
          events: [
            evt("thinking_summary_delta", {
              items: [
                activity("act_summary_1", "Preparing the run", "Klara set up the runtime.", "narrator_model"),
                activity("act_summary_2", "Writing the answer", "Klara composed the final response.", "narrator_model"),
              ],
            }),
            evt("activity_item_upserted", {
              item: activity(
                "act_runtime_1",
                "Search results returned",
                "Klara received candidate sources.",
                "runtime_event",
              ),
            }),
            evt("thinking_summary_completed", { duration_ms: 800, has_summary: true }),
          ],
        }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /open activity/i }));

    expect(screen.getByText("Klara thinking")).toBeInTheDocument();
    expect(screen.getByText("Agent activity")).toBeInTheDocument();
    expect(screen.getByText("Search results returned")).toBeInTheDocument();
  });

  it("does not render a raw tool chain in the top thinking trigger", () => {
    render(
      <KlaraThinkingBlock
        run={{
          ...baseRun,
          events: [
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

    expect(screen.queryByText("Called web_search.")).not.toBeInTheDocument();
    expect(screen.queryByText("web_search returned an observation.")).not.toBeInTheDocument();
    expect(screen.queryByText("This is the assistant answer.")).not.toBeInTheDocument();
  });

  it("closes the activity drawer", () => {
    render(
      <KlaraThinkingBlock
        run={{
          ...baseRun,
          status: "completed",
          events: [evt("thinking_summary_completed", { duration_ms: 800, has_summary: false })],
        }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /open activity/i }));
    expect(screen.getByText("No public thinking summary was generated for this run.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /close activity/i }));

    expect(screen.queryByText("No public thinking summary was generated for this run.")).not.toBeInTheDocument();
  });
});

function activity(
  id: string,
  title: string,
  body: string,
  source: "runtime_event" | "narrator_model",
) {
  return {
    id,
    title,
    body,
    status: "completed",
    kind: "orientation",
    source,
    evidence_event_ids: ["evt_1"],
    confidence: 0.8,
  };
}

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

