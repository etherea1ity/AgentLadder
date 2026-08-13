# Chapter 10 Memory 门禁

语言：中文 | [English](./ch10-memory.en.md)

Status: **PASS**

- 评分器: `klara.chapter10-memory.v1`
- 门禁类型: `deterministic_memory_lifecycle_and_retrieval_gate`
- 检查: `16/16`

## 验收检查

| 检查 | 结果 |
| --- | --- |
| api_exposes_governed_lifecycle | PASS |
| api_is_owner_scoped | PASS |
| audit_uses_hash_not_raw_deleted_content | PASS |
| bilingual_tutorial_exists | PASS |
| competitors_are_not_falsely_claimed | PASS |
| current_fact_supersedes_old_fact | PASS |
| five_memory_kinds_declared | PASS |
| frontend_has_search_provenance_update_forget_delete | PASS |
| hard_delete_is_verified | PASS |
| historical_query_recovers_old_fact | PASS |
| hybrid_retrieval_critical_top1_is_perfect | PASS |
| public_projection_hides_content_and_query | PASS |
| retrieval_ablation_matrix_is_complete | PASS |
| stage_manifest_exists | PASS |
| tenant_mutation_isolation | PASS |
| tenant_read_isolation | PASS |

## 检索消融

| 系统 | Top-1 | Critical Top-1 | Recall@5 | Precision@5 |
| --- | ---: | ---: | ---: | ---: |
| full_context | 0.167 | 0.000 | 0.833 | 0.167 |
| recent | 0.167 | 0.000 | 0.833 | 0.167 |
| lexical | 1.000 | 1.000 | 1.000 | 0.200 |
| vector | 0.833 | 0.667 | 1.000 | 0.200 |
| hybrid | 1.000 | 1.000 | 1.000 | 0.200 |
| mem0_compatible | 0.833 | 0.667 | 1.000 | 0.200 |

## 解释边界

通过表示仓库原生 Memory 生命周期、所有者分区、时间冲突处理、硬删除证明、公开轨迹隐私、管理界面和小型确定性检索消融门禁成立。它不表示已经在端到端 LoCoMo、LongMemEval、MemoryAgentBench、BEAM，或与 Mem0、MEM1 的同模型对比中胜出；这些仍是 Agent Product Freeze 前必须执行的冻结基准工作。
