# Chapter 2 Freeze - Tool Calling

Date: 2026-06-18

## Frozen Scope

Chapter 2 freezes Klara's first real tool-calling layer:

- `ToolSpec` as the model-visible contract
- `ToolMetadata` as runtime-only policy and tracing metadata
- registry-based tool lookup
- serial and parallel-safe tool execution
- structured success and failure observations
- namespace-safe built-in tools
- web search and web fetch as untrusted network tools
- bounded loop policy loaded from runtime config
- session-local conversation history for the next run
- evidence-state guards for search/fetch discipline
- full-stack chat UI, local API, and dev script path

## Frozen Teaching Claim

Tool calling is not a special answer format. It is a runtime boundary:

```text
model requests tool call
-> runtime validates tool name and arguments
-> runtime executes the tool
-> result returns as an observation
-> model decides the next step
```

The loop owns the run shape. Tools extend capability through explicit contracts.

## Important Boundary Decision

Chapter 2 does not rank websites by hardcoded domain quality.

The web layer should not maintain source-ranking state or source-quality
allowlists. Search providers may return many useful pages, and Klara should
inspect the evidence directly instead of discarding pages because they are not
on a favored domain list.

The remaining guardrail is evidence discipline:

- if a user asks for current facts, search first
- if search snippets are used, fetch relevant pages before final synthesis
- if search fails, try a different query/provider before giving up
- if fetched pages conflict, state what is supported and what is uncertain
- if pages are stale, navigational, or irrelevant, do not turn them into facts

## Verification

Last verified commands:

```powershell
$env:PYTHONPATH='src;.'; pytest tests\klara\core\test_loop.py tests\klara\tools\test_web_tools.py tests\klara\context\test_runtime.py tests\klara\prompts\test_persona.py tests\klara\app\test_harness.py tests\klara\services\test_web_search.py
$env:PYTHONPATH='src;.'; pytest
curl.exe -s http://127.0.0.1:5123/api/health
```

Observed results:

- Targeted Python tests: 31 passed
- Full Python test suite: 79 passed
- Local web/API health check: `{"ok":true}`

## Deferred To Chapter 3

Chapter 3 starts from this freeze and moves lifecycle observability out of the
loop body:

- hook surfaces for lifecycle events
- trace event schema
- UI projection from the same public events
- `UserPromptSubmit`
- `PreToolUse` and `PostToolUse`
- `Stop`
- hook failure isolation
- public versus private hook payloads

Chapter 3 still should not introduce complete permission approval, context
compression, memory write policy, RAG, MCP transport, or a production auth
system.
