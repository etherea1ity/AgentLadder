# Chapter 4 Harness and Config Gate

Language: [Chinese](./ch04-harness-config.md) | English

Status: **PASS**

- Scorer: `klara.chapter04-harness-config.v1`
- Profile hash: `de55caea7d51be41d9ea32db5896086ea20e4f3c0b12fa69872d1aed2fe49401`
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
  "persona_sha256": "25ba67f787134c5376aad70693303223d0c6a8e375382d687f3c267b4086e7f1",
  "profile_sha256": "de55caea7d51be41d9ea32db5896086ea20e4f3c0b12fa69872d1aed2fe49401",
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
    "update_activity"
  ]
}
```

## Interpretation Boundary

Passing proves that local product entrypoints share one frozen, capability-checked, secret-free harness assembly. It does not test paid provider quality or later Agent chapters.
