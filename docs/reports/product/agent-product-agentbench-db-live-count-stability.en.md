# AgentBench Counting Decision Stability

Language: [Chinese](./agent-product-agentbench-db-live-count-stability.md) | English

- Verdict: `PASS`
- Repetitions: `3`
- Pass rate: `1.0`
- Total semantic preflight rejections: `3`
- Average model decision attempts: `3.0`
- Estimated total cost: `$0.00202412`

## Per-run Results

| Run | Passed | Reward | Rejections | Attempts |
| ---: | --- | ---: | ---: | ---: |
| 1 | True | [1] | 1 | 3.0 |
| 2 | True | [1] | 0 | 2.0 |
| 3 | True | [1] | 2 | 4.0 |

## Boundary

- This stability result covers only the declared counting sample and is not a full AgentBench score.
- Semantic preflight is a general count-intent invariant; it contains no benchmark fixture values or expected answers.
