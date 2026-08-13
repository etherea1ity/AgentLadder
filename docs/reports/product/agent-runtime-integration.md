# 主 Agent 运行时集成

语言：中文 | [English](./agent-runtime-integration.en.md)

Status: **PASS**

机制：模型可调用工具只是 API/UI 所用真实持久服务的薄适配层；权限决定仍独立于模型文本。

## 运行时工具

`task_list`, `task_create`, `task_control`, `schedule_list`, `schedule_create`, `schedule_control`, `team_list`, `subagent_spawn`, `teammate_create`, `team_message`, `team_stop`, `worktree_create`, `worktree_inspect`, `worktree_remove`

## 真实模型烟测

固定模型：`deepseek/deepseek-v4-flash`；用例：`3/3`；Token：`7100`；延迟：`41045 ms`。

## 验收检查

| 检查 | 结果 |
| --- | --- |
| `all_runtime_tools_have_unique_model_specs` | PASS |
| `approval_request_is_durable_and_exact` | PASS |
| `bilingual_report_contract_exists` | PASS |
| `created_task_is_visible_from_shared_service` | PASS |
| `main_profile_exposes_every_runtime_tool` | PASS |
| `mutation_fails_closed_before_approval` | PASS |
| `no_internal_protocol_in_answers` | PASS |
| `permission_grant_id_not_in_task_database` | PASS |
| `public_trace_omits_raw_tool_arguments` | PASS |
| `question_answer_consistency` | PASS |
| `real_model_runtime_smoke_passes` | PASS |
| `run_service_injects_shared_product_services` | PASS |
| `same_exact_action_executes_after_allow_task` | PASS |
| `stage_manifest_exists` | PASS |

## 权限顺序

1. 模型请求 `task_create`。
2. 权限 hook 持久化精确申请并阻止变更。
3. 所有者授予 `ALLOW_TASK`。
4. 相同调用在共享仓库中创建唯一任务。

## 复现

```powershell
$env:PYTHONPATH='src'
python -m klara.eval.runtime_integration_cli --json-out docs/reports/product/agent-runtime-integration.json --markdown-out docs/reports/product/agent-runtime-integration.md --markdown-en-out docs/reports/product/agent-runtime-integration.en.md
python -m klara.eval.runtime_integration_live_cli --json-out docs/reports/product/agent-runtime-integration-live.json
python -m pytest tests/klara/app/test_runtime_tools.py tests/klara/eval/test_runtime_integration.py -q
```

## 限制

- 确定性门禁使用脚本模型，将运行时权限与共享状态同模型质量分开验证。
- 真实烟测仅覆盖 3 个冻结用例；广泛行为、公共基准、独立裁判与人工门禁仍单独执行。
- Agent Product Freeze 与广泛隐藏集/人工/参考模型评测仍属于后续门禁。
- 本阶段没有执行 HKU 或模型训练。
