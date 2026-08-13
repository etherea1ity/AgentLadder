# Chapter 17: MCP and External Tools

Language: [Chinese](./ch17-mcp-and-external-tools.md) | English

Previous: [Chapter 16: Subagents, Teams, and Worktrees](../skills/roadmap.md#chapter-16---subagents-teams-and-worktrees)

Next: [Chapter 18: Production Runtime and Evaluation Bridge](./ch18-production-runtime-and-eval-bridge.en.md)

Roadmap: [Klara Roadmap](../skills/roadmap.md)

---

## Chapter in one sentence

Klara can attach standard MCP server tools, resources, and prompts to its existing Agent Runtime, but discovery never implies authority: every external action crosses the Permission Engine, returned content is bounded untrusted data, and credential values never enter configuration, audit, or public traces.

![Klara MCP trust boundary](../assets/ch17-mcp-boundary.svg)

## Quick start

```powershell
.\scripts\dev.ps1 -Restart
```

Open `http://127.0.0.1:5123`, then choose **Integrations** in the sidebar. Configure either a local stdio command with one argument per line or a Streamable HTTP endpoint. An optional credential field stores only an environment-variable name.

**Connect** first creates an exact permission request. Approve it in **Permissions**, connect again, and the page will show the negotiated protocol, server identity, tools, resources, prompts, and health.

Run the deterministic gate with:

```powershell
$env:PYTHONPATH='src'
python -m klara.eval.chapter17_cli `
  --json-out docs/reports/product/ch17-mcp.json `
  --markdown-out docs/reports/product/ch17-mcp.md `
  --markdown-en-out docs/reports/product/ch17-mcp.en.md
```

## 1. Protocol lifecycle

`McpClient.initialize` freezes protocol `2025-11-25`: it sends `initialize`, validates version, capabilities, and serverInfo, then sends `notifications/initialized`. It reads a catalog only when the capability is declared, and bounds both item counts and observations.

The stdio transport uses `shell=False`, a minimal environment, and an isolated temporary working directory. It parses newline-delimited UTF-8 JSON-RPC, drains stderr independently, sends `notifications/cancelled` on timeout, and owns a bounded graceful-to-forced shutdown sequence.

Streamable HTTP sends POST requests with JSON/SSE Accept, Origin, protocol-version, and optional session headers. A returned `Mcp-Session-Id` is used by later requests; close attempts DELETE. Requests on one client are serialized so request IDs and session state cannot race.

## 2. Configuration and credentials

`SQLiteMcpRepository` partitions configuration and content-free audit by tenant and actor. Configuration may persist credential or environment **reference names**, never bearer values. Secret-like stdio arguments and URLs with userinfo, query, or fragment are rejected.

This is not a general secret manager. Deployment supplies actual values through the process environment or a future secret backend; Klara resolves the reference only at the transport boundary.

## 3. Permissions and dynamic tools

Connect, reconnect, disconnect, delete, ping, tool call, resource read, and prompt get all create canonical `PermissionAction` records. Control actions are critical; network reads are medium. Without an exact grant, the service returns `McpPermissionRequired`; the API exposes a 403 and request ID without launching a process or sending a request.

Negotiated tools use the stable name:

```text
mcp__<server-slug>__<tool-slug>
```

Conflicting server slugs are rejected per owner. `RunService` injects only that owner's currently connected tools into each run registry, and the normal PreToolUse Permission Hook still guards them. Tool calls are never automatically replayed because a lost response may follow a real side effect.

## 4. Untrusted observations and audit

The model can see MCP output, but it is wrapped as `untrusted_external_mcp` and explicitly treated as data rather than system or developer instructions. Response and observation sizes are bounded.

Public traces receive separate redacted `public_content`. Audit stores target, result hash, duration, outcome, and public errors—not tool output, resource text, or prompt content. `ToolExecutor` preserves this redaction while normalizing IDs or truncating output.

## 5. Product UI

The Integrations page reads `/api/mcp` state and never fabricates a connected state. Cards show status, last error, catalog, and lifecycle actions. A blocked action says that nothing ran and links to Permissions. The desktop three-column layout collapses to one column on narrow screens.

## 6. Failure and scope boundaries

- timeout, malformed/oversized data, or version mismatch fails closed;
- API shutdown calls `McpService.shutdown`; durable configuration remains and restarts disconnected;
- reconnect is explicit, re-authorized, and never replays a tool side effect;
- OAuth authorization-server behavior, subscriptions, roots/sampling/elicitation, a public marketplace, and experimental MCP tasks remain out of scope.

Chapter 18 adds authenticated multi-user workers, queues, and production persistence without silently widening these external-tool permissions.
