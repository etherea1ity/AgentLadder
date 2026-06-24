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
  it("shows active thinking with a timer and mini Klara marker", () => {
    render(
      <KlaraThinkingBlock
        run={{
          ...baseRun,
          events: [evt("thinking_summary_started", { started_at: "2026-06-18T12:00:00Z" })],
        }}
      />,
    );

    expect(screen.getByText(/Thinking\.\.\. 1\.2s/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /mini klara/i })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /open activity/i })).not.toBeInTheDocument();
  });

  it("shows the latest live activity item while a run is still thinking", () => {
    render(
      <KlaraThinkingBlock
        run={{
          ...baseRun,
          status: "thinking",
          events: [
            evt("thinking_summary_started", { started_at: "2026-06-18T12:00:00Z" }),
            evt("thinking_summary_delta", {
              items: [
                activity(
                  "act_live_1",
                  "Request understood",
                  "Klara identified the request goal and keeps public activity in one stream.",
                  "narrator_model",
                ),
              ],
            }),
          ],
        }}
      />,
    );

    expect(screen.getByText(/Thinking\.\.\./)).toBeInTheDocument();
    expect(
      screen.getByText(
        "Klara identified the request goal and keeps public activity in one stream.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Live activity")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /open activity/i })).toBeInTheDocument();
  });

  it("shows the live preamble while a run is still thinking", () => {
    render(
      <KlaraThinkingBlock
        run={{
          ...baseRun,
          status: "thinking",
          events: [
            evt("thinking_summary_started", { started_at: "2026-06-18T12:00:00Z" }),
            evt("thinking_preamble_delta", {
              text: "我先理解一下：你是在问今天世界杯的最新情况，我会把可确认的信息整理清楚。",
              source: "narrator_model",
              evidence_event_ids: ["evt_1"],
              confidence: 0.8,
            }),
          ],
        }}
      />,
    );

    expect(screen.getByText(/Thinking\.\.\./)).toBeInTheDocument();
    expect(
      screen.getByText(
        "我先理解一下：你是在问今天世界杯的最新情况，我会把可确认的信息整理清楚。",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /open activity/i })).toBeInTheDocument();
  });

  it("does not show completed Thought when no visible activity exists", () => {
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

  it("shows completed Thought when narrator activity exists", () => {
    render(
      <KlaraThinkingBlock
        run={{
          ...baseRun,
          status: "completed",
          events: [
            evt("thinking_summary_delta", {
              text: "Klara summarized the public trace.",
              items: [
                activity(
                  "act_1",
                  "Request understood",
                  "Klara identified the request goal and prepared a concise response.",
                  "narrator_model",
                ),
              ],
            }),
            evt("thinking_summary_completed", { duration_ms: 4200, has_summary: true }),
          ],
        }}
      />,
    );

    expect(screen.getByText("Thought for 4.2s")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /open activity/i })).toBeInTheDocument();
  });

  it("shows completed Thought when provider reasoning exists", () => {
    render(
      <KlaraThinkingBlock
        run={{
          ...baseRun,
          status: "completed",
          events: [
            evt("provider_reasoning_delta", {
              items: [
                activity(
                  "act_provider_1",
                  "Model thinking",
                  "The provider returned a safe reasoning summary.",
                  "provider_reasoning",
                ),
              ],
            }),
            evt("provider_reasoning_completed", {}),
            evt("thinking_summary_completed", { duration_ms: 800, has_summary: false }),
          ],
        }}
      />,
    );

    expect(screen.getByText("Thought for 800ms")).toBeInTheDocument();
  });

  it("shows completed Thought when only a safe preamble exists", () => {
    render(
      <KlaraThinkingBlock
        run={{
          ...baseRun,
          status: "completed",
          events: [
            evt("thinking_preamble_delta", {
              text: "Klara understood the request and will prepare an answer.",
              source: "narrator_model",
              evidence_event_ids: ["evt_1"],
              confidence: 0.8,
            }),
            evt("thinking_summary_completed", { duration_ms: 1200, has_summary: false }),
          ],
        }}
      />,
    );

    expect(screen.getByText("Thought for 1.2s")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /open activity/i })).toBeInTheDocument();
  });

  it("opens activity only from the right chevron button", () => {
    render(
      <KlaraThinkingBlock
        run={{
          ...baseRun,
          status: "completed",
          events: [
            evt("thinking_summary_delta", {
              items: [
                activity(
                  "act_summary_1",
                  "Request understood",
                  "Klara identified the request goal before answering.",
                  "narrator_model",
                ),
              ],
            }),
            evt("thinking_summary_completed", { duration_ms: 800, has_summary: true }),
          ],
        }}
      />,
    );

    fireEvent.click(screen.getByText("Thought for 800ms"));
    expect(screen.queryByText("Klara activity")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /open activity/i }));
    expect(screen.getByText("Klara activity")).toBeInTheDocument();
    expect(screen.getByText("Request understood")).toBeInTheDocument();
  });

  it("renders provider and narrator activity inside the drawer", () => {
    render(
      <KlaraThinkingBlock
        run={{
          ...baseRun,
          status: "completed",
          events: [
            evt("provider_reasoning_delta", {
              items: [
                activity(
                  "act_provider_1",
                  "Model thinking",
                  "The provider returned a safe reasoning summary.",
                  "provider_reasoning",
                ),
              ],
            }),
            evt("thinking_summary_delta", {
              items: [
                activity(
                  "act_summary_1",
                  "Request understood",
                  "Klara identified the request goal before answering.",
                  "narrator_model",
                ),
              ],
            }),
            evt("thinking_summary_completed", { duration_ms: 800, has_summary: true }),
          ],
        }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /open activity/i }));

    expect(screen.getAllByText("Model thinking").length).toBeGreaterThan(0);
    expect(screen.getByText("Klara activity")).toBeInTheDocument();
    expect(screen.getByText("The provider returned a safe reasoning summary.")).toBeInTheDocument();
    expect(screen.getByText("Request understood")).toBeInTheDocument();
  });

  it("opens an activity drawer for a safe preamble without activity items", () => {
    render(
      <KlaraThinkingBlock
        run={{
          ...baseRun,
          status: "completed",
          events: [
            evt("thinking_preamble_delta", {
              text: "Klara understood the request and will prepare an answer.",
              source: "narrator_model",
              evidence_event_ids: ["evt_1"],
              confidence: 0.8,
            }),
            evt("thinking_summary_completed", { duration_ms: 800, has_summary: false }),
          ],
        }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /open activity/i }));

    expect(screen.getByText("Klara activity")).toBeInTheDocument();
    expect(
      screen.getByText("Klara understood the request and will prepare an answer."),
    ).toBeInTheDocument();
  });

  it("does not render unsafe narrator payload as a public Thought", () => {
    render(
      <KlaraThinkingBlock
        run={{
          ...baseRun,
          status: "completed",
          events: [
            evt("thinking_summary_delta", {
              items: [
                activity(
                  "act_bad_query",
                  "Search query used",
                  "Klara used query arguments against https://example.com/raw.",
                  "narrator_model",
                ),
              ],
            }),
            evt("thinking_summary_completed", { duration_ms: 800, has_summary: true }),
          ],
        }}
      />,
    );

    expect(screen.queryByText(/Thought for/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /open activity/i })).not.toBeInTheDocument();
  });

  it("closes the activity drawer", () => {
    render(
      <KlaraThinkingBlock
        run={{
          ...baseRun,
          status: "completed",
          events: [
            evt("thinking_summary_delta", {
              items: [
                activity(
                  "act_summary_1",
                  "Request understood",
                  "Klara identified the request goal before answering.",
                  "narrator_model",
                ),
              ],
            }),
            evt("thinking_summary_completed", { duration_ms: 800, has_summary: true }),
          ],
        }}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /open activity/i }));
    expect(screen.getByText("Klara activity")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /close activity/i }));

    expect(screen.queryByText("Klara activity")).not.toBeInTheDocument();
  });
});

function activity(
  id: string,
  title: string,
  body: string,
  source: "provider_reasoning" | "narrator_model",
) {
  return {
    id,
    title,
    body,
    status: "completed",
    kind: "orientation",
    source,
    evidence_fact_ids: source === "narrator_model" ? ["fact_1"] : undefined,
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
