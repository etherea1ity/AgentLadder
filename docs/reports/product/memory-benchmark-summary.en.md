# Agent Architecture and Memory Benchmark Summary

Language: [中文](./memory-benchmark-summary.md) | English

Current conclusion: **the architecture freeze passes, but Agent Product Freeze does not; HKU model training must not start.**

## Architecture and real execution

- The audit covered `34` remote branches representing `32` unique commits. `34/34` compiled and `33/34` passed their historical test suites. The independent legacy `origin/rag` line still has `9` failures.
- No historical branch satisfies the current complete architecture contract. Repairs were integrated only on the latest reliable branch; historical tutorial snapshots were not rewritten.
- The latest branch passes `12/12` chapter architecture gates, `498` Python tests with `2` environment-dependent skips, `71` web tests, and the production build.
- The live DeepSeek runtime integration passes `3/3` cases and `14/14` checks with `0` unauthorized mutations. The evidence/MCP/team-tooling replay passes `3/3` cases with `0` P0 responses.
- The real Harness behavior replay is `40/41` (`97.56%`): `100%` on ordinary tasks, `95%` on critical tasks, and `0` P0 responses. It still cannot pass the behavior gate because independent-judge, reference, and blind-human labels have not been imported. The sole deterministic miss was a semantically correct Chinese refusal rejected by the frozen lexical matcher; the hidden fixture was not edited after observing it.

## LoCoMo memory result

All 100 repair-replay questions completed normally. Exactly one valid `memory_search` was issued in `100%` of cases. Recall@20 reached `0.7402`, slightly above the same-model direct-hybrid baseline of `0.7340`. Owner isolation, memory routing, the tool protocol, and dense/sparse RRF retrieval therefore clear their gates.

Final F1 is only `0.3910`, below the same-model dedicated QA baseline of `0.4619`. The `-0.0709` gap exceeds the allowed `-0.03`. Exact Match is `0.11`, versus `0.25` for the baseline. The remaining failure boundary is general-agent answer synthesis, not evidence retrieval.

These 100 questions are a same-set repair replay. They validate the repair but are not a new hidden evaluation. The next run must use a fresh hidden split.

## Mem0

No Mem0 score is fabricated. The pinned official `memory-benchmarks` Dockerfile references the deleted `feat/v3-pipeline` branch, so its official runtime is not currently reproducible. The SDK compatibility adapter is not represented as a byte-identical official result.

## Current gates

- Agent Architecture Freeze: `PASS`
- Agent Product Freeze: `FAIL`
- HKU model training: `BLOCKED`

The next stage must repair memory answer synthesis, rerun a fresh hidden split, import independent-judge/reference/blind-human labels, and reproduce Mem0 from a provenance-pinned official runtime. Training is allowed only after those product gates pass.
