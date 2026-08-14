# Agent 产品外部真实评测

语言：中文 | [English](./agent-product-external-benchmarks.en.md)

- 阶段状态: `stage_passed_product_freeze_blocked`
- 本阶段门禁: `通过`
- Agent Product Freeze: `不允许`
- 模型训练: `不允许`

## 实测摘要

| 指标 | 值 |
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

## 未解除阻塞

- `qwen-authentication`: Two distinct configured Qwen credentials returned typed HTTP 401 results; no usable Qwen comparison provider exists.
- `blind-human-labels`: The required blind acceptability sample has no independent human labels and cannot be self-certified by the candidate system.
- `official-memory-competitors`: Mem0 lacks a configured comparable embedding stack, MEM1 requires the pinned 7B HKU GPU rollout, and BEAM lacks a licensed hashed dataset snapshot.

## 解释边界

- τ2 与 AgentBench 的官方 0.8 原样保留；候选侧可控动作正确率与基准缺陷分开报告。
- LoCoMo 只证明冻结 100 题上的同模型结果，不证明普遍达到 ChatGPT 或超过 Mem0/MEM1/BEAM。
- 由于 Qwen、人评和官方 Memory 竞品仍阻塞，Agent Product Freeze 与训练都不允许开始。
