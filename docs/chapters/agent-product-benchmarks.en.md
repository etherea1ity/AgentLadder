# Agent Product Benchmarks and Pre-Freeze Gate

Language: [Chinese](./agent-product-benchmarks.md) | English

Previous: [Chapter 18: Production Runtime and Evaluation Bridge](./ch18-production-runtime-and-eval-bridge.en.md)

Next stage: Agent Product Freeze (not currently allowed)

---

## Chapter in one sentence

This stage freezes the current Agent's real Harness, safety state, public Memory/Agent benchmark sources, and competitor implementations as reproducible contracts. Local wiring passes, but live candidate, independent judge, blind-human, and official comparable scores are incomplete, so the aggregate gate remains FAIL and model training stays prohibited.

## 1. KlaraBench v2

`tests/fixtures/behavior/agent_behavior_cases.v2.json` freezes 11 cases and 41 repeated observations spanning bilingual answers, tasks, Skills, schedules, Memory, latest corrections, approval, tenant isolation, Memory injection, destructive scope, and ambiguous stopping.

The runner does not directly assert success. Every observation receives isolated SQLite task, scheduler, Memory, and Permission state; it calls the real `KlaraHarness` and production tool adapters, then derives actions, states, and invariants from the transcript, persisted state, and public events. A scripted model replays only public reference answers and tool arguments to calibrate agreement between cases and runtime.

Calibration passes `41/41`. This is not a capability score for the current DeepSeek, Qwen, or learned Klara model, and it does not synthesize independent-judge or human labels.

## 2. Runtime defect found and fixed

The real calibration initially found that “my schedule status” and “my release-report preference” were still treated as public Web facts after successful local tool reads. Web Research then demanded fetched sources and stopped at `max_turns`.

The classifier now considers the actual visible tools and routes explicit owner task, schedule, Memory, and Skill-metadata questions to local state. Public questions such as the latest NBA schedule still enter the Web evidence gate. Dedicated regressions cover both sides.

## 3. Public Memory benchmarks

LoCoMo uses its official commit and dataset hash, official scored categories 1–4, ten questions per conversation, 100 questions total, and shared corpus/questions with `top_k=5`. Klara hybrid currently achieves evidence Recall@5 `0.630588`, Hit@5 `0.68`, and MRR `0.439`. This measures retrieval of gold evidence IDs, not answer accuracy.

LongMemEval uses the official 500-question cleaned oracle and a 60-question question-ID-hash sample. It validates answer sessions, content, answers, and six capability types. The oracle already contains only answer-bearing sessions, so this result cannot measure retrieval or answer correctness.

MemoryAgentBench pins the official dataset revision and validates Accurate Retrieval, Test-Time Learning, Long-Range Understanding, and Conflict Resolution: 146 rows and 3671 questions. Only schema, provenance, and QA alignment pass; no incremental Memory Agent answer model was run.

## 4. Mem0, MEM1, and BEAM

Mem0, MEM1, and BEAM are pinned to official manifest commits:

- Mem0's official memory-benchmarks require Mem0 OSS/Qdrant or Cloud; extraction, embedding, answerer, and judge choices all affect scores.
- MEM1 is a learned Qwen2.5-7B constant-memory Agent requiring vLLM, a GPU retriever, and official rollout/evaluation. It is not a drop-in local retrieval function.
- BEAM publishes 100 long conversations and 2000 validated questions from 128K to 10M. Execution requires a hashed official data snapshot plus frozen capability subset, answer model, and judge.

Accordingly, local `semantic_recency` is only a local ablation and is no longer presented as Mem0. All competitor scores are `not_executed/not_claimed`.

## 5. AgentBench and tau2-bench

AgentBench pins the Apache-2.0 official commit and nine task definitions. Its low-resource preset includes DBBench and OS, and DBBench dev/standard contain 60/300 rows. tau2-bench pins the MIT official commit and validates 2556 unique tasks plus core labels across mock, airline, retail, telecom, and banking_knowledge.

These are source/task contracts only. Official scores require official environments, tools, and graders with frozen Agent model, tau2 user simulator, maximum turns, and budget. No score is claimed.

## 6. Paid and human-review boundary

The stage manifest currently declares `paid_api_usd = 0`. The live candidate CLI checks this before any network call and refuses a zero budget; it also requires explicit input/output token prices. A blind queue is generated only after full candidate coverage. It omits candidate slot, stores the private key separately, and gives identical answers from different repetitions unique pair IDs.

The live report now preserves all public observations but leaves reference success unset: scripted calibration is not allowed to impersonate a live GPT/Codex reference run. `behavior_labels_cli` accepts a separately hashed candidate report, exact-coverage live-reference and independent-judge results, blind A/B acceptability ratings, and the private decode key. It rejects missing or duplicate rows, candidate-report changes after labeling, invalid judge outcomes, a mismatched private key, and any review artifact that lacks both A and B boolean ratings. Only that merged report may satisfy the three external behavior checks.

The following therefore remain failed: 41 live candidate observations, reference non-inferiority, full independent-model judging, at least 95% blind human acceptability, and official comparable AgentBench, tau2, Mem0, MEM1, and BEAM scores.

## Tests and reproduction

```powershell
$env:PYTHONPATH = "src;."
python -m klara.eval.behavior_runtime_cli `
  --fixture tests/fixtures/behavior/agent_behavior_cases.v2.json `
  --repository-root . `
  --json-out .tmp/behavior-runtime-calibration.json
python -m klara.eval.public_memory_cli `
  --locomo-checkout .tmp/public-benchmarks/locomo `
  --json-out .tmp/locomo-public-memory.json
python -m pytest -q
npm --prefix apps/web test -- --run
npm --prefix apps/web run build
git diff --check
```

## Limitations and next step

Local deterministic and public-source contracts are ready, but this is not Agent Product Freeze. Only a newly authorized paid budget, full live candidate and independent-judge runs, blind-human labels, and official comparable benchmark scores can unlock regeneration of the aggregate report and consideration of KV Cache, trajectory data, and HKU training. No general ChatGPT parity is claimed.
