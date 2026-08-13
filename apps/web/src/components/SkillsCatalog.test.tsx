import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { SkillsCatalog } from "./SkillsCatalog";

afterEach(() => vi.restoreAllMocks());

it("shows metadata-first loading and permission boundaries", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
    schema_version: "klara.skills-catalog.v1",
    precedence: ["project", "user", "built_in"],
    body_loading: "on_demand",
    skills: [{
      name: "repository-work",
      description: "Inspect a repository before changing code.",
      version: "1.0.0",
      scope: "built_in",
      source: "built_in:repository_work",
      sha256: "a".repeat(64),
      tools: [],
      permissions: [],
      dependencies: [],
      references: ["references/checklist.md"],
      shadowed_scopes: [],
    }],
  }), { headers: { "Content-Type": "application/json" } })));

  render(<SkillsCatalog onBackToChat={() => undefined} />);

  expect(await screen.findByRole("heading", { name: "Skills" })).toBeInTheDocument();
  expect(await screen.findByText("repository-work")).toBeInTheDocument();
  expect(screen.getByText("Bodies load on demand")).toBeInTheDocument();
  expect(screen.getByText("Permissions fail closed")).toBeInTheDocument();
  expect(screen.queryByText("private procedure body")).not.toBeInTheDocument();
});
