import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
let sessionDetailResponse: unknown;
let runDetailResponse: unknown;

describe("Klara app flow", () => {
  beforeEach(() => {
    localStorage.clear();
    MockEventSource.instances = [];
    listedSessions = [];
    sessionDetailResponse = {
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
      todo_plan: {
        schema_version: "klara.todo-plan.v1",
        session_id: "sess_1",
        version: 2,
        updated_at: now,
        items: [
          { id: "inspect", title: "Inspect repository", status: "completed" },
          { id: "build", title: "Build the runtime", status: "in_progress" },
        ],
      },
    };
    runDetailResponse = {
      run: {
        ...runResponse,
        status: "completed",
        latency_ms: 1200,
        trace_saved: true,
      },
      events: [],
      trace: null,
    };
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
        if (url === "/api/evaluations/summary")
          return json({
            available: true,
            status: "passed",
            gate_kind: "contract_control_probe",
            interpretation: "Control probe only.",
            scorer_version: "klara.behavior-scorer.v1",
            evaluated_at: now,
            counts: { observations: 24 },
            metrics: {
              normal_task_success_rate: 1,
              critical_deterministic_rate: 1,
              reference_gap: 0,
              human_acceptability_rate: 1,
            },
            checks: { p0_zero: true },
            split_hashes: { validation: "a".repeat(64) },
          });
        if (url === "/api/sessions" && (!init || init.method === undefined)) return json({ sessions: listedSessions });
        if (url === "/api/sessions" && init?.method === "POST") return json(session);
        if (url === "/api/runs") return json(runResponse);
        if (url === "/api/runs/run_1") return json(runDetailResponse);
        if (url === "/api/sessions/sess_1") return json(sessionDetailResponse);
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
    expect(await screen.findByText(/Developer debug.*3 events.*1 tool/)).toBeInTheDocument();
    expect(screen.getByText("Trace saved")).toBeInTheDocument();
    expect(screen.getByLabelText("Current plan")).toBeInTheDocument();
    expect(screen.getByText("1 of 2 done")).toBeInTheDocument();
  });

  it("streams a runtime loop answer without a right-side trace panel", async () => {
    const { container } = render(<App />);
    await userEvent.type(
      screen.getByPlaceholderText("Ask your first question..."),
      "run the runtime loop",
    );
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(MockEventSource.instances.length).toBe(1));
    const runRequest = vi
      .mocked(fetch)
      .mock.calls.find(([url]) => url === "/api/runs");
    const runPayload = JSON.parse(String(runRequest?.[1]?.body));
    expect(runPayload.client_context.timestamp).toEqual(expect.any(String));
    expect(runPayload.client_context.timezone).toEqual(expect.any(String));
    expect(runPayload.client_context.utc_offset_minutes).toEqual(expect.any(Number));

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
      "provider_reasoning_delta",
      evt("provider_reasoning_delta", "Provider reasoning summary received.", {
        items: [
          {
            id: "provider_1",
            title: "Provider reasoning",
            body: "The provider returned a safe reasoning summary.",
            status: "completed",
            kind: "orientation",
            source: "provider_reasoning",
            evidence_event_ids: ["evt_llm_completed"],
          },
        ],
        evidence_event_ids: ["evt_llm_completed"],
      }),
    );
    expect(
      screen.queryByText("The provider returned a safe reasoning summary."),
    ).not.toBeInTheDocument();
    source.emit(
      "assistant_activity_delta",
      evt("assistant_activity_delta", "", {
        activity_id: "activity_turn_1",
        sequence: 1,
        status: "completed",
        text: "I will check one runtime step before answering.",
        source: "main_model_commentary",
        phase: "before_tool",
        evidence_event_ids: ["evt_llm_completed"],
      }),
    );
    expect(
      await screen.findByText("I will check one runtime step before answering."),
    ).toBeInTheDocument();
    fireEvent.click(
      await screen.findByRole("button", { name: /toggle thinking details/i }),
    );
    await waitFor(() =>
      expect(screen.getByRole("dialog", { name: /thinking/i })).toBeInTheDocument(),
    );
    expect(container.querySelector(".chat-workspace.is-thinking-open")).toBeTruthy();
    expect(
      container.querySelector(".chat-workspace > .klara-thinking-drawer-layer"),
    ).toBeTruthy();
    expect(
      within(screen.getByRole("dialog", { name: /thinking/i })).getByText(
        "The provider returned a safe reasoning summary.",
      ),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /close thinking/i }));
    expect(container.querySelector(".chat-workspace.is-thinking-open")).toBeFalsy();
    expect(container.querySelector(".klara-answer-cursor .klara-presence")).toBeTruthy();
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
      "todo_plan_updated",
      evt("todo_plan_updated", "Plan updated.", {
        schema_version: "klara.todo-plan.v1",
        session_id: "sess_1",
        version: 2,
        updated_at: now,
        items: [
          { id: "inspect", title: "Inspect the runtime", status: "completed" },
          { id: "answer", title: "Write the answer", status: "in_progress" },
        ],
      }),
    );
    expect(await screen.findByText("Write the answer")).toBeInTheDocument();
    source.emit(
      "todo_plan_updated",
      evt("todo_plan_updated", "Stale plan ignored.", {
        schema_version: "klara.todo-plan.v1",
        session_id: "sess_1",
        version: 1,
        updated_at: now,
        items: [{ id: "stale", title: "Stale plan", status: "in_progress" }],
      }),
    );
    expect(screen.queryByText("Stale plan")).not.toBeInTheDocument();
    expect(screen.getByText("Write the answer")).toBeInTheDocument();
    source.emit(
      "thinking_summary_completed",
      evt("thinking_summary_completed", "Thinking summary completed.", {
        duration_ms: 1200,
        has_summary: true,
      }),
    );
    source.emit("answer_streaming_started", evt("answer_streaming_started", "Klara is writing."));
    await waitFor(() =>
      expect(container.querySelector(".klara-answer-cursor .klara-presence")).toBeTruthy(),
    );
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
    await waitFor(() => expect(container.querySelector(".klara-answer-cursor")).toBeFalsy());
    expect(container.querySelector(".assistant-content")?.textContent).not.toContain(
      "Klara summarized a public tool step.",
    );
    const generatedImage = container.querySelector(".generated-image");
    expect(generatedImage).toHaveAttribute("src", generatedImageUrl);
    fireEvent.error(generatedImage as Element);
    expect(screen.getByText("Generated image unavailable")).toBeInTheDocument();
    expect(screen.queryByText("Run Margin")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /open run trace/i })).not.toBeInTheDocument();
  });

  it("keeps the desktop sidebar collapsed after sending from the empty view", async () => {
    localStorage.setItem(
      "klara_ui_state",
      JSON.stringify({ activeSessionId: null, sidebarCollapsed: true }),
    );

    const { container } = render(<App />);
    await userEvent.type(
      screen.getByPlaceholderText("Ask your first question..."),
      "keep the rail quiet",
    );
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(MockEventSource.instances.length).toBe(1));

    expect(container.querySelector(".app-shell")).toHaveClass("sidebar-collapsed");
  });

  it("opens aggregate evaluations and returns to chat", async () => {
    render(<App />);

    await userEvent.click(screen.getByRole("button", { name: "Evaluations" }));
    expect(await screen.findByRole("heading", { name: "Agent evaluations" })).toBeInTheDocument();
    expect(await screen.findByText("Contract gate passed")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Back to chat" }));
    expect(await screen.findByPlaceholderText("Ask your first question...")).toBeInTheDocument();
  });

  it("keeps live thinking after a failed run is reconciled from a sparse snapshot", async () => {
    render(<App />);
    await userEvent.type(
      screen.getByPlaceholderText("Ask your first question..."),
      "run a long research task",
    );
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(MockEventSource.instances.length).toBe(1));

    const source = MockEventSource.instances[0];
    source.emit(
      "assistant_activity_delta",
      evt("assistant_activity_delta", "", {
        text: "I will search current sources before writing the answer.",
        source: "main_model_commentary",
        phase: "before_tool",
        evidence_event_ids: ["evt_llm"],
      }),
    );
    expect(
      await screen.findByText(
        "I will search current sources before writing the answer.",
      ),
    ).toBeInTheDocument();

    runDetailResponse = {
      run: {
        ...runResponse,
        status: "failed",
        latency_ms: 2500,
        error: {
          code: "provider_error",
          message: "provider request failed: The read operation timed out",
          stage: "runtime_loop",
        },
      },
      events: [],
      trace: null,
    };
    sessionDetailResponse = {
      session,
      messages: [
        {
          message_id: "msg_u",
          session_id: "sess_1",
          role: "user",
          content: "run a long research task",
          status: "completed",
          created_at: now,
        },
        {
          message_id: "msg_a",
          session_id: "sess_1",
          role: "assistant",
          content: "",
          run_id: "run_1",
          status: "failed",
          created_at: now,
        },
      ],
      runs: [{ ...runResponse, status: "failed", latency_ms: 2500 }],
      events: [],
    };

    source.emit(
      "run_failed",
      evt("run_failed", "Run failed.", {
        error: {
          code: "provider_error",
          message: "provider request failed: The read operation timed out",
          stage: "runtime_loop",
        },
        latency_ms: 2500,
      }),
    );
    source.onerror?.();

    await waitFor(() =>
      expect(
        screen.getByText(
          "I will search current sources before writing the answer.",
        ),
      ).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByRole("button", { name: /toggle thinking details/i }));
    expect(
      within(screen.getByRole("dialog", { name: /thinking/i })).getByText(
        "I will search current sources before writing the answer.",
      ),
    ).toBeInTheDocument();
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
