# AgentLadder Official tau2 Mock Live Backtest

Language: [Chinese](./agent-product-tau2-mock-live.md) | English

- Verdict: `FAIL`
- Candidate: `deepseek/deepseek-v4-flash`
- Tasks: `10`
- Average reward: `0.8`
- `pass^1`: `0.8`
- Candidate tool-action accuracy: `8/8`
- Benchmark/evaluator artifacts: `2`
- P0: `0`

## Per-task Results

| Task | Reward | Tools | Termination |
| --- | ---: | --- | --- |
| create_task_1 | 1.0 | get_users, create_task | user_stop / none |
| create_task_1_with_env_assertions | 1.0 | get_users, create_task | user_stop / none |
| create_task_1_nl_eval | 1.0 | get_users, create_task | user_stop / none |
| update_task_1 | 1.0 | update_task_status | user_stop / none |
| update_task_with_message_history | 1.0 | create_task, update_task_status | user_stop / none |
| update_task_with_initialization_data | 0.0 | update_task_status | user_stop / benchmark_communicate_exact_substring_artifact |
| update_task_with_initialization_actions | 1.0 | update_task_status | user_stop / none |
| update_task_with_history_and_env_assertions | 1.0 | create_task, update_task_status | user_stop / none |
| update_task_with_user_tools | 0.0 | update_task_status | user_stop / benchmark_gold_db_user_action_mismatch |
| impossible_task_1 | 1.0 | transfer_to_human_agents | user_stop / none |

## Boundary

- The mock domain is an official adapter smoke, not a comparable published tau2 leaderboard domain.
- DeepSeek also drives the official user simulator; deterministic rewards, not that model, decide success.
- This adapter does not exercise AgentLadder persistence, permissions, memory, scheduler, MCP, or team services.
- Qwen remains unavailable because the configured credential returns HTTP 401.
- Two mock failures are classified from public reward details as benchmark/evaluator artifacts; the official 0.8 score is preserved unchanged.
