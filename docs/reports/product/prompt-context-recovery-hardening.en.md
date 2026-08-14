# Prompt, Context, Memory, and Recovery Hardening

Language: [Chinese](./prompt-context-recovery-hardening.md) | English

- Local code/API gate: `PASS`
- Agent Product Freeze: `FAIL`
- HKU training started: `false`

## Results

- Python: `510` collected, `2` skipped.
- Web: `71` tests in `20` files; production build passed.
- Chapter gates: `12/12`.
- Behavior: critical `1.0`, normal `1.0`, P0 `0`.
- LoCoMo F1: direct `0.455354`, Agent `0.437246`, delta `-0.018108`.
- LoCoMo Recall@20: direct `0.767917`, Agent `0.782417`.

## Blockers

- Qwen independent-judge credential returned HTTP 401 during the frozen live smoke.
- Blind human comparison labels have not been produced; model output cannot be relabeled as human review.
