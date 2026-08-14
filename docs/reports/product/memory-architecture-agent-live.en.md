# Memory Agent Architecture Evaluation

Language: [Chinese](./memory-architecture-agent-live.md) | English

## Result

FAIL

## Frozen score

| System | F1 | EM | Recall@20 | Tool call rate |
|---|---:|---:|---:|---:|
| Direct hybrid baseline | 0.461914 | 0.250000 | 0.734020 | N/A |
| KlaraLoop memory agent | 0.390983 | 0.110000 | 0.740176 | 1.000000 |

## Runtime metrics

- Cases: 100/100
- Valid tool arguments: 1.000000
- Average turns: 2.000
- P50/P95 latency: 18864/44534 ms
- Estimated DeepSeek cost: $0.086497

## Gates

- PASS — `official_dataset_hash`
- PASS — `balanced_ten_by_ten_subset`
- PASS — `all_cases_execute_through_klara_harness`
- PASS — `all_cases_completed`
- PASS — `all_final_case_results_successful`
- PASS — `memory_search_call_rate_at_least_0_98`
- PASS — `valid_memory_search_arguments_at_least_0_99`
- FAIL — `agent_f1_not_below_direct_hybrid_by_more_than_0_03`
- PASS — `agent_evidence_recall_at_20_at_least_0_70`
- PASS — `zero_strange_response_p0`

## Limitations

- The deterministic LoCoMo token F1 remains the primary score; no same-model self-judge replaces it.
- The benchmark instruction identifies the request as durable-history QA, but DeepSeek still chooses and parameterizes memory_search through the production loop.
- LoCoMo turns are seeded as explicit episodic records so this stage isolates runtime tool choice and retrieval; automatic memory formation is evaluated separately.
- The committed report removes public question, answer, memory, and prediction text; raw rows stay in the ignored checkpoint.
- No local GPU execution or model training occurs in this evaluation.
