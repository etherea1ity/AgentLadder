import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

class MockEventSource {
  static instances: MockEventSource[] = [];
  listeners: Record<string, ((event: MessageEvent) => void)[]> = {};
  onerror: (() => void) | null = null;

  constructor(public url: string) {
    MockEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (event: MessageEvent) => void) {
    (this.listeners[type] ??= []).push(listener);
  }

  emit(type: string, data: unknown) {
    (this.listeners[type] ?? []).forEach((listener) =>
      listener({ data: JSON.stringify(data) } as MessageEvent),
    );
  }

  close() {
    return undefined;
  }
}

const now = new Date().toISOString();
const session = {
  session_id: "sess_1",
  title: "runtime loop",
  created_at: now,
  updated_at: now,
  message_ids: [],
};
const runResponse = {
  run_id: "run_1",
  session_id: "sess_1",
  user_message_id: "msg_u",
  assistant_message_id: "msg_a",
  status: "queued",
  events_url: "/api/runs/run_1/events/stream",
};
let listedSessions: (typeof session)[];

describe("Klara app flow", () => {
  beforeEach(() => {
    localStorage.clear();
    MockEventSource.instances = [];
    listedSessions = [];
    vi.stubGlobal("EventSource", MockEventSource);
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url === "/api/models")
          return json({
            default_model: "qwen/qwen-flash",
            models: [
              {
                id: "qwen/qwen-flash",
                model: "qwen/qwen-flash",
                label: "Qwen 3.7 Flash",
                use_when: "qwen provider",
              },
            ],
          });
        if (url === "/api/sessions" && (!init || init.method === undefined)) return json({ sessions: listedSessions });
        if (url === "/api/sessions" && init?.method === "POST") return json(session);
        if (url === "/api/runs") return json(runResponse);
        if (url === "/api/sessions/sess_1")
          return json({
            session,
            messages: [
              {
                message_id: "msg_u",
                session_id: "sess_1",
                role: "user",
                content: "run the runtime loop",
                status: "completed",
                created_at: now,
              },
              {
                message_id: "msg_a",
                session_id: "sess_1",
                role: "assistant",
                content: "Klara completed the runtime loop.",
                run_id: "run_1",
                status: "completed",
                created_at: now,
              },
            ],
            runs: [
              {
                ...runResponse,
                status: "completed",
                latency_ms: 1200,
                trace_saved: true,
              },
            ],
            events: [
              evt("tool_call_started", "Klara is using current_time.", {
                tool_call: { id: "call_1", name: "current_time" },
              }),
              evt("tool_call_completed", "current_time returned.", {
                tool_result: {
                  tool_call_id: "call_1",
                  name: "current_time",
                  ok: true,
                  content_preview: "Asia/Shanghai 22:00",
                  content_length: 20,
                },
              }),
              evt("run_completed", "Run completed.", {
                latency_ms: 1200,
                trace_saved: true,
              }),
            ],
          });
        return json({});
      }),
    );
  });

  afterEach(() => vi.restoreAllMocks());

  it("restores the previous conversation after a page refresh", async () => {
    listedSessions = [session];
    localStorage.setItem(
      "klara_ui_state",
      JSON.stringify({ activeSessionId: "sess_1", sidebarCollapsed: false }),
    );

    render(<App />);

    expect(await screen.findByText("runtime loop")).toBeInTheDocument();
    expect(
      await screen.findByText("Klara completed the runtime loop."),
    ).toBeInTheDocument();
    expect(await screen.findByText(/Developer trace.*3 events.*1 tool/)).toBeInTheDocument();
    expect(screen.getByText("Trace saved")).toBeInTheDocument();
  });

  it("streams a runtime loop answer without a right-side trace panel", async () => {
    const { container } = render(<App />);
    await userEvent.type(
      screen.getByPlaceholderText("Ask your first question..."),
      "run the runtime loop",
    );
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(MockEventSource.instances.length).toBe(1));

    const source = MockEventSource.instances[0];
    source.emit("thinking_started", evt("thinking_started", "Klara is preparing the runtime loop."));
    source.emit(
      "thinking_summary_started",
      evt("thinking_summary_started", "Klara is tracking visible thinking.", {
        started_at: now,
        presentation: "gpt_style_collapsible",
      }),
    );
    source.emit(
      "thinking_summary_delta",
      evt("thinking_summary_delta", "Klara visible thinking summary.", {
        text: "Klara is preparing the observable run from public events.",
        items: [
          {
            id: "act_summary_1",
            title: "Preparing the run",
            body: "Klara is preparing the observable run from public events.",
            status: "completed",
            kind: "orientation",
            source: "narrator_model",
            evidence_event_ids: ["evt_thinking_started"],
          },
          {
            id: "act_summary_2",
            title: "Writing the answer",
            body: "Klara is preparing the final response.",
            status: "completed",
            kind: "composition",
            source: "narrator_model",
            evidence_event_ids: ["evt_thinking_started"],
          },
        ],
        evidence_event_ids: ["evt_thinking_started"],
      }),
    );
    expect(
      screen.queryByText("Klara is preparing the observable run from public events."),
    ).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: /open activity/i }));
    expect(await screen.findByText("Klara thinking")).toBeInTheDocument();
    expect(await screen.findByText("Preparing the run")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /close activity/i }));
    source.emit("llm_call_started", evt("llm_call_started", "Klara is calling the model."));
    source.emit(
      "tool_call_started",
      evt("tool_call_started", "Klara is using current_time.", {
        tool_call: { name: "current_time" },
      }),
    );
    source.emit(
      "tool_call_completed",
      evt("tool_call_completed", "current_time returned.", {
        tool_result: { name: "current_time", ok: true },
      }),
    );
    source.emit(
      "thinking_summary_completed",
      evt("thinking_summary_completed", "Thinking summary completed.", {
        duration_ms: 1200,
        has_summary: true,
      }),
    );
    source.emit("answer_streaming_started", evt("answer_streaming_started", "Klara is writing."));
    const generatedImageUrl =
      "/api/assets/local?path=data/assets/images/20260617/sample.png";
    source.emit(
      "answer_delta",
      evt("answer_delta", "", {
        delta: `![Generated image](${generatedImageUrl})\n\nKlara completed the runtime loop.`,
        streamed_chars: 100,
      }),
    );
    source.emit(
      "run_completed",
      evt("run_completed", "Run completed.", {
        latency_ms: 1200,
        token_source: "reported",
      }),
    );

    expect(await screen.findByText(/Klara completed the runtime loop/)).toBeInTheDocument();
    expect(container.querySelector(".assistant-content")?.textContent).not.toContain(
      "Klara is preparing the observable run from public events.",
    );
    const generatedImage = container.querySelector(".generated-image");
    expect(generatedImage).toHaveAttribute("src", generatedImageUrl);
    fireEvent.error(generatedImage as Element);
    expect(screen.getByText("Generated image unavailable")).toBeInTheDocument();
    expect(screen.queryByText("Run Margin")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /open run trace/i })).not.toBeInTheDocument();
  });
});

function evt(event_type: string, message: string, payload = {}) {
  return {
    event_id: `evt_${event_type}`,
    run_id: "run_1",
    event_type,
    message,
    payload,
    created_at: new Date().toISOString(),
  };
}

function json(body: unknown) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
}
