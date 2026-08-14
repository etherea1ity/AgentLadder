# LoCoMo Same-Model Memory Live Backtest

Language: [Chinese](./agent-product-memory-locomo-same-model.md) | English

- Verdict: `PASS`
- Model: `deepseek/deepseek-v4-flash`
- Questions: `100`
- Generation limit: `1400`

## Controlled Results

| System | F1 | EM | Recall@20 | Avg context items | P50/P95 ms | Cost USD |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| full_context | 0.543081 | 0.27 | 1.0 | 588.2 | 8850.0 / 13610.0 | 0.4765943 |
| recent | 0.023032 | 0.01 | 0.01 | 20.0 | 7014.0 / 8557.0 | 0.01967266 |
| lexical | 0.456857 | 0.27 | 0.67805 | 20.0 | 7770.0 / 12539.0 | 0.02378348 |
| vector | 0.454232 | 0.23 | 0.690938 | 20.0 | 7554.5 / 13283.0 | 0.02323496 |
| semantic_recency | 0.446954 | 0.19 | 0.680938 | 20.0 | 7964.0 / 14442.0 | 0.02352308 |
| hybrid | 0.461914 | 0.25 | 0.73402 | 20.0 | 7552.0 / 12580.0 | 0.02327248 |

## Boundary

- The official LoCoMo token F1 is deterministic and uses the pinned category rules; no LLM judge is substituted for it.
- The committed report omits question, ground-truth, context text, and prediction text; those public-dataset-derived fields stay in the ignored local checkpoint.
- The live matrix uses top_k=20 after a pre-freeze 10-question calibration showed that five atomic turns could not preserve the preregistered full-context F1 gap; the earlier Recall@5 artifact remains preserved.
- The vector signal is Klara's dependency-free hashed character-ngram representation, not a learned embedding model.
- semantic_recency is a local ablation and is not labeled as Mem0; the official Mem0 pipeline is a separate result.
- DeepSeek temperature=0 remained API-nondeterministic across calibration reruns; the frozen score is the single declared 100-question run, not a claim of exact repeatability to six decimals.
- No model training or local GPU execution occurs in this evaluation.
