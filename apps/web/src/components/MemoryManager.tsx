import { FormEvent, useEffect, useMemo, useState } from "react";
import { ArrowLeft, Brain, Check, Clock3, Pencil, Plus, Search, ShieldCheck, Trash2, X } from "lucide-react";
import { api } from "../api/client";
import type { MemoryKind, MemoryRecord, MemorySensitivity } from "../types/domain";

const MEMORY_KINDS: { value: MemoryKind; label: string }[] = [
  { value: "user_preference", label: "Preference" },
  { value: "stable_fact", label: "Stable fact" },
  { value: "episodic", label: "Episode" },
  { value: "task", label: "Task" },
  { value: "agent_learning", label: "Agent lesson" },
];

export function MemoryManager({ onBackToChat }: { onBackToChat: () => void }) {
  const [records, setRecords] = useState<MemoryRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<MemoryKind | "all">("all");
  const [draft, setDraft] = useState("");
  const [draftKind, setDraftKind] = useState<MemoryKind>("user_preference");
  const [sensitivity, setSensitivity] = useState<MemorySensitivity>("standard");
  const [editing, setEditing] = useState<string | null>(null);
  const [editingText, setEditingText] = useState("");
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    api.listMemories(controller.signal)
      .then((value) => setRecords(value.records))
      .catch((caught) => {
        if (caught instanceof DOMException && caught.name === "AbortError") return;
        setError("Memory is unavailable. Chat remains usable without it.");
      })
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, []);

  const visible = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return records.filter((record) => {
      if (kind !== "all" && record.kind !== kind) return false;
      return !needle || record.content.toLocaleLowerCase().includes(needle) || record.provenance.source_type.toLocaleLowerCase().includes(needle);
    });
  }, [records, query, kind]);

  async function remember(event: FormEvent) {
    event.preventDefault();
    const content = draft.trim();
    if (!content) return;
    setBusy("create");
    setError("");
    try {
      const record = await api.createMemory(content, draftKind, sensitivity);
      setRecords((current) => [record, ...current]);
      setDraft("");
    } catch {
      setError("Klara could not save that memory. Nothing was added.");
    } finally {
      setBusy(null);
    }
  }

  async function update(record: MemoryRecord) {
    const content = editingText.trim();
    if (!content) return;
    setBusy(record.memory_id);
    try {
      const next = await api.updateMemory(record.memory_id, content);
      setRecords((current) => [next, ...current.filter((item) => item.memory_id !== record.memory_id)]);
      setEditing(null);
    } catch {
      setError("Update failed. The previous memory remains current.");
    } finally {
      setBusy(null);
    }
  }

  async function forget(record: MemoryRecord) {
    setBusy(record.memory_id);
    try {
      await api.forgetMemory(record.memory_id);
      setRecords((current) => current.filter((item) => item.memory_id !== record.memory_id));
    } catch {
      setError("Forget failed. The memory remains available.");
    } finally {
      setBusy(null);
    }
  }

  async function remove(record: MemoryRecord) {
    setBusy(record.memory_id);
    try {
      const receipt = await api.deleteMemory(record.memory_id);
      if (!receipt.deletion_verified) throw new Error("deletion_not_verified");
      setRecords((current) => current.filter((item) => item.memory_id !== record.memory_id));
    } catch {
      setError("Delete was not verified. The item stays visible for safety.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <main className="memory-page" aria-label="Memory manager">
      <header className="memory-header">
        <button className="memory-back" onClick={onBackToChat} aria-label="Back to chat"><ArrowLeft size={17} />Back to chat</button>
        <span className="memory-eyebrow"><Brain size={14} />Durable continuity</span>
        <h1>Memory</h1>
        <p>Klara saves only explicit or reviewed facts. Each item keeps its type, provenance, time, sensitivity, and deletion controls.</p>
      </header>

      <section className="memory-contract" aria-label="Memory guarantees">
        <span><ShieldCheck size={16} />Tenant isolated</span>
        <span><Clock3 size={16} />Temporal history</span>
        <span><Trash2 size={16} />Verified hard delete</span>
      </section>

      <form className="memory-create" onSubmit={remember}>
        <label htmlFor="memory-draft">Remember something</label>
        <textarea id="memory-draft" value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="For example: I prefer concise weekly updates." rows={3} />
        <div>
          <select aria-label="Memory type" value={draftKind} onChange={(event) => setDraftKind(event.target.value as MemoryKind)}>{MEMORY_KINDS.map((item) => <option value={item.value} key={item.value}>{item.label}</option>)}</select>
          <select aria-label="Sensitivity" value={sensitivity} onChange={(event) => setSensitivity(event.target.value as MemorySensitivity)}><option value="standard">Standard</option><option value="personal">Personal</option><option value="sensitive">Sensitive</option><option value="restricted">Restricted</option></select>
          <button type="submit" disabled={!draft.trim() || busy === "create"}><Plus size={16} />{busy === "create" ? "Saving…" : "Remember"}</button>
        </div>
      </form>

      <section className="memory-controls" aria-label="Memory filters">
        <label><Search size={16} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search content or provenance" /></label>
        <div role="group" aria-label="Filter by memory type">
          <button className={kind === "all" ? "active" : ""} onClick={() => setKind("all")}>All <small>{records.length}</small></button>
          {MEMORY_KINDS.map((item) => <button key={item.value} className={kind === item.value ? "active" : ""} onClick={() => setKind(item.value)}>{item.label}</button>)}
        </div>
      </section>

      {error ? <div className="memory-alert" role="alert">{error}</div> : null}
      {loading ? <div className="memory-empty" aria-live="polite">Loading memory…</div> : visible.length === 0 ? <div className="memory-empty">No matching memories. Klara will not infer or fabricate one.</div> : (
        <section className="memory-list" aria-label="Saved memories">
          {visible.map((record) => (
            <article className="memory-row" key={record.memory_id}>
              <div className="memory-row-meta"><span className={`memory-kind is-${record.kind}`}>{labelKind(record.kind)}</span><time dateTime={record.updated_at}>{new Date(record.updated_at).toLocaleString()}</time><span>{record.sensitivity}</span></div>
              {editing === record.memory_id ? <textarea aria-label="Edit memory" value={editingText} onChange={(event) => setEditingText(event.target.value)} rows={3} /> : <p>{record.content}</p>}
              <footer>
                <span>Source: {record.provenance.source_type} · confidence {Math.round(record.confidence * 100)}%</span>
                <div>
                  {editing === record.memory_id ? <><button aria-label="Save memory" disabled={busy === record.memory_id} onClick={() => void update(record)}><Check size={15} /></button><button aria-label="Cancel edit" onClick={() => setEditing(null)}><X size={15} /></button></> : <button aria-label="Edit memory" onClick={() => { setEditing(record.memory_id); setEditingText(record.content); }}><Pencil size={15} /></button>}
                  <button onClick={() => void forget(record)}>Forget</button>
                  <button className="danger" aria-label="Delete memory" onClick={() => void remove(record)} disabled={busy === record.memory_id}><Trash2 size={15} /></button>
                </div>
              </footer>
            </article>
          ))}
        </section>
      )}
    </main>
  );
}

function labelKind(kind: MemoryKind) {
  return MEMORY_KINDS.find((item) => item.value === kind)?.label ?? kind;
}
