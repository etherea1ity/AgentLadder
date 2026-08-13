# Chapter 14: Durable Task System

Language: [Chinese](./ch14-durable-tasks.md) | English

Previous: [Chapter 13: Research Agent](./ch13-research-agent.en.md)

Next: [Chapter 15: Background Scheduler](../skills/roadmap.md#chapter-15---background-scheduler)

Roadmap: [Klara Roadmap](../skills/roadmap.md)

---

## Chapter in one sentence

A chat Run is one visible interaction; a Durable Task is the persistent work unit that can continue across process death and prove who worked, how far it progressed, how many attempts occurred, and whether required outputs really exist.

![Klara Durable Task lifecycle](../assets/ch14-durable-task-lifecycle.svg)

## Quick start

```powershell
.\scripts\dev.ps1 -Restart
```

Open `http://127.0.0.1:5123` and select **Tasks** in the sidebar. Every chat Run enters the Task Board under the same `run_id/task_id`. Inspect state, progress, attempts, artifacts, and immutable history; resume paused/blocked work, retry eligible failures, or cancel non-terminal tasks.

Run the deterministic gate:

```powershell
$env:PYTHONPATH='src'
python -m klara.eval.chapter14_cli `
  --json-out docs/reports/product/ch14-durable-tasks.json `
  --markdown-out docs/reports/product/ch14-durable-tasks.md `
  --markdown-en-out docs/reports/product/ch14-durable-tasks.en.md
```

## Why Run status is insufficient

`queued/thinking/completed` can draw a chat interaction, but cannot answer:

- Which worker takes over after process failure?
- Why can a stale worker not continue writing after it returns?
- Did an external action already execute, and will recovery repeat it?
- Do the report or evidence required for completion actually exist?
- Are every pause, block, and failed attempt still auditable?

`RunService` therefore keeps its chat-facing projection while mapping the same ID into `DurableTaskService`. The Task is execution truth and chat state is the user-facing interaction projection; they are not competing loops.

## Complete persistence contract

Every `DurableTask` contains:

- a `tenant_id + owner_id + agent_id` identity partition;
- dependencies and parent/child lineage;
- state, progress, current step, and block reason;
- active attempt, attempt count, and maximum attempts;
- worker, lease hash, expiry, and heartbeat;
- checkpoint sequence;
- required artifacts and required evidence;
- creation, update, completion, and cancellation timestamps.

Attempts, checkpoints, artifacts, effect receipts, and events are persisted separately. A state transition and attempt closure commit in one SQLite transaction, with `updated_at` compare-and-swap preventing concurrent workers from overwriting each other.

## Code controls the state machine, not model claims

```text
waiting --dependencies satisfied--> ready --claim--> running
running --pause--> paused --resume--> ready
running --block--> blocked --resume--> ready
running --fail--> failed --retry budget--> ready
running --requirements satisfied--> completed
any non-completed state --cancel--> cancelled
```

Invalid transitions return conflicts. A second worker cannot claim a running task with a valid lease; a failed task can retry only while attempt budget remains; completed or cancelled work is not re-executed.

## Leases, heartbeats, and process-death recovery

Claim returns the raw lease token once, while SQLite stores only SHA-256. Progress, heartbeat, checkpoint, artifact, and terminal operations then require all of these:

1. the task remains running;
2. the token hash matches exactly;
3. the lease has not expired;
4. the active attempt exists and remains running.

After process death, the old lease expires. A new claim atomically closes the old attempt as `abandoned`, creates a new attempt, and returns the latest checkpoint metadata. The stale worker cannot write after it returns.

This chapter implements the generic expired-lease takeover primitive. Automatic scanning, timed claims, restart notifications, and recurring semantics belong to Chapter 15 Scheduler and are not claimed here.

## Public and recovery checkpoint views

Checkpoint payload remains in owner-scoped SQLite for recovery. Canonical JSON is capped at 256 KiB per payload, and non-JSON or NaN values are rejected. The ordinary API exposes only:

- checkpoint, attempt, and sequence identifiers;
- summary;
- payload SHA-256;
- field count, not field names or values.

Developers can verify recovery lineage without Task Board leaking secrets, prompts, or provider-private state.

## Idempotent effect receipts

A step with external side effects first calls `reserve_effect(task_id, idempotency_key)`. Its unique key is the owner-scoped task plus idempotency key:

```text
new key       -> reserved / should_execute=true
commit result -> committed + result_sha256
recovery call -> committed / should_execute=false
```

If a worker dies after the action, recovery observes a committed receipt instead of sending again. If failure lands across the reserve/action boundary, the tool must pass the same idempotency key into an external system that supports idempotency; a local receipt cannot invent cross-system exactly-once consensus.

## Artifact and evidence completion gate

A task may declare `required_artifacts` and `required_evidence`. `complete` queries the real artifact table:

- ordinary artifact names must cover every required artifact;
- only artifacts with `is_evidence=true` cover required evidence;
- any missing item leaves the task running and returns an explicit conflict.

HTTP query and fragment are removed before URIs become public. Only `http`, `https`, `workspace`, and `artifact` semantics are accepted so tokens do not travel into the UI.

## Cancellation propagation and immutable attempts

Cancelling a parent recursively cancels non-terminal descendants. A running child attempt closes as `cancelled`; an old attempt is never rewritten into a new attempt or erased by retry/recovery. Task detail returns attempts, artifacts, latest checkpoint metadata, and append-only events together.

## API, RunService, and Task Board

`/api/tasks` exposes create/list/detail, claim, heartbeat, progress, checkpoint, artifact, pause, block, resume, fail, retry, complete, and cancel. Owner scope is applied before every read. Guessing another tenant's task id still produces only `task_not_found`.

The existing `RunService` creates a same-ID task with every chat Run. Its worker thread claims the task, records runtime and answer progress, and enters the matching durable success, failure, or cancellation state. Task Board reads these backend contracts directly and does not hold a second lifecycle truth.

## What this chapter proves and does not prove

The deterministic gate covers dependencies, isolation, lease forgery, progress, checkpoint privacy, expired takeover, attempt history, effect deduplication, artifact/evidence completion, pause/resume/block/fail/retry, cancellation propagation, API, RunService integration, and Task Board source contracts. Full Python, frontend, and production-build regressions run separately.

This chapter does not claim distributed consensus or completed recurring schedules; the latter waits for Chapter 15. The question/answer consistency probe is a fixed contract control, not independent human/model review and not evidence of general ChatGPT equivalence.
