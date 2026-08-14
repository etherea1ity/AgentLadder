# AgentBench FC DBBench 真实回测

语言：中文 | [English](./agent-product-agentbench-db-live.en.md)

- 结论: `未通过`
- 模型: `deepseek/deepseek-v4-flash`
- 成功率: `4/5`
- 候选侧可控成功率: `1.0`
- 基准数据缺陷数: `1`
- 非法工具调用比例: `0.0`
- 语义预检拦截数: `0`
- 平均轮数: `2.4`
- P50/P95: `7340.0 / 9399.0 ms`
- 估算成本: `$0.00270088`

## 逐样本结果

| Index | Reward | 轮数 | 归因 | 工具序列 |
| ---: | ---: | ---: | --- | --- |
| 0 | 1 | 2 | none | execute_sql → commit_final_answer |
| 20 | 1 | 2 | none | execute_sql → commit_final_answer |
| 40 | 0 | 3 | benchmark_ground_truth_omits_valid_second_row | execute_sql → execute_sql → commit_final_answer |
| 60 | 1 | 2 | none | execute_sql → commit_final_answer |
| 80 | 1 | 3 | none | execute_sql → execute_sql → commit_final_answer |

## 边界

- 这是预先声明的 5 条只读 DBBench 子集，不是 300 条标准集或 AgentBench 榜单分数。
- 每条样本使用官方 AgentRL controller、DBBench worker、隔离 MySQL 环境和官方 reward。
- 候选侧使用 Klara persona、AgentLadder Provider 适配器和协议防泄漏；未收集隐藏推理。
- 本阶段没有训练模型，也没有使用本机 GPU。
