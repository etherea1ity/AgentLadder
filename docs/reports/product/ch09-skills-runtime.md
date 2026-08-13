# Chapter 9 Skills 运行时门禁

语言：中文 | [English](./ch09-skills-runtime.en.md)

Status: **PASS**

- 评分器: `klara.chapter09-skills-runtime.v1`
- 门禁类型: `deterministic_progressive_disclosure_gate`
- 检查: `14/14`

## 验收检查

| 检查 | 结果 |
| --- | --- |
| api_is_metadata_only | PASS |
| bilingual_tutorial_exists | PASS |
| catalog_is_metadata_only | PASS |
| frontend_explains_loading_and_permissions | PASS |
| irrelevant_skill_body_stays_out | PASS |
| loaded_event_projects_to_api | PASS |
| project_precedence_is_deterministic | PASS |
| public_trace_hides_skill_body | PASS |
| run_completes_after_loading | PASS |
| selection_and_version_are_traced | PASS |
| skill_body_loads_after_view | PASS |
| stage_manifest_exists | PASS |
| three_scopes_supported | PASS |
| tool_escalation_is_rejected | PASS |

## 公开加载证据

```json
{
  "body_content_exposed": false,
  "loaded_count": 1,
  "name": "review",
  "reference": null,
  "scope": "project",
  "sha256": "346947a020a680c5965ccf8f3939baa806dda67f78a2a65740f260dc8ecd0cf4",
  "version": "1.0.0"
}
```

## 解释边界

通过表示内置、用户和项目 Skills 的确定性优先级、元数据优先发现、显式按需加载、依赖/工具/权限失败关闭、安全生命周期投影和响应式目录界面均已得到确定性证明。它不代表远程市场或生产级组织 Skill 注册中心已经完成。
