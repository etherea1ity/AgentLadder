# Mem0 Same-control Reproduction Experiment

Language: [Chinese](./mem0-comparable-reproduction.md) | English

## Question and Hypothesis

Question: how does the AgentLadder Memory Agent compare with official Mem0 OSS v3 on the frozen LoCoMo validation split, without manufacturing an advantage through different models, questions, top-k values, or scorers?

Falsifiable hypothesis: pinning the final official `feat/v3-pipeline` pull-request head to an immutable SHA, executing its real memory formation and hybrid retrieval, and reusing AgentLadder's frozen 100 questions, DeepSeek answer model, 512-token budget, top-20 context, and deterministic LoCoMo F1 scorer produces a traceable same-control Mem0 result.

## Quick Experience

Start the host embedding service dedicated to this experiment:

```powershell
$env:PYTHONPATH='src'
python -m uvicorn klara.eval.local_embedding_server:app --host 0.0.0.0 --port 18989
```

In a second terminal, start the Mem0 container:

```powershell
docker compose --env-file .env -f docker/mem0-comparable/compose.yaml up -d --build
```

Run a real formation/search smoke:

```powershell
$env:PYTHONPATH='src'
python -m klara.eval.mem0_comparable_live `
  --root . --server-url http://localhost:18888 --smoke
```

The complete 100-question run is resumable:

```powershell
$env:PYTHONPATH='src'
python -m klara.eval.mem0_comparable_live `
  --root . `
  --manifest config/stages/mem0-comparable-reproduction.manifest.json `
  --source-commit 3b93e9b91e83b48e405e21a932d1d1b3702ef7f1 `
  --dataset .tmp/public-benchmarks/locomo/data/locomo10.json `
  --ingestion-checkpoint .tmp/mem0-comparable/ingestion.jsonl `
  --answer-checkpoint .tmp/mem0-comparable/answers.jsonl `
  --server-url http://localhost:18888 `
  --max-ingest-workers 2 --max-answer-workers 4 `
  --python-tests-collected 517 --python-tests-skipped 2
```

Raw questions, answers, retrieved text, and predictions stay in the ignored directory. The tracked JSON report retains only hashes, scores, and aggregate runtime metrics.

## Frozen Baseline and Controls

- `memory-benchmarks` is pinned at `4b61c5d31b9c668a12b4f5e78064248a02c82d2b`.
- Its inaccessible dependency name `feat/v3-pipeline` is replaced exactly by the final official PR #4805 head `5e941e24c2cb260f73cc6d31113a92bb1ce62d46`.
- LoCoMo is pinned to commit `3eb6f2c585f5e1699204e3c3bdf7adc5c28cb376` and SHA-256 `79fa87e...98ff4`.
- The selection is offset 10, ten questions per conversation, 100 total; its case-ID hash is `8b80b91c...3e12`.
- All three systems share the `deepseek/deepseek-v4-flash` answer model, temperature 0, top-k 20, maximum 512 output tokens, and deterministic scorer; Mem0 and the direct baseline reuse the same answer-only prompt, while the Agent retains its frozen tool-capability prompt.
- Mem0 formation uses the same DeepSeek model and `sentence-transformers/all-MiniLM-L6-v2` embedding.
- Each one-turn extraction is capped at 2,400 output tokens. The live compatibility probe showed that 512 tokens were exhausted by `deepseek-v4-flash` internal reasoning and left an empty content field. A 1,400-token simple smoke passed, but complex LoCoMo turns still produced truncation-like invalid JSON, so the formal configuration freezes 2,400 before accepting its checkpoint. Assuming at most 20,000 input tokens per call, the conservative upper bound for 5,882 formation calls stays below the frozen USD 25 budget. The official SDK does not return extraction usage, so the report marks that telemetry gap; answer generation remains fixed at 512 tokens.

## Data, Provenance, and Isolation

The official benchmark requirements reference a deleted branch. GitHub's PR API and `refs/pull/4805/head` independently identify that branch's final head; the build file pins the SHA directly and never substitutes `main` or `latest`.

LoCoMo is CC-BY-NC-4.0, so raw data and derived checkpoints remain outside Git. `.env` is passed only into the container by Docker Compose; the health endpoint, smoke artifact, and public report never emit the API key.

