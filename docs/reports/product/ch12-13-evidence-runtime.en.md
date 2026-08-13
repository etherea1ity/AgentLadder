# Chapters 12-13 Evidence Runtime Gate

Language: [Chinese](./ch12-13-evidence-runtime.md) | English

Status: **PASS**

- Scorer: `klara.chapter12-13-evidence-runtime.v1`
- Checks: `15/15`

## Acceptance Checks

| Check | Result |
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

## Critical Gold Metrics

| Metric | Value |
| --- | ---: |
| citation_precision | 1.000 |
| citation_recall | 1.000 |
| contradiction_recall | 1.000 |
| abstention_accuracy | 1.000 |

## Bounded Live Smoke

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

## Interpretation Boundary

Passing proves claim-level control on the real Klara loop, deterministic critical gold metrics, safe public projections, and one bounded public-page fetch smoke. It is not an open-domain factual-accuracy or universal research claim.
