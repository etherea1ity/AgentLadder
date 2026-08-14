# AgentLadder 官方 τ2 Mock 真实回测

语言：中文 | [English](./agent-product-tau2-mock-live.en.md)

- 结论: `未通过`
- 候选模型: `deepseek/deepseek-v4-flash`
- 任务数: `10`
- 平均奖励: `0.8`
- `pass^1`: `0.8`
- 候选工具动作准确率: `8/8`
- 基准/评估器伪失败: `2`
- P0: `0`

## 逐任务结果

| 任务 | Reward | 工具 | 终止原因 |
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

## 边界

- τ2 负责用户模拟、工具执行、对话编排和官方奖励；Klara 负责 persona、真实 Provider 调用、工具 schema 转换与协议防泄漏。
- 这是官方 mock 域适配烟测，不是已发表榜单域的可比成绩。
- 这不是完整 AgentLadder 产品运行时分数；持久化、权限、Memory、Scheduler、MCP 和 Team 另有真实回测。
- 当前千问凭据真实返回 HTTP 401，因此本轮候选使用 DeepSeek。
- 两个官方 0 分均保留：一个是 `COMMUNICATE` 精确子串评估器拒绝自然同义回答；一个是 user-tool fixture 的 gold DB 与场景要求冲突。没有把它们改写成满分。
