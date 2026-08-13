# Chapter 13: Research Agent

Language: [Chinese](./ch13-research-agent.md) | English

> Chapter 13 puts the Chapter 12 evidence gate inside a bounded web-research state machine. The target is observable, stoppable, reproducible research—not an unbounded crawler or a black-box `deep_search` tool.

![Research Agent evidence flow](../assets/ch12-13-evidence-flow.svg)

## Problem

A research Agent is more than an Agent that can call search. It must know when web access is required, when a search snippet remains only a lead, how many independent sources were fetched, whether source quality is sufficient, when the budget is exhausted, and whether the final answer passed claim-level control. If those states exist only in model prose, users cannot see real progress and failures cannot be replayed.

## Mechanism One: Runtime-Owned Research State Machine

At run start, `WebResearchController` classifies a request as stable or time-sensitive and selects quick, deep, or off mode. Quick defaults to at most three searches, five fetches, and one good source. Deep defaults to at most eight searches, sixteen fetches, three good sources, and two independent domains.

```text
web_required
-> searching
-> fetching
-> verifying
-> ready | need_more_search | need_more_fetch | budget_exhausted
```

The system prompt receives only compact state, gaps, and next-step hints. Older complete `web_fetch` observations become summaries that preserve source ids so long pages do not consume context forever. Search, fetch, and finalization remain scheduled by the same `KlaraLoop`; there is no hidden second Agent loop.

## Mechanism Two: Source Readiness And Conflict

`EvidenceLedger` strictly separates candidates from fetched sources. Readiness requires at least readable, request-relevant fetched content; deep research also requires multiple independent domains. Low-quality pages, missing relevant terms, duplicate URLs, or duplicate bodies cannot masquerade as independent evidence.

Conflict is not a simple majority vote. In `evidence_submit`, the model must classify each claim/source pair as `supported | contradicted | insufficient` and provide a source witness. A contradicted required claim cannot be published as a certain fact. The system may continue research, narrow the conclusion, or explicitly abstain.

## Mechanism Three: Product Observability

Public events cover research start, candidates, sources, readiness, structured answer submission, and verification. API projection removes final drafts and witness content, retaining counts, status, claim id, judgment, source id, and citation key.

The chat Evidence status displays:

- Gathering evidence: sources or independent domains are still missing;
- Sources ready: research readiness passed but claim verification is pending;
- Evidence verified: required claims passed;
- Evidence blocked: verification failed;
- Evidence-limited answer: the system explicitly abstained or preserved uncertainty.

This is not fabricated thinking animation. State comes only from persisted public events, and screen readers receive changes through `aria-live=polite`.

<details>
<summary>Why does budget exhaustion not mean factual correctness?</summary>

Budget exhaustion only means no further network action is available. The Chapter 12 evidence gate still verifies every claim. When evidence is insufficient, the model must submit an explicit abstention; lack of money or calls cannot release an unsupported assertion.

</details>

## Real Source And Runtime Experiment

- `src/klara/services/web/research.py`: mode, budget, EvidenceLedger, readiness, and compaction.
- `src/klara/tools/builtin/web_search/`: candidate cards, provider limitations, and whether freshness is actually enforced.
- `src/klara/tools/builtin/web_fetch/`: SSRF boundary, bounded content, quality signals, and fetch time.
- `src/klara/services/evidence/runtime.py`: final claim gate.
- `apps/web/src/components/ChatWorkspace.tsx`: normal-user source and claim status.

```powershell
$env:PYTHONPATH = "src"
pytest -q tests/klara/services/test_web_research.py tests/klara/services/evidence
python -m klara.eval.chapter12_13_cli `
  --json-out docs/reports/product/ch12-13-evidence-runtime.json `
  --markdown-out docs/reports/product/ch12-13-evidence-runtime.md `
  --markdown-en-out docs/reports/product/ch12-13-evidence-runtime.en.md
```

The real-loop fixture executes `web_fetch -> evidence_submit -> final` and confirms that published text comes from the verified submission rather than an arbitrary later draft. The live smoke reads only one public page, at most 2,000 characters, with a twelve-second timeout.

## Limits And Next Step

The default no-key search provider does not guarantee freshness hints, and some JavaScript pages cannot be extracted. These limitations enter the observation instead of being hidden. A public-page smoke proves only current network and fetcher availability. Open-domain research quality must still be measured at Agent Product Freeze with a frozen answer model, hidden cases, real questions, and blinded human review.

The next stage is the Permission Engine. It will make network domain, resource, actor, tenant, risk, and side effect explicit authorization conditions. This chapter's network tools do not substitute for a complete permission system.
