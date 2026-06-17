import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Run } from "../../types/domain";
import { KlaraRunStatus } from "./KlaraRunStatus";

const baseRun: Run = {
  run_id: "run_1",
  session_id: "sess_1",
  user_message_id: "msg_u",
  assistant_message_id: "msg_a",
  status: "streaming",
  model: "qwen/qwen-flash",
  events: [],
  live: { streamed_chars: 12, current_label: "Writing answer..." },
};

describe("KlaraRunStatus", () => {
  it("renders the single active presence only for the visually active run", () => {
    const { container, rerender } = render(
      <KlaraRunStatus
        run={baseRun}
        visuallyActive
      />,
    );
    expect(container.querySelectorAll(".klara-presence.is-active")).toHaveLength(1);

    rerender(
      <KlaraRunStatus
        run={{ ...baseRun, run_id: "run_2" }}
        visuallyActive={false}
      />,
    );
    expect(container.querySelectorAll(".klara-presence.is-active")).toHaveLength(0);
    expect(container.querySelector(".klara-stamp")).not.toBeNull();
  });

  it("keeps completed runs as a static stamp and keeps run details accessible", () => {
    const { container } = render(
      <KlaraRunStatus
        run={{ ...baseRun, status: "completed", latency_ms: 900 }}
      />,
    );
    expect(container.querySelectorAll(".klara-presence.is-active")).toHaveLength(0);
    expect(container.querySelector(".klara-stamp")).not.toBeNull();
    expect(screen.queryByText(/view run/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/klara status: completed/i)).toBeInTheDocument();
  });
});
