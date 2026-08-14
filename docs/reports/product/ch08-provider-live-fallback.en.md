# Chapter 8 Live Provider Fallback

Language: [Chinese](./ch08-provider-live-fallback.md) | English

- Verdict: `PASS`
- Requested model: `qwen/qwen3.7-flash`
- Actual model: `deepseek/deepseek-v4-flash`
- Duration: `14434 ms`

## Acceptance Checks

| Check | Result |
| --- | --- |
| deepseek_fallback_completed | PASS |
| fallback_event_order_is_public | PASS |
| fallback_tool_call_is_exact | PASS |
| qwen_auth_failure_is_typed | PASS |
| qwen_is_frozen_primary | PASS |
| qwen_siblings_are_skipped_after_auth_failure | PASS |
| usage_is_reported | PASS |

## Public Runtime Events

```json
[
  {
    "type": "model_route.candidate_started",
    "payload": {
      "requested_model": "qwen/qwen3.7-flash",
      "candidate_model": "qwen/qwen3.7-flash",
      "candidate_index": 0,
      "candidate_count": 7
    }
  },
  {
    "type": "provider.attempt_started",
    "payload": {
      "provider": "qwen",
      "model": "qwen/qwen3.7-flash",
      "attempt": 1,
      "max_attempts": 1,
      "timeout_seconds": 60
    }
  },
  {
    "type": "provider.attempt_failed",
    "payload": {
      "provider": "qwen",
      "model": "qwen/qwen3.7-flash",
      "attempt": 1,
      "error_code": "provider_authentication_failed",
      "retryable": false,
      "status_code": 401
    }
  },
  {
    "type": "model_route.candidate_failed",
    "payload": {
      "requested_model": "qwen/qwen3.7-flash",
      "candidate_model": "qwen/qwen3.7-flash",
      "candidate_index": 0,
      "error_code": "provider_authentication_failed",
      "retryable": false,
      "status_code": 401
    }
  },
  {
    "type": "model_route.fallback_started",
    "payload": {
      "requested_model": "qwen/qwen3.7-flash",
      "failed_model": "qwen/qwen3.7-flash",
      "fallback_model": "qwen/qwen3.7-plus",
      "reason": "provider_authentication_failed"
    }
  },
  {
    "type": "model_route.candidate_skipped",
    "payload": {
      "requested_model": "qwen/qwen3.7-flash",
      "candidate_model": "qwen/qwen3.7-plus",
      "candidate_index": 1,
      "reason": "provider_authentication_circuit_open"
    }
  },
  {
    "type": "model_route.fallback_started",
    "payload": {
      "requested_model": "qwen/qwen3.7-flash",
      "failed_model": "qwen/qwen3.7-plus",
      "fallback_model": "qwen/qwen3.6-plus",
      "reason": "provider_authentication_circuit_open"
    }
  },
  {
    "type": "model_route.candidate_skipped",
    "payload": {
      "requested_model": "qwen/qwen3.7-flash",
      "candidate_model": "qwen/qwen3.6-plus",
      "candidate_index": 2,
      "reason": "provider_authentication_circuit_open"
    }
  },
  {
    "type": "model_route.fallback_started",
    "payload": {
      "requested_model": "qwen/qwen3.7-flash",
      "failed_model": "qwen/qwen3.6-plus",
      "fallback_model": "qwen/qwen3.7-max",
      "reason": "provider_authentication_circuit_open"
    }
  },
  {
    "type": "model_route.candidate_skipped",
    "payload": {
      "requested_model": "qwen/qwen3.7-flash",
      "candidate_model": "qwen/qwen3.7-max",
      "candidate_index": 3,
      "reason": "provider_authentication_circuit_open"
    }
  },
  {
    "type": "model_route.fallback_started",
    "payload": {
      "requested_model": "qwen/qwen3.7-flash",
      "failed_model": "qwen/qwen3.7-max",
      "fallback_model": "qwen/qwen-flash",
      "reason": "provider_authentication_circuit_open"
    }
  },
  {
    "type": "model_route.candidate_skipped",
    "payload": {
      "requested_model": "qwen/qwen3.7-flash",
      "candidate_model": "qwen/qwen-flash",
      "candidate_index": 4,
      "reason": "provider_authentication_circuit_open"
    }
  },
  {
    "type": "model_route.fallback_started",
    "payload": {
      "requested_model": "qwen/qwen3.7-flash",
      "failed_model": "qwen/qwen-flash",
      "fallback_model": "deepseek/deepseek-v4-flash",
      "reason": "provider_authentication_circuit_open"
    }
  },
  {
    "type": "model_route.candidate_started",
    "payload": {
      "requested_model": "qwen/qwen3.7-flash",
      "candidate_model": "deepseek/deepseek-v4-flash",
      "candidate_index": 5,
      "candidate_count": 7
    }
  },
  {
    "type": "provider.attempt_started",
    "payload": {
      "provider": "deepseek",
      "model": "deepseek/deepseek-v4-flash",
      "attempt": 1,
      "max_attempts": 1,
      "timeout_seconds": 60
    }
  },
  {
    "type": "provider.attempt_completed",
    "payload": {
      "provider": "deepseek",
      "model": "deepseek/deepseek-v4-flash",
      "attempt": 1
    }
  },
  {
    "type": "model_route.candidate_completed",
    "payload": {
      "requested_model": "qwen/qwen3.7-flash",
      "model_used": "deepseek/deepseek-v4-flash",
      "fallback_used": true,
      "candidate_index": 5
    }
  }
]
```

## Boundaries

- The configured Qwen credential was rejected with HTTP 401.
- This proves live fallback behavior, not Qwen availability or Qwen quality.
- DeepSeek cannot independently judge a DeepSeek candidate run.
