# Agent Product Live Stage Token Contract Amendment

Language: [Chinese](./agent-product-live-stage-token-amendment.md) | English

- Case: `dev-todo-multistep-en-001`
- Field: `limits.maximum_tokens`
- Previous value: `120`
- New value: `180`
- Status: `requires_fresh_live_rerun`

Reason: the case requires a public native tool call containing three plan items plus a final status answer. The original 120-token ceiling was below the 180 or 220 tokens used by comparable tool-backed KlaraBench v2 cases and rejected semantically correct arguments before answer quality was considered.

Anti-gaming boundary: the provider generation cap remains 800 and the maximum step count remains 2. Required tools, states, invariants, and the reference answer are unchanged. The pre-amendment report remains preserved, and a fresh real-API rerun is mandatory; offline rescoring is not accepted.
