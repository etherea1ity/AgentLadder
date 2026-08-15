# Agent Product Freeze Readiness Experiment

Language: [Chinese](./agent-product-freeze-readiness.md) | English

## Question and Hypothesis

Question: when an older failed replay, a fresh hidden split, module-level architecture gates, and external benchmarks coexist, which evidence may decide whether the Agent can enter model training?

Falsifiable hypothesis: verifying every frozen input hash and applying the precedence rule “a fresh hidden split updates the current verdict, historical failures remain preserved, and an internal baseline is not an external competitor” produces one repeatable Product Freeze status.

## Quick Experience

```powershell
$env:PYTHONPATH='src'
python -m klara.eval.product_freeze_readiness `
  --root . `
  --manifest config/stages/agent-product-freeze-readiness.manifest.json `
  --source-commit 0d3f3d5b61a2a374f504e0f8407f72de14d49cc7 `
  --python-tests-collected 513 --python-tests-skipped 2 `
  --web-tests 71 --web-test-files 20 --web-build-passed `
  --report-json docs/reports/product/agent-product-freeze-readiness.json `
  --report-md docs/reports/product/agent-product-freeze-readiness.md `
  --report-en-md docs/reports/product/agent-product-freeze-readiness.en.md `
  --ledger-json docs/reports/product/completion-ledger.json `
  --ledger-md docs/reports/product/completion-ledger.md `
  --ledger-en-md docs/reports/product/completion-ledger.en.md
```

Expected output: the evidence-reconciliation stage passes, while `agent_product_freeze_allowed=false` and model training remains blocked.

## Frozen Baseline and Controls

- The parent commit is fixed at `0d3f3d5b61a2a374f504e0f8407f72de14d49cc7`.
- Input paths and SHA-256 digests are frozen in `config/stages/agent-product-freeze-readiness.manifest.json`.
- The current LoCoMo gate uses the fresh offset-10 100-question split; Agent and direct baseline share questions, DeepSeek model, top-k, generation length, and scorer.
- The older offset-0 failed replay remains historical repair evidence. It is not deleted and is not presented as the current hidden score.
- This experiment changes no benchmark answer, label, threshold, or model output.

## Data, Provenance, and Isolation

- LoCoMo source, commit, license, and data hash remain those of the frozen benchmark reports.
- KlaraBench contains public answers and public actions only, never provider-hidden reasoning.
- Reports read aggregate metrics, ID hashes, and run metadata; ignored raw public-dataset text is not copied into Git.
- Missing independent-judge, human-review, Mem0, MEM1, and BEAM results remain blockers or resource-dependent expansion items.

## Decision Mechanism

```text
verify manifest and input hashes
-> separate architecture freeze from product freeze
-> select the latest fresh hidden split
-> preserve the older failed replay
-> distinguish internal baselines from external competitors
-> update the machine-readable ledger
-> allow or block the next stage
```

The implementation is in `src/klara/eval/product_freeze_readiness.py`. An input-hash or cross-report case-hash mismatch fails closed instead of generating a more optimistic status.

## Metrics and Gates

- Frozen input hash agreement must be `100%`.
- Architecture Freeze and Product Freeze status must remain separate.
- The fresh hidden LoCoMo Agent must pass the frozen non-inferiority gate.
- Missing independent judge, blind-human review, or same-control Mem0 comparison must keep Product Freeze blocked.
- No Mem0/MEM1/BEAM/GPT/Qwen/ChatGPT or general Agent-framework superiority claim is allowed.

## Validation

```powershell
python -m pytest tests/klara/eval/test_product_freeze_readiness.py -q
python -m pytest -q
npm --prefix apps/web test -- --run
npm --prefix apps/web run build
git diff --check
```

## Artifacts

- `docs/reports/product/agent-product-freeze-readiness.json`
- `docs/reports/product/agent-product-freeze-readiness.md`
- `docs/reports/product/agent-product-freeze-readiness.en.md`
- `docs/reports/product/completion-ledger.json`
- `docs/reports/product/completion-ledger.md`
- `docs/reports/product/completion-ledger.en.md`

## Limitations and Next Experiment

This experiment reconciles evidence; it does not manufacture an independent review or competitor score. The next stage must complete an independent model judge, blind-human review, and a provenance-pinned same-control Mem0 reproduction before `codex/agent-product-freeze` can be produced.
