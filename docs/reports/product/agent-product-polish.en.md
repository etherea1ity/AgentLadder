# Agent Product Polish Gate

Language: [Chinese](./agent-product-polish.md) | English

Status: **PASS**

Mechanism: model, persistence, and developer-trace data must cross a public-output boundary before entering chat or product views.

![Desktop Agent control plane](./agent-product-polish-desktop.png)

## Acceptance evidence

- Scorer: `klara.agent-product-polish.v1`
- Checks: `15/15`
- Targeted Python tests: `64 passed`
- Frontend tests: `20 files / 71 passed`
- Post-repair P0 strange responses: `0`

| Check | Result |
| --- | --- |
| `browser_privacy_console_and_screenshots_pass` | PASS |
| `cancelled_run_is_not_restarted` | PASS |
| `deepseek_dsml_is_normalized` | PASS |
| `desktop_has_no_horizontal_overflow` | PASS |
| `developer_trace_is_separate_from_chat` | PASS |
| `evaluation_history_omits_hidden_cases` | PASS |
| `historical_protocol_markup_is_withheld` | PASS |
| `malformed_dsml_fails_closed` | PASS |
| `mobile_navigation_is_contained` | PASS |
| `overview_reads_current_backend_contracts` | PASS |
| `raw_jsonl_trace_is_not_returned_by_api` | PASS |
| `raw_provider_reasoning_is_not_public` | PASS |
| `run_cancelled_is_public_terminal_event` | PASS |
| `stage_manifest_exists` | PASS |
| `worktree_inspection_is_contained_and_read_only` | PASS |

## Repaired P0 counterexamples

### `provider-dsml-leak`

- Observed: A DeepSeek fallback returned DSML tool markup in assistant content.
- Repair: Normalize valid DSML, reject malformed DSML, and withhold legacy protocol text at the public read boundary.
- Regression: `tests/klara/infra/llm/test_openai_compatible.py; tests/klara/app/test_harness.py; tests/apps/api/test_sessions_route.py`

### `cancel-tail-events`

- Observed: A cancelled scheduled run retained public events after run_cancelled and could be implicitly revived.
- Repair: Make cancellation terminal and require an explicit durable-task retry before restart.
- Regression: `tests/apps/api/test_run_service_history.py`

## Reproduce

```powershell
$env:PYTHONPATH='src'
python -m klara.eval.product_polish_cli --json-out docs/reports/product/agent-product-polish.json --markdown-out docs/reports/product/agent-product-polish.md --markdown-en-out docs/reports/product/agent-product-polish.en.md
python -m pytest -q
Set-Location apps/web
npm test -- --run
npm run build
```

## Limits and next gate

- This is a product-polish stage, not Agent Product Freeze.
- The frozen task set has not yet been run against the live Agent and pinned reference with an independent judge and blind human review.
- Public memory benchmarks against Mem0 and Mem1 have not yet been executed.
- A full accessibility scanner, keyboard-only matrix, 200-percent zoom matrix, long-list profile, and reconnect/offline matrix remain.
- No HKU or model-training work was started.
