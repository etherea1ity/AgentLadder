# Agent Product External Live Evaluation

Language: [Chinese](./agent-product-external-benchmarks.md) | English

- Stage status: `stage_passed_product_freeze_blocked`
- Stage gate: `PASS`
- Agent Product Freeze: `BLOCKED`
- Model training: `BLOCKED`

## Measured Summary

| Metric | Value |
| --- | ---: |
| `qwen_distinct_credentials_probed` | 2 |
| `qwen_usable_credentials` | 0 |
| `tau2_official_success_rate` | 0.8 |
| `tau2_candidate_tool_action_accuracy` | 1.0 |
| `tau2_benchmark_artifacts` | 2 |
| `agentbench_official_success_rate` | 0.8 |
| `agentbench_candidate_controllable_success_rate` | 1.0 |
| `agentbench_benchmark_artifacts` | 1 |
| `agentbench_counting_repeat_pass_rate` | 1.0 |
| `locomo_full_context_f1` | 0.543081 |
| `locomo_hybrid_f1` | 0.461914 |
| `locomo_hybrid_recall_at_20` | 0.73402 |
| `locomo_hybrid_token_reduction` | 0.956272 |
| `locomo_final_pairs` | 600 |
| `estimated_live_api_cost_usd` | 0.60001308 |
| `strange_response_p0_count` | 0 |
| `python_tests_passed` | 478 |
| `python_tests_skipped` | 2 |
| `frontend_tests_passed` | 71 |

## Remaining Blockers

- `qwen-authentication`: Two distinct configured Qwen credentials returned typed HTTP 401 results; no usable Qwen comparison provider exists.
- `blind-human-labels`: The required blind acceptability sample has no independent human labels and cannot be self-certified by the candidate system.
- `official-memory-competitors`: Mem0 lacks a configured comparable embedding stack, MEM1 requires the pinned 7B HKU GPU rollout, and BEAM lacks a licensed hashed dataset snapshot.

## Interpretation Boundary

- Official tau2 and AgentBench rewards remain 0.8 because pinned evaluator/label artifacts are preserved rather than rewritten; candidate-controllable action metrics are reported separately.
- The LoCoMo result is a frozen 100-question single run under one DeepSeek model; it is not a claim of general memory-system superiority.
- No general ChatGPT equivalence, Qwen parity, Mem0/MEM1/BEAM parity, or full public leaderboard score is claimed.
