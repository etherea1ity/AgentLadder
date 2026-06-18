import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Run, RunEvent } from "../../types/domain";
import { KlaraRunSurface } from "./KlaraRunSurface";

const baseRun: Run = {
  run_id: "run_1",
  session_id: "sess_1",
  user_message_id: "msg_u",
  assistant_message_id: "msg_a",
  status: "thinking",
  model: "qwen/qwen-flash",
  events: [],
  live: { streamed_chars: 0, current_label: "Calling model..." },
};

describe("KlaraRunSurface", () => {
  it("renders tool call started and completed cards", () => {
    render(
      <KlaraRunSurface
        run={{
          ...baseRun,
          events: [
            evt("tool_call_started", {
              tool_call: { id: "call_1", name: "current_time" },
            }),
            evt("tool_call_completed", {
              tool_result: {
                tool_call_id: "call_1",
                name: "current_time",
                content_preview: "2026-06-18 20:30",
                content_length: 16,
                ok: true,
              },
            }),
          ],
        }}
      />,
    );

    expect(screen.getByText("current_time")).toBeInTheDocument();
    expect(screen.getByText("completed")).toBeInTheDocument();
    expect(screen.getByText("2026-06-18 20:30")).toBeInTheDocument();
  });

  it("renders failed tool cards", () => {
    render(
      <KlaraRunSurface
        run={{
          ...baseRun,
          events: [
            evt("tool_call_failed", {
              blocked: true,
              tool_result: {
                tool_call_id: "call_2",
                name: "web_search",
                content_preview: "",
                content_length: 0,
                ok: false,
                error: "Tool blocked by hook: test",
              },
            }),
          ],
        }}
      />,
    );

    expect(screen.getByText("web_search")).toBeInTheDocument();
    expect(screen.getByText("failed")).toBeInTheDocument();
    expect(screen.getByText("Tool blocked by hook: test")).toBeInTheDocument();
  });

  it("renders hook placement badges without answer delta text", () => {
    render(
      <KlaraRunSurface
        run={{
          ...baseRun,
          events: [
            evt("hook_placement_completed", {
              placement: "PreToolUse",
              allowed: true,
            }),
            evt("answer_delta", { delta: "This belongs in the assistant answer." }),
          ],
        }}
      />,
    );

    expect(screen.getByText("PreToolUse allowed")).toBeInTheDocument();
    expect(
      screen.queryByText("This belongs in the assistant answer."),
    ).not.toBeInTheDocument();
  });

  it("renders workstream notes as runtime surface content", () => {
    render(
      <KlaraRunSurface
        run={{
          ...baseRun,
          events: [
            evt("workstream_note", {
              text: "Klara is preparing the observable run.",
              source: "narrator_model",
              evidence_event_ids: ["evt_1"],
            }),
          ],
        }}
      />,
    );

    expect(screen.getByText("Klara is preparing the observable run.")).toBeInTheDocument();
  });

  it("collapses completed runs by default", () => {
    render(
      <KlaraRunSurface
        run={{
          ...baseRun,
          status: "completed",
          trace_saved: true,
          events: [
            evt("tool_call_completed", {
              tool_result: {
                tool_call_id: "call_1",
                name: "current_time",
                content_preview: "done",
                content_length: 4,
                ok: true,
              },
            }),
          ],
        }}
      />,
    );

    expect(screen.getByRole("button", { name: /run trace/i })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.queryByText("current_time")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /run trace/i }));

    expect(screen.getByText("current_time")).toBeInTheDocument();
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
