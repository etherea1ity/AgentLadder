# Main Agent Runtime Integration

Language: [Chinese](./agent-runtime-integration.md) | English

Status: **PASS**

Mechanism: the model-facing tools are thin adapters over the same durable services used by API and UI; permission decisions remain outside model prose.

## Runtime tools

`task_list`, `task_create`, `task_control`, `schedule_list`, `schedule_create`, `schedule_control`, `team_list`, `subagent_spawn`, `teammate_create`, `team_message`, `team_stop`, `worktree_create`, `worktree_inspect`, `worktree_remove`

## Live model smoke

Pinned model: `deepseek/deepseek-v4-flash`; cases: `3/3`; tokens: `7100`; latency: `41045 ms`.

## Acceptance checks

| Check | Result |
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

## Authority sequence

1. The model requests `task_create`.
2. The permission hook persists an exact request and blocks the mutation.
3. The owner grants `ALLOW_TASK`.
4. The same call creates one task in the shared repository.

## Reproduce

```powershell
$env:PYTHONPATH='src'
python -m klara.eval.runtime_integration_cli --json-out docs/reports/product/agent-runtime-integration.json --markdown-out docs/reports/product/agent-runtime-integration.md --markdown-en-out docs/reports/product/agent-runtime-integration.en.md
python -m klara.eval.runtime_integration_live_cli --json-out docs/reports/product/agent-runtime-integration-live.json
python -m pytest tests/klara/app/test_runtime_tools.py tests/klara/eval/test_runtime_integration.py -q
```

## Limits

- The deterministic gate uses a scripted model to isolate runtime authority and state sharing from model quality.
- The live smoke covers only three frozen cases; broad behavior, public benchmark, judge, and human gates remain separate.
- Agent Product Freeze and broad hidden/human/reference evaluation remain later gates.
- No HKU or model training is performed in this stage.
