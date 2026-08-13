# Chapter 5 Todo Planning Gate

Language: [Chinese](./ch05-todo-planning.md) | English

Status: **PASS**

- Scorer: `klara.chapter05-todo-planning.v1`
- Gate kind: `deterministic_product_gate`
- Checks: `14/14`

## Acceptance Checks

| Check | Result |
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

## Product Probe

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
  "session_id": "sess_3b2b4f2da4414fc7a5eea22bbb8dc73c",
  "updated_at": "2026-08-13T04:10:41.758176+00:00",
  "version": 1
}
```

## Interpretation Boundary

Passing proves the local current-session Todo Planning state machine, persistence, product wiring, trace/SSE projection, and frontend contract. It does not claim general planning quality or ChatGPT equivalence.