## Execution Mechanism

```text
freeze sources and input hashes
-> build the exact Mem0 PR head
-> execute one official v3 ADD formation per LoCoMo turn
-> retain source dia_id / time as observational metadata
-> official v3 dense + BM25 + entity hybrid search
-> chronologically pack the top-20 memories
-> same DeepSeek prompt / 512-token answer budget
-> deterministic F1, EM, and Evidence Recall@20
-> update the Product Freeze blocker and completion ledger
```

Formation and search execute official `Memory.add` and `Memory.search`. The adapter owns only the HTTP boundary, source metadata, same-control answer prompt, and report generation.

## Disclosed Official-wrapper Gaps

- The official benchmark client sends `timestamp`, but the pinned server request schema lacks that field; the adapter places time in the official SDK's supported `created_at` metadata.
- The pinned server still calls search with `user_id=`, while the v3 SDK requires `filters={"user_id": ...}`; the adapter performs only that parameter mapping.
- Qdrant uses the official v3 adapter against a version-pinned service container. In embedded mode, the exact PR head copies the lazy entity-store configuration and collides with the local RocksDB lock. Service mode preserves dense, BM25, and entity additive scoring while removing that lock conflict.
- The exact PR head silently folds malformed extraction JSON and provider exceptions into an empty memory list. The adapter retries only when the same DeepSeek call returns empty, non-object, or schema-invalid JSON, for at most three total attempts. A third invalid response explicitly fails that HTTP request. The outer client then makes at most 16 attempts for the same turn with a four-second backoff cap; this durable retry changes only failure recovery, not the model, prompt, trajectory order, retrieval, or scoring. A final failure aborts the run; the report exposes the JSON retries, request failures, and HTTP policy instead of relabelling a provider/schema failure as “no memory.”
- The identical `all-MiniLM-L6-v2` model runs in a host-cached service and Mem0 calls it through its official OpenAI-compatible embedding provider, avoiding a duplicate Torch download inside the container.
- The official benchmark LLM judge is replaced by the frozen deterministic LoCoMo token F1, which is required to keep the scorer identical across all three systems.

## Metrics and Gates

- 100/100 questions must complete with zero provider or retrieval errors.
- Every LoCoMo turn must execute through official Mem0 formation.
- A finally unrecovered extraction JSON failure aborts the run; recovered JSON retries and HTTP request failures must be reported.
- The formal run crossed multiple checkpoint-resume processes whose earlier durations were not persisted. The machine report therefore labels only the final resume-process duration and marks end-to-end duration unavailable. JSON-retry and request-failure values are Mem0 adapter service-lifetime counters, including the bounded smoke before the formal checkpoint, and must not be interpreted as formal-sample-only counts.
- Question, model, embedding, top-k, generation-budget, and scorer hashes must agree; the Mem0 and direct-baseline answer-prompt hashes must agree.
- P0 strange responses must be zero.
- F1, EM, Recall@20, P50/P95 retrieval latency, end-to-end latency, and answer tokens must be reported without suppression; there is no post-hoc “must win” threshold.
- Even if this split beats Mem0, the claim is limited to the frozen 100-question same-control result and cannot be generalized to Mem0 overall.

## Validation

```powershell
python -m pytest -q tests/klara/eval/test_mem0_comparable_live.py
python -m pytest -q
docker compose --env-file .env -f docker/mem0-comparable/compose.yaml ps
git diff --check
```

## Artifacts

- `docs/reports/product/mem0-comparable-reproduction.json`
- `docs/reports/product/mem0-comparable-reproduction.md`
- `docs/reports/product/mem0-comparable-reproduction.en.md`
- `.tmp/mem0-comparable/ingestion.jsonl` (ignored and resumable)
- `.tmp/mem0-comparable/answers.jsonl` (ignored, contains public-data-derived text)
- updated `agent-product-freeze-readiness.*` and `completion-ledger.*`

## Limitations and Next Experiment

This is not a Mem0 Platform cloud score and does not reproduce the official LLM judge. It compares only formation and retrieval from the pinned OSS v3 head. After the Mem0 gate passes, Product Freeze must still wait for the independent model judge and blind-human labels; MEM1 and BEAM remain resource-dependent expansions, and training stays prohibited.
