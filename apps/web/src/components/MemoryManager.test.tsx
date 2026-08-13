import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { MemoryManager } from "./MemoryManager";

const now = new Date().toISOString();

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/memory" && (!init || init.method === undefined)) return json({ schema_version: "klara.memory-list.v1", counts_by_kind: { user_preference: 1 }, records: [record("mem-1", "Prefer concise answers")] });
    if (url === "/api/memory" && init?.method === "POST") return json(record("mem-2", "Use dark mode"));
    if (url === "/api/memory/mem-1" && init?.method === "DELETE") return json({ memory_id: "mem-1", deleted: true, deletion_verified: true });
    return json({});
  }));
});

it("supports explicit remember and verified delete", async () => {
  render(<MemoryManager onBackToChat={() => undefined} />);
  expect(await screen.findByText("Prefer concise answers")).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Remember something"), "Use dark mode");
  await userEvent.click(screen.getByRole("button", { name: "Remember" }));
  expect(await screen.findByText("Use dark mode")).toBeInTheDocument();
  await userEvent.click(screen.getAllByRole("button", { name: "Delete memory" })[1]);
  await waitFor(() => expect(screen.queryByText("Prefer concise answers")).not.toBeInTheDocument());
});

function record(memory_id: string, content: string) {
  return { memory_id, scope: { tenant_id: "tenant", user_id: "user" }, kind: "user_preference", content, sensitivity: "standard", provenance: { source_type: "explicit_ui", actor_id: "user" }, created_at: now, updated_at: now, confidence: 1, status: "active", metadata: {} };
}

function json(value: unknown) {
  return Promise.resolve({ ok: true, status: 200, json: async () => value, text: async () => JSON.stringify(value) } as Response);
}
