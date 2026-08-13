# Chapter 4 Harness and Config Gate

Language: [Chinese](./ch04-harness-config.md) | English

Status: **PASS**

- Scorer: `klara.chapter04-harness-config.v1`
- Profile hash: `6bf6f90021dfb5d1005916f431e258f6f37d9a43bf7e474eba056b669d54ec60`
- Model: `qwen/qwen-flash`

## Acceptance Checks

| Check | Result |
| --- | --- |
| api_uses_harness | PASS |
| cli_uses_harness | PASS |
| hooks_and_trace_declared | PASS |
| model_supports_profile | PASS |
| persona_hash_valid | PASS |
| profile_hash_valid | PASS |
| profile_schema_frozen | PASS |
| provider_connection_details_absent | PASS |
| required_tools_visible | PASS |
| secret_values_absent | PASS |
| stage_manifest_exists | PASS |

## Frozen Profile

```json
{
  "capability_profile": "agent",
  "hooks": [
    "run_projection",
    "jsonl_trace"
  ],
  "locale": "en-US",
  "loop_policy": {
    "max_repeated_final_blocks": 2,
    "max_repeated_tool_calls": 3,
    "max_tool_calls": 48,
    "max_turns": 24
  },
  "model": "qwen/qwen-flash",
  "persona_sha256": "9f346d86d01228e1f764350b2915250431121bf43d5cc300046ee79c30eb7680",
  "profile_sha256": "6bf6f90021dfb5d1005916f431e258f6f37d9a43bf7e474eba056b669d54ec60",
  "required_model_capabilities": [
    "tools"
  ],
  "schema_version": "klara.run-profile.v1",
  "thinking_enabled": null,
  "timezone": "local",
  "trace_sink": "jsonl",
  "user_partition": "local-user",
  "visible_tools": [
    "current_time",
    "image_generate",
    "web_fetch",
    "web_search",
    "todo_write",
    "update_activity"
  ]
}
```

## Interpretation Boundary

Passing proves that local product entrypoints share one frozen, capability-checked, secret-free harness assembly. It does not test paid provider quality or later Agent chapters.
