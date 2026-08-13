import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Run, RunEventType } from "../types/domain";
import { ProviderRecoveryStatus } from "./ChatWorkspace";

function runWith(
  events: Array<{ event_type: RunEventType; payload: Record<string, unknown> }>,
): Run {
  return {
    run_id: "run-recovery",
    session_id: "session-recovery",
    user_message_id: "user-recovery",
    assistant_message_id: "assistant-recovery",
    status: "completed",
    events: events.map((event, index) => ({
      event_id: `event-${index}`,
      run_id: "run-recovery",
      message: "Recovery event",
      created_at: "2026-08-13T00:00:00Z",
      ...event,
    })),
  };
}

describe("ProviderRecoveryStatus", () => {
  it("shows an explicit primary-to-fallback route", () => {
    render(
      <ProviderRecoveryStatus
        run={runWith([
          {
            event_type: "model_route.fallback_started",
            payload: {
              failed_model: "deepseek/deepseek-v4-flash",
              fallback_model: "qwen/qwen3.7-plus",
            },
          },
        ])}
      />,
    );

    expect(screen.getByLabelText("Provider recovery")).toHaveTextContent(
      "Fallback active · deepseek-v4-flash → qwen3.7-plus",
    );
  });

  it("shows context recovery when no fallback was needed", () => {
    render(
      <ProviderRecoveryStatus
        run={runWith([
          {
            event_type: "prompt_recovery.completed",
            payload: { attempt: 1 },
          },
        ])}
      />,
    );

    expect(screen.getByLabelText("Provider recovery")).toHaveTextContent(
      "Prompt recovered · context compacted",
    );
  });

  it("renders nothing when a call needed no recovery", () => {
    const { container } = render(<ProviderRecoveryStatus />);
    expect(container).toBeEmptyDOMElement();
  });
});
