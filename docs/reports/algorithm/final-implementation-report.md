# Final Implementation Report

Date: 2026-08-12

Status: complete for the bounded algorithm suite

## Runtime Boundary

The existing `KlaraLoop`, hooks, and public trace remain the runtime center.
Algorithm work is layered outside `src/klara/core`:

- `src/klara/services/evidence`: claims, evidence records, links, verdicts,
  contradiction, insufficiency, and abstention control;
- `src/klara/eval`: versioned trajectory export, deterministic dataset checks,
  scorers, JSON/Markdown reports, and final suite aggregation;
- `src/klara/training`: byte tokenizer, custom decoder, checkpoints, bounded
  trainers, public-trajectory SFT, sparse MoE, FP16, and FP4/W4A16.

Architecture tests enforce that `klara.core` does not import evidence,
evaluation, or training code. No new frontend implementation is part of the
algorithm gate.

## Implemented Algorithms

1. Claim-level evidence control with explicit supported, contradicted, and
   insufficient verdicts; required unsupported claims abstain.
2. Redacted public trajectory schema with content hashes, stable IDs,
   deterministic JSONL, disjoint splits, leakage detection, and exact scorers.
3. Repository-native decoder-only Transformer with RMSNorm, RoPE, grouped-query
   attention, SwiGLU, causal/padding masks, generation, trainer, and checkpoint.
4. Multi-teacher public-contract ingestion for Qwen and DeepSeek with schema,
   redaction, deduplication, lineage, hard-label SFT, and held-out scoring.
5. Four-expert token-level top-2 sparse MoE with normalized routing, auxiliary
   balance loss, router z-loss, entropy/utilization diagnostics, and reload.
6. Real CUDA FP16 AMP and GradScaler path; E2M1 FP4 codec, nibble packing,
   per-block FP16 scales, packed W4A16 modules, optional QAT trigger, and reload.
7. HKU-only Slurm deployment, source hashing, isolated Python, report retrieval,
   checksum validation, and process cleanup checks.
8. A final aggregator that refuses PASS unless all stage reports, checkpoint
   lineage, data/teacher lineage, source lineage, tests, and frontend exclusion
   pass together.

## Canonical Documentation

- Chinese lab: `docs/labs/algorithm-suite.md`
- English lab: `docs/labs/algorithm-suite.en.md`
- Machine report: `docs/reports/algorithm/algorithm-suite-freeze.json`
- Human report: `docs/reports/algorithm/algorithm-suite-freeze.md`
- Freeze: `docs/freezes/algorithm-suite-freeze.md`
