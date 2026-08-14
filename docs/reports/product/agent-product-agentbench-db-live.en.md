# AgentBench FC DBBench Live Backtest

Language: [Chinese](./agent-product-agentbench-db-live.md) | English

- Verdict: `FAIL`
- Model: `deepseek/deepseek-v4-flash`
- Task success rate: `4/5`
- Candidate-controllable success rate: `1.0`
- Benchmark artifact count: `1`
- Invalid tool-call ratio: `0.0`
- Semantic preflight rejections: `0`
- Average rounds: `2.4`
- P50/P95: `7340.0 / 9399.0 ms`
- Estimated cost: `$0.00270088`

## Per-sample Results

| Index | Reward | Rounds | Classification | Tool sequence |
| ---: | ---: | ---: | --- | --- |
| 0 | 1 | 2 | none | execute_sql → commit_final_answer |
| 20 | 1 | 2 | none | execute_sql → commit_final_answer |
| 40 | 0 | 3 | benchmark_ground_truth_omits_valid_second_row | execute_sql → execute_sql → commit_final_answer |
| 60 | 1 | 2 | none | execute_sql → commit_final_answer |
| 80 | 1 | 3 | none | execute_sql → execute_sql → commit_final_answer |

## Boundary

- This is a declared five-sample read-only subset, not the 300-sample DBBench standard score or AgentBench leaderboard score.
- The subset excludes database mutations so a failure cannot alter persistent user data; each sample still uses an isolated official MySQL environment.
- At pinned index 40, the official label omits Ecuador even though the official standard SQL and table rows return both United States and Ecuador; the official zero is preserved.
- Qwen comparison and cross-provider judging remain blocked by two distinct credentials returning HTTP 401.
- No model training or local GPU execution occurred during this evaluation.
