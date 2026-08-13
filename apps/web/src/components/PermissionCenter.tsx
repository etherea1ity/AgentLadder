import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Ban, Check, Clock3, KeyRound, RefreshCw, ShieldCheck, ShieldX } from "lucide-react";
import { api } from "../api/client";
import type { PermissionEffect, PermissionGrantRecord, PermissionRequestRecord, PermissionState } from "../types/domain";

const EMPTY: PermissionState = {
  schema_version: "klara.permissions-state.v1",
  requests: [],
  grants: [],
  audit: [],
};

export function PermissionCenter({ onBackToChat }: { onBackToChat: () => void }) {
  const [state, setState] = useState<PermissionState>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState("");
  const pending = useMemo(() => state.requests.filter((item) => item.status === "pending"), [state.requests]);
  const active = useMemo(() => state.grants.filter((item) => item.status === "active"), [state.grants]);

  useEffect(() => {
    const controller = new AbortController();
    refresh(controller.signal);
    return () => controller.abort();
  }, []);

  async function refresh(signal?: AbortSignal) {
    setLoading(true);
    try {
      setState(await api.listPermissions(signal));
      setError("");
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") return;
      setError("Permission state is unavailable. Risky tool actions remain blocked.");
    } finally {
      setLoading(false);
    }
  }

  async function decide(request: PermissionRequestRecord, effect: PermissionEffect) {
    setBusy(request.request_id);
    setError("");
    try {
      const seconds = effect === "allow_once" ? 15 * 60 : effect === "allow_task" ? 24 * 60 * 60 : 7 * 24 * 60 * 60;
      await api.decidePermission(request.request_id, effect, seconds);
      await refresh();
    } catch {
      setError("The decision was not saved. No new authority was granted.");
    } finally {
      setBusy(null);
    }
  }

  async function revoke(grant: PermissionGrantRecord) {
    setBusy(grant.grant_id);
    try {
      await api.revokePermission(grant.grant_id);
      await refresh();
    } catch {
      setError("Revocation could not be verified. Treat this grant as active until refreshed.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <main className="permission-page" aria-label="Permission center">
      <header className="permission-header">
        <button className="memory-back" onClick={onBackToChat} aria-label="Back to chat"><ArrowLeft size={17} />Back to chat</button>
        <span className="memory-eyebrow"><KeyRound size={14} />Explicit authority</span>
        <h1>Permissions</h1>
        <p>Low-risk local reads follow the frozen policy. Network, paid, destructive, and control actions stop here until you approve their exact scope.</p>
      </header>
      <section className="permission-contract" aria-label="Permission guarantees">
        <span><ShieldCheck size={16} />Fail closed</span><span><Clock3 size={16} />Expiry enforced</span><span><ShieldX size={16} />Revocable</span>
        <button onClick={() => void refresh()} disabled={loading}><RefreshCw size={15} />Refresh</button>
      </section>
      {error ? <div className="memory-alert" role="alert">{error}</div> : null}
      {loading ? <div className="memory-empty" aria-live="polite">Loading permission state…</div> : null}

      {!loading && pending.length ? (
        <section className="permission-pending" aria-label="Approval requests">
          <h2>Awaiting your decision <span>{pending.length}</span></h2>
          {pending.map((request) => (
            <article className={`permission-dialog risk-${request.action.risk}`} role="dialog" aria-modal="true" aria-labelledby={`${request.request_id}-title`} key={request.request_id}>
              <div className="permission-dialog-head"><span className="permission-risk">{request.action.risk} risk</span><time dateTime={request.expires_at}>expires {new Date(request.expires_at).toLocaleString()}</time></div>
              <h3 id={`${request.request_id}-title`}>{request.action.tool_name}</h3>
              <dl><div><dt>Action</dt><dd>{request.action.capability}</dd></div><div><dt>Resource</dt><dd>{request.action.resource}</dd></div><div><dt>Side effect</dt><dd>{request.action.side_effect}</dd></div><div><dt>Requested again</dt><dd>{request.repeated_count}×</dd></div></dl>
              <p>{request.action.destructive ? "This action is destructive and cannot be undone by Klara." : request.action.externally_consequential ? "This action crosses the local runtime boundary." : "This action changes durable local state."}</p>
              <div className="permission-actions">
                <button className="danger" disabled={busy === request.request_id} onClick={() => void decide(request, "deny")}><Ban size={15} />Deny</button>
                <button disabled={busy === request.request_id} onClick={() => void decide(request, "allow_once")}><Check size={15} />Allow once</button>
                {request.scope.task_id ? <button disabled={busy === request.request_id} onClick={() => void decide(request, "allow_task")}>Allow for task</button> : null}
                <button disabled={busy === request.request_id} onClick={() => void decide(request, "allow_standing")}>Allow 7 days</button>
              </div>
            </article>
          ))}
        </section>
      ) : !loading ? <div className="memory-empty">No approval is waiting. Klara has not inferred any permission.</div> : null}

      <section className="permission-history" aria-label="Active and historical grants">
        <header><h2>Grant history</h2><span>{active.length} active</span></header>
        {state.grants.length ? state.grants.map((grant) => (
          <article key={grant.grant_id}>
            <div><strong>{grant.action.tool_name}</strong><span className={`grant-status is-${grant.status}`}>{grant.status}</span></div>
            <p>{grant.effect.replace(/_/g, " ")} · {grant.action.resource}</p>
            <small>Expires {new Date(grant.expires_at).toLocaleString()} · {grant.scope.task_id ? "task scoped" : "owner scoped"}</small>
            {grant.status === "active" ? <button disabled={busy === grant.grant_id} onClick={() => void revoke(grant)}>Revoke</button> : null}
          </article>
        )) : <p className="permission-no-history">No grants have been created.</p>}
      </section>
    </main>
  );
}
