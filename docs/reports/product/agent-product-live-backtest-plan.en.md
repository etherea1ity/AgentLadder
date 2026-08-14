# Agent Product Live Backtest Plan

Language: [Chinese](./agent-product-live-backtest-plan.md) | English

Status: **IN PROGRESS**

## Current truth

Most Chapter 4–18 behavior results were deterministic tests or `contract_control_probe` runs. The only prior product evidence using an external model was the three-case DeepSeek V4 Flash Runtime Integration smoke. KlaraBench v2 `41/41` is scripted-reference calibration, not a model score.

## Comparison unit

Each sample compares the complete public behavior: question and context → tool selection, arguments, and order → tool observations → persisted state change → final answer. GPT/Codex supplies only public reference answers and public action paths without hidden reasoning; both DeepSeek and Qwen must execute through the real `KlaraHarness`.

## Execution order

1. Verify real DeepSeek and Qwen authentication and model IDs.
2. Expand every frozen stage capability into the cross-chapter behavior matrix.
3. Run the same observations with DeepSeek V4 Flash and Qwen 3.7 Flash.
4. Compute non-inferiority against the public GPT/Codex references.
5. Judge DeepSeek outputs with Qwen Max and Qwen outputs with DeepSeek Pro.
6. Preserve wrong tools, wrong arguments, false success, irrelevant answers, permission violations, strange follow-ups, and unnecessary plans; repair the owning stage and rerun.
7. Generate the blind-review queue; the generator may not fabricate human labels.
8. Allow Agent Product Freeze only after every mandatory gate passes.

## Budget and stop condition

This run has a hard total cap of USD 20 equivalent, plus sublimits of USD 10 for DeepSeek, CNY 75 for Qwen, and 900 requests. Cost uses official prices, conservative cache-miss/list rates, and provider usage. Execution stops before any limit is exceeded.

Model training, HKU, KV Cache, and trajectory-scale collection remain blocked by Agent Product Freeze.
