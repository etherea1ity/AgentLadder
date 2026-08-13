# Chapter 18: Production Runtime and Evaluation Bridge

Language: [Chinese](./ch18-production-runtime-and-eval-bridge.md) | English

Previous: [Chapter 17: MCP and External Tools](./ch17-mcp-and-external-tools.en.md)

Next: [Lab A: Trace Dataset and Evaluation](../skills/roadmap.md#lab-a---trace-dataset-and-evaluation)

Roadmap: [Klara Roadmap](../skills/roadmap.md)

---

## Chapter in one sentence

Klara now has a production-shaped path where a signed identity owns every session and job, workers act through expiring compare-and-swap leases, terminal state and notifications commit together, and only an authorized redacted trace can cross into evaluation or training.

![Klara Agent behavior evaluation contract](../assets/ch18-agent-eval-contract.svg)

| Boundary | Runtime guarantee |
| --- | --- |
| credential → principal | signature, issuer, audience, lifetime, tenant, user, and role are verified |
| principal → data | every owner read filters tenant and user; a foreign object is opaque |
| queue → worker | only the holder of an unexpired hashed lease can heartbeat or finish |
| job → notification | terminal transition and Outbox insert share one transaction |
| public trace → dataset | ownership, path containment, schema, redaction, linkage, split, and hashes are checked |
| baseline → candidate | identical fixture and split hashes are mandatory; P0 and resource regressions fail |

## Quick experience

The existing `/api` path remains the local learning adapter for the Chapter UI. The new `/api/production` path is independently authenticated and is the path a deployment or worker should use.

```powershell
$env:KLARA_AUTH_MODE = "development"
\.\scripts\dev.ps1 -Restart
```

On the same workstation, request a short-lived development token:

```powershell
$tokenResponse = Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/api/production/auth/dev-token `
  -ContentType application/json `
  -Body '{"tenant_id":"demo-tenant","user_id":"demo-user","roles":["owner","operator"]}'
$headers = @{ Authorization = "Bearer $($tokenResponse.access_token)" }
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/production/whoami -Headers $headers
```

`/auth/dev-token` is loopback-only and disappears when `KLARA_AUTH_MODE=production`. Production startup refuses to invent a signing key: deployment must supply `KLARA_AUTH_SIGNING_KEY` through its secret channel. Never put that value in Git, TOML, a job payload, or a trace.

Run the deterministic chapter gate:

```powershell
$env:PYTHONPATH = "src;."
python -m klara.eval.chapter18_cli `
  --repository-root . `
  --json-out docs/reports/product/ch18-production-runtime.json `
  --markdown-out docs/reports/product/ch18-production-runtime.md `
  --markdown-en-out docs/reports/product/ch18-production-runtime.en.md
```

## 1. Authentication is a runtime boundary

`AuthService` uses a compact versioned HMAC-SHA256 bearer format for Klara's trusted deployment boundary. Verification checks the exact header, constant-time signature, token schema, issuer, audience, issued time, expiry, and maximum lifetime before creating a `Principal`. A principal contains a tenant, user, roles, token ID, and expiry; public projection omits the token ID and credential.

Roles are intentionally small: `owner` and `operator` create and inspect their own sessions/jobs, `worker` claims tenant jobs, `evaluator` exports an owned trajectory, and `admin` reads payload-free metrics. `admin` can satisfy a role check, but it does not change the repository's owner filter. A managed OIDC or workload-identity gateway may authenticate people and mint this internal credential; deploying that identity provider is outside the repository.

The development issuer is not a production login system. It only makes the boundary reproducible on one workstation, accepts no password, and is unavailable remotely or in production mode.

## 2. Versioned persistence and opaque tenancy

`ProductionRepository` applies immutable SQLite migrations under `BEGIN IMMEDIATE` and records each migration checksum in `schema_migrations`. Restarting is idempotent; changed migration text fails startup instead of silently mutating an existing database.

Sessions and jobs store `tenant_id` and `owner_id`. Owner APIs put both fields in every query, so another user in the same tenant and the same user name in another tenant receive the same not-found result. Workers use a separate tenant-scoped query only after the `worker` role check. Public job records expose lifecycle metadata and a payload hash, never the question, result, lease hash, or worker credential.

The current repository uses SQLite WAL for one-host reliability. `PostgresProductionRepository` is the deployment adapter: it uses JSONB, transaction contexts, and `FOR UPDATE SKIP LOCKED` for multiple workers while keeping the same owner predicates, CAS leases, and Outbox contract. Install the `production-postgres` extra and select it explicitly through `KLARA_DATABASE_URL=postgresql://...`. This stage also ran a real driver/migration/isolation/queue/lease/Outbox/JSONB/state/revocation integration test against a disposable PostgreSQL 16 Alpine container. Its image digest and result are in the machine report, and the container was removed afterward.

The SQLite operations CLI also supplies `integrity`, consistent `backup`, verified `restore`, and retention. The rollback policy is forward-only migration: restore preserves a `.pre-restore` copy and validates quick check, foreign keys, and migration versions before promotion. The repository does not pretend that unsafe automatic down-migrations are supported.

## 3. Idempotent queue, leases, cancellation, and event streaming

Enqueue requires an `Idempotency-Key` unique per tenant and owner. The same key plus the exact canonical payload returns the original job; the same key with different content fails. Payloads and results are bounded to 64 KiB.

Claiming runs in an immediate transaction. It recovers expired jobs, selects one available row, moves it from `queued` to `running`, increments the attempt, stores only the SHA-256 of a random lease, and returns the raw lease once to the worker. Heartbeat, completion, and failure compare the hash and expiry. A forged or stale lease cannot finish a job.

`ProductionQueueWorker` is the adapter seam for the frozen Agent runtime. Its executor sees the bounded payload, stable job/run IDs, attempt count, a cooperative `cancel_requested` probe, and a `heartbeat()` method. It never sees the raw lease. An exception stores only the exception class as a public error code; provider text does not enter the database.

Cancellation is cooperative for a running job and immediate for a queued job. Public job events are monotonically sequenced and contain state, attempt, error code, or result hash—not prompt/result text. `/events/stream` replays existing events, polls for new events, emits SSE IDs, and closes at a terminal state or client disconnect.

## 4. Transactional Outbox

A terminal job transition and `prod_outbox` insert happen in the same database transaction. The event contains only job ID, run ID, and terminal state. Delivery has its own hashed, expiring lease and acknowledgement. A crashed delivery can be reclaimed without replaying the Agent job; a forged delivery token cannot acknowledge it.

This separates task effects from notification effects. It does not claim exactly-once delivery to an arbitrary external system. Consumers still use `event_id` as their idempotency key.

## 5. Authorized trajectory export

`TrajectoryExportService` first proves that the job belongs to the caller. The requested trace must resolve under a configured trace root. The exporter selects the job's run, orders events by sequence, and calls the Chapter 3 trajectory projection.

The dataset retains only:

- lifecycle state and bounded outcome labels;
- tool name and tool-call linkage, without arguments or returned content;
- explicit source/claim IDs;
- approved numeric latency, token, and cost fields.

It drops the raw prompt, final answer text, tool arguments/results, provider reasoning, and private references. Validation enforces contiguous sequence numbers, one run ID, monotonic turns, complete tool start/terminal pairs, declared source/claim links, and secret-pattern scans. A deterministic group-level hash assigns train/validation/test so wording variants cannot be manually moved after inspection.

Each export receives an opaque ID and tenant-hashed directory. `manifest.json` links source trace hash, job payload hash, run lineage hash, schema version, split counts, dataset hash, and privacy assertions. The repository records the dataset and manifest hashes for audit without storing their contents again.

## 6. Frozen regression comparison

`klara.eval.regression_cli` compares a baseline and candidate behavior report without the frontend. It refuses different fixture hashes, split hashes, schemas, or observation counts. A candidate must keep critical, overall, normal, reference, independent-judge, human-acceptance, P0, and severe-mismatch metrics non-inferior.

It also caps aggregate candidate/baseline latency at `1.25`, tokens at `1.10`, and cost at `1.10` by default. Zero baselines remain strict: a candidate may stay zero but cannot introduce previously absent cost. The JSON report is the source of truth; Chinese and English Markdown are mirrors.

The generated Chapter 18 control comparison uses the same frozen report on both sides. It proves that comparison code and anti-drift checks work. It is not yet the final current-Agent-vs-GPT behavioral judgment; that occurs at Agent Product Freeze with real observations and independent grading.

## 7. Observability and privacy

Production middleware creates or bounds a request ID, returns it to the caller, adds `nosniff` and `no-store`, and aggregates method, route template, status class, and duration. It never labels metrics with tenant, user, prompt, token, job ID, exception text, or URL query. Only `admin` can read the aggregate metrics endpoint.

Audit rows store tenant, actor, action, target type, target-ID hash, request-ID hash, and time. They intentionally omit bearer values, request bodies, results, and hidden model reasoning.

## Tests and reproduction

```powershell
python -m pytest `
  tests/klara/production `
  tests/apps/api/test_production_route.py `
  tests/klara/eval/test_regression.py `
  tests/klara/eval/test_chapter18.py -q
python -m pytest -q
npm --prefix apps/web test -- --run
npm --prefix apps/web run build
git diff --check
```

The focused suite covers signature tampering/expiry, missing production keys, role separation, same-tenant and cross-tenant opacity, migration checksums, idempotency collisions, queue recovery, forged leases, heartbeat, cancellation, worker retry, secret non-persistence, Outbox acknowledgement, export path containment, trace redaction/linkage/hashes, API projection, and regression failure injection.

## Exercises

1. Advance a fake clock beyond one worker lease and verify a second worker recovers the job while the first lease can no longer complete it.
2. Use the same idempotency key with a changed `maximum_steps` and verify the queue rejects it.
3. Add `authorization` to a temporary trajectory object and verify the privacy validator identifies its exact path.
4. Increase candidate token totals to `1.11×` baseline and confirm the regression report fails while all task-success rates remain equal.
5. Implement a PostgreSQL repository adapter and run the unchanged service/evaluator contract against it.

## Limitations and next stage

This chapter proves real authenticated multi-user isolation, backup/restore/retention, and durable queue semantics on SQLite and passes a real disposable PostgreSQL 16 integration run. No external OIDC provider was configured, so that provider smoke remains `not_executed`; the RS256 discovery/JWKS/claim/revocation path uses generated keys and deterministic metadata. Multi-region consensus, managed at-rest encryption, and an external broker remain deployment operations rather than local passes.

The Agent runtime is still frozen from learned-policy takeover. Lab A next collects real, licensed, contamination-reviewed trajectories through this bridge and fixes the evaluation set. Only after the full Agent Product Freeze may HKU training start.
