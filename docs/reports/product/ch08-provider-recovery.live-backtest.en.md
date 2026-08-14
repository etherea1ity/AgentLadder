# Chapter 8 Provider Recovery Gate

Language: [Chinese](./ch08-provider-recovery.live-backtest.md) | English

Status: **PASS**

- Scorer: `klara.chapter08-provider-recovery.v1`
- Gate kind: `deterministic_fault_injection_gate`
- Checks: `18/18`

## Acceptance Checks

| Check | Result |
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

## Public Fallback Evidence

```json
{
  "failed_model": "primary/model-a",
  "fallback_model": "fallback/model-b",
  "reason": "provider_unavailable",
  "requested_model": "primary/model-a"
}
```

## Interpretation Boundary

Passing proves deterministic transient retry, bounded backoff, typed public failure events, explicit fallback routing, one context-length compaction retry, tool-failure observations, and a safe recovery UI. It uses fault injection and does not claim live-provider uptime, production incident response, or a learned policy.
