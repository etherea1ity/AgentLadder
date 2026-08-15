# Mem0 同控制复现

语言：中文 | [English](./mem0-comparable-reproduction.en.md)

- 阶段: `通过`
- Mem0 PR head: `5e941e24c2cb260f73cc6d31113a92bb1ce62d46`
- 冻结问题: `100`

## 同控制成绩

| System | F1 | EM | Recall@20 | Completed |
| --- | ---: | ---: | ---: | ---: |
| Mem0 OSS v3 PR #4805 | 0.341772 | 0.160000 | 0.851833 | 100/100 |
| KlaraLoop Agent | 0.437246 | 0.210000 | 0.782417 | 100/100 |
| Klara direct hybrid | 0.455354 | 0.210000 | 0.767917 | 100/100 |

## 门槛

- PASS — `all_source_hashes_and_commits_match`
- PASS — `deleted_branch_resolves_to_exact_pr_head`
- PASS — `official_bm25_and_entity_runtime_green`
- PASS — `qdrant_service_mode_avoids_embedded_entity_lock`
- PASS — `strict_extraction_json_failures_surface_for_http_retry`
- PASS — `same_frozen_100_case_ids`
- PASS — `same_answer_model`
- PASS — `same_direct_answer_prompt`
- PASS — `same_embedding_model`
- PASS — `same_top_k_generation_temperature_and_scorer`
- PASS — `official_mem0_formation_executed_for_every_turn`
- PASS — `all_100_cases_completed`
- PASS — `all_final_cases_error_free`
- PASS — `zero_strange_response_p0`

## 适配偏差

- The deleted feat/v3-pipeline name is replaced only by its exact final official PR #4805 head SHA.
- The official benchmark wrapper drops timestamp and calls a removed user_id search argument; this adapter maps source time into created_at metadata and user scope into the v3 filters contract.
- Source dialogue IDs and turn order are observational metadata used only to compute deterministic evidence Recall@20 and chronological answer packing.
- The exact all-MiniLM-L6-v2 model runs in a host-cached OpenAI-compatible local endpoint; Mem0 calls it through the official OpenAI embedding provider to avoid downloading a duplicate Torch runtime into the container.
- Qdrant runs through the official v3 Qdrant adapter against a version-pinned service container; embedded mode is rejected because the exact PR head deep-copies the lazy entity-store config and conflicts with the local RocksDB lock.
- The official benchmark LLM answer prompt and LLM judge are replaced by AgentLadder's already frozen direct-baseline answer prompt and deterministic LoCoMo token-F1 scorer; the Agent retains its frozen tool-capability prompt.

## 声明边界

- This is a same-control comparison of the official OSS v3 PR head, not a Mem0 Platform score.
- A win on this frozen 100-question split is not a general superiority claim.
- No MEM1, BEAM, independent-model, blind-human, ChatGPT, or leaderboard result is inferred.
- No model training, HKU connection, upload, Slurm job, SFT, RL, or quantization occurred.
