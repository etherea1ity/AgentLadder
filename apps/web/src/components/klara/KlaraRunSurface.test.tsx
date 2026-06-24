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
  it("renders LLM token metrics when present", () => {
    render(
      <KlaraRunSurface
        run={{
          ...baseRun,
          events: [
            evt("llm_call_started", { turn_index: 0, model: "qwen/qwen-flash" }),
            evt("llm_call_completed", {
              turn_index: 0,
              duration_ms: 123,
              prompt_tokens: 7,
              completion_tokens: 11,
              total_tokens: 18,
              token_source: "reported",
              tool_call_count: 1,
            }),
          ],
        }}
      />,
    );

    expect(screen.getByText("LLM rounds")).toBeInTheDocument();
    expect(screen.getByText("Turn 0")).toBeInTheDocument();
    expect(screen.getByText("qwen/qwen-flash")).toBeInTheDocument();
    expect(screen.getByText("input tokens")).toBeInTheDocument();
    expect(screen.getByText("18")).toBeInTheDocument();
    expect(screen.getByText("reported")).toBeInTheDocument();
  });

  it("shows unknown for missing LLM metrics", () => {
    render(
      <KlaraRunSurface
        run={{
          ...baseRun,
          events: [evt("llm_call_started", { turn_index: 1 })],
        }}
      />,
    );

    expect(screen.getByText("Turn 1")).toBeInTheDocument();
    expect(screen.getAllByText("unknown").length).toBeGreaterThan(1);
  });

  it("renders tool cards with arguments and observation previews", () => {
    render(
      <KlaraRunSurface
        run={{
          ...baseRun,
          events: [
            evt("tool_call_started", {
              tool_call: { id: "call_1", name: "current_time", arguments: { timezone: "Asia/Shanghai" } },
            }),
            evt("tool_call_completed", {
              tool_result: {
                tool_call_id: "call_1",
                name: "current_time",
                content_preview: "2026-06-18 20:30",
                content_length: 16,
                ok: true,
              },
              duration_ms: 42,
            }),
          ],
        }}
      />,
    );

    expect(screen.getByText("current_time")).toBeInTheDocument();
    expect(screen.getByText("completed")).toBeInTheDocument();
    expect(screen.getAllByText(/Asia\/Shanghai/).length).toBeGreaterThan(0);
    expect(screen.getByText("2026-06-18 20:30")).toBeInTheDocument();
    expect(screen.getByText("42ms")).toBeInTheDocument();
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

  it("keeps answer delta out of developer debug", () => {
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

    expect(screen.getByText("hook_placement_completed")).toBeInTheDocument();
    expect(
      screen.queryByText("This belongs in the assistant answer."),
    ).not.toBeInTheDocument();
  });

  it("renders raw payload only inside Developer debug", () => {
    render(
      <KlaraRunSurface
        run={{
          ...baseRun,
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

    expect(screen.getAllByText("Raw payload").length).toBeGreaterThan(0);
    expect(screen.getAllByText(/content_preview/).length).toBeGreaterThan(0);
  });

  it("keeps provider reasoning as a raw developer event", () => {
    render(
      <KlaraRunSurface
        run={{
          ...baseRun,
          events: [
            evt("provider_reasoning_delta", {
              items: [
                {
                  id: "provider_1",
                  title: "Model thinking",
                  body: "Provider reasoning summary.",
                  status: "completed",
                  kind: "orientation",
                  source: "provider_reasoning",
                  evidence_event_ids: ["evt_llm"],
                },
              ],
            }),
          ],
        }}
      />,
    );

    expect(screen.getAllByText("provider_reasoning_delta").length).toBeGreaterThan(0);
  });

  it("does not label persisted public events as unavailable", () => {
    render(
      <KlaraRunSurface
        run={{
          ...baseRun,
          status: "completed",
          trace_saved: false,
          events: [evt("run_completed", { trace_saved: false })],
        }}
      />,
    );

    expect(screen.getByText("Events loaded")).toBeInTheDocument();
    expect(screen.queryByText("Trace unavailable")).not.toBeInTheDocument();
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

    expect(screen.getByRole("button", { name: /developer debug/i })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.queryByText("current_time")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /developer debug/i }));

    expect(screen.getByText("current_time")).toBeInTheDocument();
  });

  it("can stay collapsed as a developer panel during active runs", () => {
    render(
      <KlaraRunSurface
        developerCollapsed
        run={{
          ...baseRun,
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

    expect(screen.getByRole("button", { name: /developer debug/i })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.queryByText("current_time")).not.toBeInTheDocument();
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
