import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

class MockEventSource {
  static instances: MockEventSource[] = [];
  listeners: Record<string, ((event: MessageEvent) => void)[]> = {};
  onerror: (() => void) | null = null;
  closed = false;
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
    this.closed = true;
  }
}

const now = new Date().toISOString();
const session = {
  session_id: "sess_1",
  title: "tell me about react",
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
const completedRun = {
  ...runResponse,
  status: "completed",
  latency_ms: 2400,
  trace_saved: true,
  prompt_tokens: 10,
  completion_tokens: 20,
  total_tokens: 30,
  token_source: "reported",
};
const completedMessages = [
  {
    message_id: "msg_u",
    session_id: "sess_1",
    role: "user",
    content: "tell me about react",
    status: "completed",
    created_at: now,
  },
  {
    message_id: "msg_a",
    session_id: "sess_1",
    role: "assistant",
    content: "I’m Klara. Core paper: ReAct: Synergizing Reasoning and Acting in Language Models.",
    run_id: "run_1",
    status: "completed",
    created_at: now,
  },
];

describe("App e2e flow", () => {
  let sessionsVisible = false;
  let failFirstSessionsList = false;
  let sessionsListCalls = 0;
  let runCancelled = false;

  beforeEach(() => {
    localStorage.clear();
    sessionsVisible = false;
    failFirstSessionsList = false;
    sessionsListCalls = 0;
    runCancelled = false;
    MockEventSource.instances = [];
    vi.stubGlobal("EventSource", MockEventSource);
    Object.assign(navigator, {
      clipboard: { writeText: vi.fn(async () => undefined) },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url === "/api/models")
          return json({
            default_model: "qwen3.6-flash",
            models: [
              { id: "flash", model: "qwen3.6-flash", label: "Qwen 3.6 Flash" },
              { id: "plus", model: "qwen3.6-plus", label: "Qwen 3.6 Plus" },
            ],
          });
        if (url === "/api/sessions" && (!init || init.method === undefined)) {
          sessionsListCalls += 1;
          if (failFirstSessionsList && sessionsListCalls === 1)
            throw new TypeError("Backend is warming up");
          return json({ sessions: sessionsVisible ? [session] : [] });
        }
        if (url === "/api/sessions" && init?.method === "POST") {
          sessionsVisible = true;
          return json(session);
        }
        if (url === "/api/runs") return json(runResponse);
        if (url === "/api/runs/run_1/cancel") {
          runCancelled = true;
          return json({ run_id: "run_1", status: "cancelled" });
        }
        if (url === "/api/runs/run_1") {
          const run = runCancelled
            ? { ...completedRun, status: "cancelled" }
            : completedRun;
          const events = runCancelled
            ? [
                evt("run_created", "Run created."),
                evt("run_cancelled", "Run cancelled."),
              ]
            : [
                evt("run_created", "Run created."),
                evt("run_completed", "Run completed.", {
                  latency_ms: 2400,
                  trace_saved: true,
                }),
              ];
          return json({ run, events, trace: { run: { run_id: "run_1" } } });
        }
        if (url === "/api/sessions/sess_1" && init?.method === "DELETE") {
          sessionsVisible = false;
          return json({
            session_id: "sess_1",
            deleted: true,
            deleted_at: new Date().toISOString(),
          });
        }
        if (url === "/api/sessions/sess_1")
          return json({
            session,
            messages: completedMessages,
            runs: [completedRun],
          });
        return json({});
      }),
    );
  });
  afterEach(() => vi.restoreAllMocks());

  it("keeps the New Chat home on first load while listing existing conversations", async () => {
    sessionsVisible = true;
    render(<App />);
    await waitFor(() =>
      expect(screen.getByTitle("tell me about react")).toBeInTheDocument(),
    );
    expect(
      screen.getByPlaceholderText("Ask your first question..."),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    expect(
      screen.queryByText("I’m Klara. Core paper: ReAct: Synergizing Reasoning and Acting in Language Models."),
    ).not.toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalledWith(
      "/api/sessions/sess_1",
      expect.anything(),
    );
    expect(screen.queryByText("Run Margin")).not.toBeInTheDocument();
  });

  it("retries the initial conversation list while the backend warms up", async () => {
    sessionsVisible = true;
    failFirstSessionsList = true;
    render(<App />);
    await waitFor(() =>
      expect(screen.getByTitle("tell me about react")).toBeInTheDocument(),
    );
    expect(
      screen.getByPlaceholderText("Ask your first question..."),
    ).toBeInTheDocument();
    expect(sessionsListCalls).toBeGreaterThanOrEqual(2);
  });

  it("asks, streams, opens Run Margin, completes, and closes details", async () => {
    render(<App />);
    await userEvent.type(
      screen.getByPlaceholderText("Ask your first question..."),
      "tell me about react",
    );
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(MockEventSource.instances.length).toBe(1));
    const source = MockEventSource.instances[0];
    source.emit(
      "thinking_started",
      evt("thinking_started", "Understanding your question..."),
    );
    source.emit(
      "answer_streaming_started",
      evt("answer_streaming_started", "Answer is streaming..."),
    );
    source.emit(
      "answer_delta",
      evt("answer_delta", "", { delta: "I’m Klara. Core paper: ReAct ", streamed_chars: 15 }),
    );
    source.emit(
      "run_completed",
      evt("run_completed", "Run completed.", {
        latency_ms: 2400,
        trace_saved: true,
        prompt_tokens: 10,
        completion_tokens: 20,
        total_tokens: 30,
      }),
    );
    expect(await screen.findByText(/I’m Klara/)).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: /open run trace/i }),
    );
    expect(screen.getByText("Run Margin")).toBeInTheDocument();
    expect(screen.getByText("Klara Run · Summary")).toBeInTheDocument();
    expect(screen.getByText("LLM Call")).toBeInTheDocument();
    expect(screen.getAllByText("input tokens").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("output tokens").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("2.4s").length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText("Presence mock runs")).not.toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: /run trace is open/i }),
    );
    expect(screen.getByText("Run Margin")).toBeInTheDocument();
    await userEvent.click(
      screen.getByRole("button", { name: /close run margin/i }),
    );
    expect(screen.queryByText("Run Margin")).not.toBeInTheDocument();
  });

  it("ignores Enter while a run is active and only stops through the Stop button", async () => {
    render(<App />);
    await userEvent.type(
      screen.getByPlaceholderText("Ask your first question..."),
      "tell me about react",
    );
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(MockEventSource.instances.length).toBe(1));

    const activeInput = screen.getByPlaceholderText("Ask anything...");
    activeInput.focus();
    await userEvent.keyboard("{Enter}");
    expect(fetch).not.toHaveBeenCalledWith(
      "/api/runs/run_1/cancel",
      expect.anything(),
    );

    await userEvent.click(screen.getByRole("button", { name: "Stop run" }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/runs/run_1/cancel",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });

  it("deletes the active conversation through the backend and returns home", async () => {
    render(<App />);
    await userEvent.type(
      screen.getByPlaceholderText("Ask your first question..."),
      "tell me about react",
    );
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() =>
      expect(
        screen.getAllByText("tell me about react").length,
      ).toBeGreaterThan(0),
    );
    const sidebarItem = screen
      .getByTitle("tell me about react")
      .closest(".conversation-item") as HTMLElement;
    await userEvent.click(
      within(sidebarItem).getByLabelText("Conversation actions"),
    );
    await userEvent.click(
      within(sidebarItem).getByRole("button", { name: "Delete" }),
    );
    await userEvent.click(
      within(sidebarItem).getByRole("button", { name: "Delete" }),
    );
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/sessions/sess_1",
        expect.objectContaining({ method: "DELETE" }),
      ),
    );
    await waitFor(() =>
      expect(screen.getByAltText("Klara Agent System")).toBeInTheDocument(),
    );
    expect(
      screen.getByPlaceholderText("Ask your first question..."),
    ).toBeInTheDocument();
  });

  it("reconciles a run if the SSE stream drops before completion", async () => {
    render(<App />);
    await userEvent.type(
      screen.getByPlaceholderText("Ask your first question..."),
      "tell me about react",
    );
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(MockEventSource.instances.length).toBe(1));
    MockEventSource.instances[0].emit(
      "answer_delta",
      evt("answer_delta", "", { delta: "Partial ", streamed_chars: 8 }),
    );
    MockEventSource.instances[0].onerror?.();
    await waitFor(() =>
      expect(screen.getAllByText(/^Completed$/).length).toBeGreaterThan(0),
    );
    await userEvent.click(
      screen.getByRole("button", { name: /open run trace/i }),
    );
    expect(screen.getByText("Run Margin")).toBeInTheDocument();
  });

  it("collapses and expands the left sidebar", async () => {
    render(<App />);
    const initialCollapseButtons = screen.queryAllByRole("button", {
      name: /collapse sidebar/i,
    });
    if (initialCollapseButtons.length > 0) {
      await userEvent.click(initialCollapseButtons[0]);
      expect(
        screen.getAllByRole("button", { name: /expand sidebar/i }).length,
      ).toBeGreaterThan(0);
    }
    await userEvent.click(
      screen.getAllByRole("button", { name: /expand sidebar/i })[0],
    );
    expect(
      screen.getAllByRole("button", { name: /collapse sidebar/i }).length,
    ).toBeGreaterThan(0);
  });

  it("copies answers, toggles exclusive feedback, and chooses a configured model", async () => {
    render(<App />);
    await waitFor(() =>
      expect(screen.getAllByText("Qwen 3.6 Flash").length).toBeGreaterThan(0),
    );
    await userEvent.click(screen.getByLabelText(/choose model/i));
    await userEvent.click(
      screen.getByRole("button", {
        name: /Qwen 3\.6 Plus\s+qwen3\.6-plus/i,
      }),
    );
    await userEvent.type(
      screen.getByPlaceholderText("Ask your first question..."),
      "tell me about react",
    );
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/runs",
        expect.objectContaining({
          body: expect.stringContaining("qwen3.6-plus"),
        }),
      ),
    );
    await waitFor(() => expect(MockEventSource.instances.length).toBe(1));
    MockEventSource.instances[0].emit(
      "answer_delta",
      evt("answer_delta", "", { delta: "Answer text", streamed_chars: 11 }),
    );
    MockEventSource.instances[0].emit(
      "run_completed",
      evt("run_completed", "Run completed.", {
        latency_ms: 1000,
        trace_saved: true,
        prompt_tokens: 5,
        completion_tokens: 3,
        total_tokens: 8,
        token_source: "estimated",
      }),
    );

    await userEvent.click(
      await screen.findByRole("button", { name: /copy answer/i }),
    );
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("Answer text");
    const like = screen.getByRole("button", { name: /^Like answer$/i });
    const dislike = screen.getByRole("button", { name: /^Dislike answer$/i });
    await userEvent.click(like);
    expect(like).toHaveAttribute("aria-pressed", "true");
    expect(dislike).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(dislike);
    expect(like).toHaveAttribute("aria-pressed", "false");
    expect(dislike).toHaveAttribute("aria-pressed", "true");
  });

  it("renders markdown math output from bracket-style formulas", async () => {
    render(<App />);
    await userEvent.type(
      screen.getByPlaceholderText("Ask your first question..."),
      "Show Fourier formula",
    );
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(MockEventSource.instances.length).toBe(1));
    MockEventSource.instances[0].emit(
      "answer_delta",
      evt("answer_delta", "", {
        delta: "[ F(\\\\omega) = \\\\int f(t)e^{-j\\\\omega t}\\\\,dt ]",
        streamed_chars: 48,
      }),
    );
    await waitFor(() =>
      expect(document.querySelector(".katex")).not.toBeNull(),
    );
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
