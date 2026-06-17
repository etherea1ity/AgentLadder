import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ChatWorkspace } from "./ChatWorkspace";
import { Sidebar } from "./Sidebar";
import type { ModelOption, Session } from "../types/domain";

const now = new Date("2026-06-16T08:00:00.000Z").toISOString();

const modelOptions: ModelOption[] = [
  {
    id: "qwen/qwen3.7-plus",
    model: "qwen/qwen3.7-plus",
    label: "Qwen3.7 Plus",
  },
  {
    id: "qwen/qwen3.7-max",
    model: "qwen/qwen3.7-max",
    label: "Qwen3.7 Max",
  },
];

const session: Session = {
  session_id: "sess_1",
  title: "runtime loop",
  created_at: now,
  updated_at: now,
  message_ids: [],
};

describe("popover dismissal", () => {
  it("closes the model picker on outside click and after choosing a model", async () => {
    const user = userEvent.setup();
    const onModelChange = vi.fn();

    render(
      <ChatWorkspace
        activeSessionId={null}
        messages={[]}
        runs={{}}
        input=""
        running={false}
        submitting={false}
        cancelling={false}
        onInput={vi.fn()}
        onSend={vi.fn()}
        onStop={vi.fn()}
        modelOptions={modelOptions}
        selectedModel="qwen/qwen3.7-plus"
        onModelChange={onModelChange}
        theme="light"
        onToggleTheme={vi.fn()}
      />,
    );

    const pickerSummary = screen.getByLabelText("Choose model");
    const picker = pickerSummary.closest("details");

    await user.click(pickerSummary);
    expect(picker).toHaveAttribute("open");

    await user.click(document.body);
    await waitFor(() => expect(picker).not.toHaveAttribute("open"));

    await user.click(pickerSummary);
    expect(picker).toHaveAttribute("open");
    await user.click(screen.getByRole("button", { name: /Qwen3.7 Max/i }));

    expect(onModelChange).toHaveBeenCalledWith("qwen/qwen3.7-max");
    await waitFor(() => expect(picker).not.toHaveAttribute("open"));
  });

  it("closes the conversation delete confirmation from outside click and Escape", async () => {
    const user = userEvent.setup();

    render(
      <Sidebar
        sessions={[session]}
        activeSessionId="sess_1"
        collapsed={false}
        onToggleCollapsed={vi.fn()}
        onNewChat={vi.fn()}
        onSelect={vi.fn()}
        onRename={vi.fn()}
        onDelete={vi.fn()}
      />,
    );

    const menuSummary = screen.getByLabelText("Conversation actions");
    const menu = menuSummary.closest("details");

    await user.click(menuSummary);
    await user.click(screen.getByRole("button", { name: "Delete" }));
    expect(screen.getByText("Delete this conversation?")).toBeInTheDocument();

    await user.click(document.body);
    await waitFor(() => expect(menu).not.toHaveAttribute("open"));
    expect(screen.queryByText("Delete this conversation?")).not.toBeInTheDocument();

    await user.click(menuSummary);
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.keyboard("{Escape}");

    await waitFor(() => expect(menu).not.toHaveAttribute("open"));
    expect(screen.queryByText("Delete this conversation?")).not.toBeInTheDocument();
  });
});
