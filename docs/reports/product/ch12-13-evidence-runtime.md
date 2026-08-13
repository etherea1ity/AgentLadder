# 第 12–13 章证据运行时门禁

语言：中文 | [English](./ch12-13-evidence-runtime.en.md)

Status: **PASS**

- 评分器: `klara.chapter12-13-evidence-runtime.v1`
- 检查: `15/15`

## 验收检查

| 检查 | 结果 |
| --- | --- |
| bilingual_tutorials_exist | PASS |
| bounded_live_public_page_smoke | PASS |
| citation_uses_fetched_source_url | PASS |
| critical_abstention_accuracy | PASS |
| critical_citation_precision | PASS |
| critical_citation_recall | PASS |
| critical_contradiction_recall | PASS |
| dangling_stale_irrelevant_contradiction_tests_exist | PASS |
| duplicate_evidence_rejected_by_contract | PASS |
| fetched_source_precedes_verification | PASS |
| gold_gate_passed | PASS |
| private_submission_not_public | PASS |
| real_loop_replaces_unchecked_prose | PASS |
| stage_manifest_exists | PASS |
| ui_projects_evidence_state | PASS |

## 关键金标指标

| Metric | Value |
| --- | ---: |
| citation_precision | 1.000 |
| citation_recall | 1.000 |
| contradiction_recall | 1.000 |
| abstention_accuracy | 1.000 |

## 受限在线探针

```json
{
  "bounded": true,
  "fetched_at": "2026-08-13T11:11:27.979724+00:00",
  "final_url": "https://example.com/",
  "http_status": 200,
  "status": "passed",
  "text_length": 127,
  "title": "Example Domain",
  "url": "https://example.com/"
}
```

## 解释边界

通过只证明真实 Klara 回路中的逐 claim 证据控制、关键确定性金标指标、公开投影边界与一次受限公开页面抓取成立；它不代表开放域事实准确率达到完美，也不代表任意研究任务都已解决。
