import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { PermissionCenter } from "./PermissionCenter";

const fetchMock = vi.fn();
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

it("shows exact risky scope and saves allow-once approval", async () => {
  const pending = {
    schema_version: "klara.permissions-state.v1",
    requests: [{
      request_id: "preq_1", fingerprint: "f", status: "pending", created_at: "2026-08-13T00:00:00Z", updated_at: "2026-08-13T00:00:00Z", expires_at: "2026-08-14T00:00:00Z", repeated_count: 2,
      scope: { tenant_id: "t", actor_id: "u", agent_id: "klara", task_id: "run_1" },
      action: { tool_name: "web_fetch", capability: "web.web_fetch", side_effect: "network", resource_type: "domain", resource: "https://example.com/docs", risk: "medium", destructive: false, externally_consequential: true, arguments_sha256: "a".repeat(64) },
    }],
    grants: [], audit: [],
  };
  const decided = { ...pending, requests: [], grants: [{ grant_id: "g", request_id: "preq_1", effect: "allow_once", status: "active", scope: pending.requests[0].scope, action: pending.requests[0].action, created_at: "2026-08-13T00:00:00Z", expires_at: "2026-08-13T00:15:00Z", remaining_uses: 1 }] };
  fetchMock
    .mockResolvedValueOnce({ ok: true, json: async () => pending })
    .mockResolvedValueOnce({ ok: true, json: async () => decided.grants[0] })
    .mockResolvedValueOnce({ ok: true, json: async () => decided });

  render(<PermissionCenter onBackToChat={() => undefined} />);
  expect(await screen.findByText("https://example.com/docs")).toBeInTheDocument();
  expect(screen.getByText("2×")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Allow once" }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3));
  expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ effect: "allow_once", expires_seconds: 900 });
  expect(await screen.findByText("No approval is waiting. Klara has not inferred any permission.")).toBeInTheDocument();
});

it("keeps risky actions blocked when permission state cannot load", async () => {
  fetchMock.mockRejectedValueOnce(new Error("offline"));
  render(<PermissionCenter onBackToChat={() => undefined} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("remain blocked");
});
