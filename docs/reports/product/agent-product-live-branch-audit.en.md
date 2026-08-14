# Agent Product Branch Live-Backtest Audit

Language: [Chinese](./agent-product-live-branch-audit.md) | English

Status: **AUDIT PASS; HISTORICAL FAILURE PRESERVED**

- Frozen product branches: `16`
- Historical exact-commit live passes: `1`
- Historical exact-commit live failures: `1`
- Historical commits without a compatible live runner: `14`
- Latest cumulative runtime coverage: `16/16`

## Conclusion

The latest cumulative runtime covers all 16 frozen product capabilities and passes the relevant deterministic gates, live API behavior backtests, and real-service checks. Historical-commit evidence is a separate dimension and is not conflated with the cumulative result.

## Historical Exact Commits

| Branch | Commit | Result |
| --- | --- | --- |
| `codex/agent-runtime-integration` | `ac6f83e` | Real DeepSeek in a detached worktree: `3/3`, 14/14 checks, 0 P0, and 0 unauthorized mutations |
| `codex/agent-product-benchmarks` | `1642ae6` | Real replay aborted after about 212 seconds with `all_model_candidates_failed`; the old runner had no checkpoint, so the failure remains a failure |
| Other 14 product branches | Frozen commits | Their historical code predates the compatible live runner; they are marked `not_executable_with_current_runner` and covered by the latest cumulative runtime |

## Evidence Boundary

The JSON peer lists every commit, status, and evidence artifact. `passed: true` means the audit is complete and honest; it does not mean both executable historical commits passed, and it does not clear the independent-judge, blind-human, or official comparable-benchmark blockers.
