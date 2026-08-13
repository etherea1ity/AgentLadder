# Chapter 10 Memory Gate

Language: [Chinese](./ch10-memory.md) | English

Status: **PASS**

- Scorer: `klara.chapter10-memory.v1`
- Gate kind: `deterministic_memory_lifecycle_and_retrieval_gate`
- Checks: `16/16`

## Acceptance Checks

| Check | Result |
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

## Retrieval Ablations

| System | Top-1 | Critical Top-1 | Recall@5 | Precision@5 |
| --- | ---: | ---: | ---: | ---: |
| full_context | 0.167 | 0.000 | 0.833 | 0.167 |
| recent | 0.167 | 0.000 | 0.833 | 0.167 |
| lexical | 1.000 | 1.000 | 1.000 | 0.200 |
| vector | 0.833 | 0.667 | 1.000 | 0.200 |
| hybrid | 1.000 | 1.000 | 1.000 | 0.200 |
| mem0_compatible | 0.833 | 0.667 | 1.000 | 0.200 |

## Interpretation Boundary

Passing proves the repository-native memory lifecycle, owner partition, temporal supersession, hard-delete proof, trace privacy, UI controls, and a small deterministic retrieval-ablation gate. It does not claim end-to-end LoCoMo, LongMemEval, MemoryAgentBench, BEAM, Mem0, or MEM1 superiority; those remain frozen same-model benchmark work before Agent Product Freeze.
