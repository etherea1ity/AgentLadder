# Chapter 8 供应商恢复门禁

语言：中文 | [English](./ch08-provider-recovery.live-backtest.en.md)

Status: **PASS**

- 评分器: `klara.chapter08-provider-recovery.v1`
- 门禁类型: `deterministic_fault_injection_gate`
- 检查: `18/18`

## 验收检查

| 检查 | 结果 |
| --- | --- |
| actual_model_is_recorded | PASS |
| bilingual_tutorial_exists | PASS |
| fallback_is_projected_to_api | PASS |
| fallback_route_is_ordered | PASS |
| fallback_uses_second_candidate | PASS |
| frontend_shows_recovery_status | PASS |
| prompt_recovery_compacts | PASS |
| prompt_recovery_refreshes_system_context | PASS |
| prompt_recovery_retries_once | PASS |
| prompt_recovery_trace_is_ordered | PASS |
| provider_body_is_not_public | PASS |
| provider_policy_is_frozen | PASS |
| retry_taxonomy_is_public | PASS |
| retry_trace_is_ordered | PASS |
| stage_manifest_exists | PASS |
| tool_failure_becomes_observation | PASS |
| transient_failure_retries | PASS |
| typed_failure_text_is_not_public | PASS |

## 公开 fallback 证据

```json
{
  "failed_model": "primary/model-a",
  "fallback_model": "fallback/model-b",
  "reason": "provider_unavailable",
  "requested_model": "primary/model-a"
}
```

## 解释边界

通过表示确定性的故障注入已经证明瞬态重试、有上限的退避、类型化公开失败事件、显式 fallback 路由、一次上下文超限压缩重试、工具失败观察和安全的恢复状态 UI。它不代表真实供应商可用率、生产事故响应或学习式恢复策略已经完成。
