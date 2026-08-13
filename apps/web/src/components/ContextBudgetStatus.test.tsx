import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Run } from "../types/domain";
import { ContextBudgetStatus } from "./ChatWorkspace";

function runWith(
  event_type: "context.budget_evaluated" | "context.compacted",
  payload: Record<string, unknown>,
): Run {
  return {
    run_id: "run-context",
    session_id: "session-context",
    user_message_id: "user-context",
    assistant_message_id: "assistant-context",
    status: "completed",
    events: [
      {
        event_id: "event-context",
        run_id: "run-context",
        event_type,
        message: "Context event",
        payload,
        created_at: "2026-08-13T00:00:00Z",
      },
    ],
  };
}

describe("ContextBudgetStatus", () => {
  it("shows compacted counts and a bounded token meter", () => {
    const { container } = render(
      <ContextBudgetStatus
        run={runWith("context.compacted", {
          after_estimated_tokens: 600,
          budget_tokens: 1000,
          messages_summarized: 8,
        })}
      />,
    );

    expect(screen.getByLabelText("Context budget")).toHaveTextContent(
      "Context compacted · 8 older messages summarized",
    );
    expect(screen.getByText("600 / 1,000 est. tokens")).toBeInTheDocument();
    expect(container.querySelector(".context-budget-meter span")).toHaveStyle({
      width: "60%",
    });
  });

  it("renders nothing before a context event exists", () => {
    const { container } = render(<ContextBudgetStatus />);
    expect(container).toBeEmptyDOMElement();
  });
});
