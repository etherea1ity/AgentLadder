# Chapter 4 Harness 与 Config 门禁

语言：中文 | [English](./ch04-harness-config.en.md)

Status: **PASS**

- 评分器: `klara.chapter04-harness-config.v1`
- 运行快照 hash: `05466ded8d81b72cb95432e0aa7229071bb00d596573b73c6f7a8e2540fb0bfa`
- 模型: `qwen/qwen-flash`

## 验收检查

| 检查 | 结果 |
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

## 冻结运行快照

```json
{
  "capability_profile": "agent",
  "context_policy": {
    "chars_per_token": 4,
    "max_input_tokens": 16000,
    "minimum_recent_messages": 4,
    "recent_messages": 10,
    "reserved_output_tokens": 3500,
    "reserved_system_tokens": 2500,
    "summary_max_chars": 2400,
    "tool_result_max_chars": 1200,
    "transcript_budget_tokens": 10000
  },
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
  "profile_sha256": "05466ded8d81b72cb95432e0aa7229071bb00d596573b73c6f7a8e2540fb0bfa",
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

## 解释边界

通过证明本地产品入口共享同一份不可变、经过能力检查且不含密钥的 harness 组装；它不评估付费模型质量，也不代表后续 Agent 章节已完成。
