# Agent Product Live Provider Smoke

Language: [Chinese](./agent-product-live-provider-smoke.md) | English

- Verdict: `FAIL`
- Requests: `2`
- Native cost: `{"CNY": 0.0, "USD": 7.994e-05}`

## Per-model results

### deepseek/deepseek-v4-flash

- status: `completed`
- model_used: `deepseek/deepseek-v4-flash`
- tool_call_valid: `true`
- usage: `{"completion_tokens": 71, "prompt_tokens": 429, "total_tokens": 500}`
- cost: `{"amount": 7.994e-05, "currency": "USD"}`
- duration_ms: `6850`

### qwen/qwen3.7-flash

- status: `failed`
- model_used: `None`
- tool_call_valid: `false`
- usage: `{"completion_tokens": 0, "prompt_tokens": 0, "total_tokens": 0}`
- cost: `{"amount": 0.0, "currency": "CNY"}`
- duration_ms: `9608`

## Boundary

- This proves live identity, authentication, usage reporting, and one structured tool call only.
- It is not a product behavior score, a chapter pass, or a GPT-parity claim.
