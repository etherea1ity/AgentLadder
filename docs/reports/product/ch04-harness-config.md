# Chapter 4 Harness 与 Config 门禁

语言：中文 | [English](./ch04-harness-config.en.md)

Status: **PASS**

- 评分器: `klara.chapter04-harness-config.v1`
- 运行快照 hash: `de55caea7d51be41d9ea32db5896086ea20e4f3c0b12fa69872d1aed2fe49401`
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

## 解释边界

通过证明本地产品入口共享同一份不可变、经过能力检查且不含密钥的 harness 组装；它不评估付费模型质量，也不代表后续 Agent 章节已完成。
