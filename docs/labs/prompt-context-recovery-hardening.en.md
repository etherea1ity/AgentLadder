# Prompt, Context, Memory, and Recovery Hardening Lab

Language: [Chinese](./prompt-context-recovery-hardening.md) | English

## Goal

This lab closes defects found after the first full architecture audit. It does not train a model. The target is a restart-safe Agent whose prompt matches its visible capabilities, whose context budget remains conservative for Chinese text, whose memory path survives prompt injection and temporal reconstruction, and whose live behavior is measured against frozen GPT/Codex-authored references.

## Architecture Changes

1. `klara.loop-checkpoint.v2` stores optional private controller state. The context summary is restored before the next model call, and the checkpoint hashes the effective prompt after controller restoration. API durable recovery also compares the frozen run-profile hash before resuming.
2. Runtime instructions are capability-scoped. A memory-only Agent is no longer told to call absent web, time, or todo tools.
3. Token estimates use `ASCII/chars_per_token + non-ASCII code points`. Summary fitting uses the same estimator, retains head and tail, records source hashes, and anchors explicit user corrections.
4. Provider recovery uses bounded jitter, respects numeric `Retry-After`, and adds a public-output recovery instruction after a reasoning-only or empty generation.
5. Memory formation receives an untrusted JSON object instead of interpolated XML. Retrieval selects top-k by relevance, presents selected evidence chronologically, and preserves `retrieval_rank`.
6. Memory search keeps the complete question. After retrieval, the answer contract asks for the shortest directly requested fact and rejects unrelated candidates or unsolicited parenthetical detail.

## Verification

```powershell
python -m pytest -q

Push-Location apps/web
npm test
npm run build
Pop-Location
```

The final fresh LoCoMo split starts at hash-ranked offset 10 and contains 100 questions. Both paths use DeepSeek V4 Flash, top-k 20, temperature 0, and a 512-token maximum. The direct hybrid baseline reached F1 0.455354 and Recall@20 0.767917. The real `KlaraHarness/KlaraLoop` Agent reached F1 0.437246 and Recall@20 0.782417, with 100% memory-tool call rate, exactly-one-call rate, and valid-argument rate; P0 was zero.

The 41-observation live behavior replay reached critical rate 1.0, normal task success 1.0, repeat stability 1.0, and P0 zero after incomplete-final and empty-provider recovery defects were repaired.

## Boundary

The local code/API gate is green, but Agent Product Freeze is not. Qwen returned HTTP 401 in the frozen independent-provider smoke, and blind human labels do not exist. These two fields remain unscored. No HKU connection, upload, Slurm submission, or model training is permitted from this report.
