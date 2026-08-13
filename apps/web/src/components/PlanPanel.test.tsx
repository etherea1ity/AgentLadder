import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PlanPanel } from "./ChatWorkspace";

describe("PlanPanel", () => {
  it("shows ordered state, progress, and version without exposing internal ids", () => {
    const { container } = render(
      <PlanPanel
        plan={{
          schema_version: "klara.todo-plan.v1",
          session_id: "sess-secret",
          version: 3,
          updated_at: "2026-08-13T00:00:00Z",
          items: [
            { id: "inspect", title: "Inspect repository", status: "completed" },
            { id: "build", title: "Build planning", status: "in_progress" },
            { id: "verify", title: "Verify behavior", status: "pending" },
          ],
        }}
      />,
    );

    expect(screen.getByLabelText("Current plan")).toBeInTheDocument();
    expect(screen.getByText("1 of 3 done")).toBeInTheDocument();
    expect(screen.getByText("Build planning")).toBeInTheDocument();
    expect(screen.getByText("In progress")).toBeInTheDocument();
    expect(screen.queryByText("sess-secret")).not.toBeInTheDocument();
    expect(container.querySelector(".todo-plan-progress span")).toHaveStyle({ width: "33%" });
  });

  it("renders nothing for absent or empty plans", () => {
    const { container, rerender } = render(<PlanPanel plan={null} />);
    expect(container).toBeEmptyDOMElement();
    rerender(
      <PlanPanel
        plan={{
          schema_version: "klara.todo-plan.v1",
          session_id: "sess-1",
          version: 1,
          updated_at: "2026-08-13T00:00:00Z",
          items: [],
        }}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
