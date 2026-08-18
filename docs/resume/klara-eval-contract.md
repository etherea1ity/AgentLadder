# Klara Eval Contract

本文件是 AgentLadder / Klara 三路对比实验的冻结契约。执行期间只允许按本文件明确授权的变更修改；任何超出范围的变化都必须先更新本文件并重新冻结。

- 创建时间: 2026-08-16
- 本地 git commit: 1225e78a9595615b63e9b6e68658a7965e337ef3
- 工作区状态: 仅 .gitignore 本地改动（新增 .env.deepseek-original 忽略项），不影响训练源码

## models

- klara:
  - architecture: decoder-only, 4-expert top-2 sparse MoE
  - normalization: RMSNorm
  - position: RoPE
  - attention: GQA
  - ffn: SwiGLU
  - total_params_target: ~124M（以最终 print 的实测参数量为准）
  - vocab: BPE（目标 ~28000，以最终词表为准）
  - max_sequence_length: 1024
- qwen:
  - base: Qwen2.5-1.5B-Instruct
  - variants: [qlora, no_finetune]
  - qlora: 默认 LoRA target = q/k/v/o + gate/up/down projections
- teacher_and_baseline:
  - model: DeepSeek V4 Pro（教师 rollout 与 DeepSeek baseline 一致）

## data

- clean_train_trajectories: 4000
- dev_tasks: 200
- hidden_tasks: 800
- 约束:
  - hidden 必须与 train/dev 完全 disjoint，不得复用训练任务。
  - hidden 优先来自 BFCL 官方 test split + 自留 holdout。
  - 轨迹只允许来自冻结 Harness + 冻结 tool backend。
  - 记录数据 license，过滤 PII。

## metrics

- task_success
- tool_call_accuracy
- invalid_call_rate
- token_usage
- latency
- cost

## eval

- same_harness: true
- same_tool_schema: true
- same_hidden_set: true
- same_decode_budget: true
- frozen_tool_backend: true（eval_mode 下工具结果来自 fixture store）

## frozen artifacts（执行中逐步填充，不得随意变更）

- random_seed: （待冻结）
- train_manifest_sha256: （待冻结）
- dev_manifest_sha256: （待冻结）
- hidden_manifest_sha256: （待冻结）
- tool_schema_sha256: （待冻结）
- prompt_version: （待冻结）
- evaluator_version: （待冻结）

## frozen tool schema（任务与评测统一使用）

- web_search
- web_fetch
- memory_search
- current_time
- evidence_submit
- update_activity
- skills_list
- skill_view
