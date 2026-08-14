# Memory Competitor Execution Preflight

Language: [Chinese](./agent-product-memory-competitor-preflight.md) | English

- Preflight: `PASS`
- Execution status: `external_execution_blocked`
- Competitor scores ready: `False`

## Per-system Status

| System | Source pinned | Execution ready | Status |
| --- | --- | --- | --- |
| mem0 | True | False | blocked_external_dependencies |
| mem1 | True | False | hku_gpu_rollout_pending |
| beam | True | True | ready |

## Blockers

- `mem0`: The official default OSS stack requires an OpenAI extraction and embedding credential, which is not configured.
- `mem0`: DeepSeek can supply the common answerer/extraction model through an OpenAI-compatible endpoint but does not supply the required embedding endpoint.
- `mem0`: The official Ollama alternative and nomic embedding runtime are not installed; starting a sustained local embedding workload is outside the thermal-safe pre-HKU boundary.
- `mem1`: The official 7B checkpoint is not cached in the repository workspace.
- `mem1`: The pinned vLLM/retriever rollout is an HKU GPU evaluation task and has not started before Agent Product Freeze.

A passing preflight means sources, dependencies, and blockers were identified accurately; it is not a Mem0, MEM1, or BEAM score.
