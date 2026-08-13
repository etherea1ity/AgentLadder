import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EvidenceStatus } from "./ChatWorkspace";
import type { Run } from "../types/domain";

function runWithEvidence(payload: Record<string, unknown>): Run {
  return {
    run_id: "run-evidence",
    session_id: "session-1",
    user_message_id: "user-1",
    assistant_message_id: "assistant-1",
    status: "completed",
    model: "fixture/model",
    events: [
      {
        event_id: "source-1",
        run_id: "run-evidence",
        event_type: "evidence.source_recorded",
        message: "Fetched source recorded.",
        payload: { source_id: "src-1" },
        created_at: "2026-08-13T00:00:00Z",
      },
      {
        event_id: "verify-1",
        run_id: "run-evidence",
        event_type: "evidence.verification_completed",
        message: "Evidence verified.",
        payload,
        created_at: "2026-08-13T00:00:01Z",
      },
    ],
  };
}

describe("EvidenceStatus", () => {
  it("shows source and claim verification counts", () => {
    render(
      <EvidenceStatus
        run={runWithEvidence({
          allowed: true,
          abstained: false,
          claims: [
            { claim_id: "claim-1", judgment: "supported", source_ids: ["src-1"] },
          ],
        })}
      />,
    );

    expect(screen.getByText("Evidence verified")).toBeInTheDocument();
    expect(screen.getByText(/1 fetched source/)).toBeInTheDocument();
    expect(screen.getByText(/1\/1 claims supported/)).toBeInTheDocument();
  });

  it("labels an explicit abstention without presenting it as verified facts", () => {
    render(
      <EvidenceStatus
        run={runWithEvidence({ allowed: true, abstained: true, claims: [] })}
      />,
    );

    expect(screen.getByText("Evidence-limited answer")).toBeInTheDocument();
  });
});
