# Chapter 5 Todo Planning 门禁

语言：中文 | [English](./ch05-todo-planning.en.md)

Status: **PASS**

- 评分器: `klara.chapter05-todo-planning.v1`
- 门禁类型: `deterministic_product_gate`
- 检查: `14/14`

## 验收检查

| 检查 | 结果 |
| --- | --- |
| frontend_consumes_live_and_restored_plan | PASS |
| frontend_renders_accessible_plan | PASS |
| merge_advances_version | PASS |
| merge_is_ordered_upsert | PASS |
| one_active_item_enforced | PASS |
| product_path_persisted_plan | PASS |
| prompt_scopes_planning | PASS |
| restart_restores_plan | PASS |
| schema_is_versioned | PASS |
| session_delete_purges_plan | PASS |
| sse_projection_exists | PASS |
| stage_manifest_exists | PASS |
| todo_write_model_visible | PASS |
| trace_contains_plan_observation | PASS |

## 产品探针

```json
{
  "items": [
    {
      "id": "inspect",
      "status": "completed",
      "title": "Inspect"
    },
    {
      "id": "build",
      "status": "in_progress",
      "title": "Build"
    },
    {
      "id": "verify",
      "status": "pending",
      "title": "Verify"
    }
  ],
  "schema_version": "klara.todo-plan.v1",
  "session_id": "sess_6851f0c9fe914a92b33428d41b51b02c",
  "updated_at": "2026-08-13T05:00:52.121823+00:00",
  "version": 1
}
```

## 解释边界

通过证明本地当前会话 Todo Planning 的状态机、持久化、产品入口、trace/SSE 投影与前端契约成立；它不代表通用规划质量或 ChatGPT 等价性。
