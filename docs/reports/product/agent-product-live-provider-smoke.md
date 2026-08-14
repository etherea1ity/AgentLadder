# Agent 产品真实 Provider 冒烟

语言：中文 | [English](./agent-product-live-provider-smoke.en.md)

- 结论: `未通过`
- 请求数: `2`
- 原生成本: `{"CNY": 0.0, "USD": 7.994e-05}`

## 逐模型结果

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

## 边界

- This proves live identity, authentication, usage reporting, and one structured tool call only.
- It is not a product behavior score, a chapter pass, or a GPT-parity claim.
