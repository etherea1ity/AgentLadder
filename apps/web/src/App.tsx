import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, type RunEventSubscription } from "./api/client";
import { ChatWorkspace } from "./components/ChatWorkspace";
import { Sidebar } from "./components/Sidebar";
import type {
  Message,
  ModelOption,
  Run,
  RunEvent,
  Session,
} from "./types/domain";
import "./styles/app.css";
import "./styles/klara.css";

type Toast = { id: string; message: string };
type PersistedUi = {
  activeSessionId: string | null;
  sidebarCollapsed: boolean;
};

const UI_STORAGE_KEY = "klara_ui_state";
const MODEL_STORAGE_KEY = "klara_selected_model";
const THEME_STORAGE_KEY = "klara_theme";
const RUN_POLL_MS = 12_000;

export default function App() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [messages, setMessages] = useState<Record<string, Message>>({});
  const [runs, setRuns] = useState<Record<string, Run>>({});
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [input, setInput] = useState("");
  const [activeSseRunId, setActiveSseRunId] = useState<string | null>(null);
  const [isSubmittingRun, setIsSubmittingRun] = useState(false);
  const [cancellingRunId, setCancellingRunId] = useState<string | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [deletingSessionIds, setDeletingSessionIds] = useState<
    Record<string, boolean>
  >({});
  const [renamingSessionIds, setRenamingSessionIds] = useState<
    Record<string, boolean>
  >({});
  const [modelOptions, setModelOptions] = useState<ModelOption[]>([]);
  const [selectedModel, setSelectedModel] = useState("");
  const [theme, setTheme] = useState<"light" | "dark">(() => readTheme());
  const [handoffTriggerRunId, setHandoffTriggerRunId] = useState<string | null>(
    null,
  );

  const subscriptionsRef = useRef<Record<string, RunEventSubscription>>({});
  const pollTimersRef = useRef<Record<string, ReturnType<typeof setTimeout>>>(
    {},
  );
  const runsRef = useRef(runs);
  const messagesRef = useRef(messages);
  const processedEventsRef = useRef<Set<string>>(new Set());
  const cancelRequestedRunIdsRef = useRef<Set<string>>(new Set());
  const submitLockRef = useRef(false);

  useEffect(() => {
    runsRef.current = runs;
  }, [runs]);
  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const saved = readPersistedUi();
    setSidebarCollapsed(saved.sidebarCollapsed || isMobileViewport());
    void restoreInitialSession(saved, controller.signal, () => cancelled);
    const warmupRefreshes = [700, 1800].map((delayMs) =>
      window.setTimeout(() => {
        if (!cancelled)
          void refreshSessions({ signal: controller.signal, silent: true });
      }, delayMs),
    );
    api
      .listModels(controller.signal)
      .then((res) => {
        if (cancelled) return;
        setModelOptions(res.models);
        const savedModel = window.localStorage.getItem(MODEL_STORAGE_KEY);
        const usableSavedModel =
          savedModel && res.models.some((option) => option.model === savedModel)
            ? savedModel
            : null;
        setSelectedModel(
          usableSavedModel ?? res.default_model ?? res.models[0]?.model ?? "",
        );
      })
      .catch(() => {
        const fallback = "qwen/qwen-flash";
        setModelOptions([
          {
            id: fallback,
            model: fallback,
            label: "Qwen 3.7 Flash",
            use_when: "qwen provider",
          },
        ]);
        setSelectedModel(fallback);
      });
    return () => {
      cancelled = true;
      controller.abort();
      warmupRefreshes.forEach((timer) => window.clearTimeout(timer));
      closeAllRunSubscriptions();
    };
  }, []);

  useEffect(() => {
    const refreshVisibleSessions = () => {
      if (document.visibilityState === "hidden") return;
      void refreshSessions({ silent: true });
    };
    window.addEventListener("focus", refreshVisibleSessions);
    document.addEventListener("visibilitychange", refreshVisibleSessions);
    return () => {
      window.removeEventListener("focus", refreshVisibleSessions);
      document.removeEventListener("visibilitychange", refreshVisibleSessions);
    };
  }, []);

  useEffect(() => {
    persistUi({
      activeSessionId,
      sidebarCollapsed,
    });
  }, [activeSessionId, sidebarCollapsed]);

  useEffect(() => {
    if (selectedModel)
      window.localStorage.setItem(MODEL_STORAGE_KEY, selectedModel);
  }, [selectedModel]);

  useEffect(() => {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  }, [theme]);

  const activeMessages = useMemo(
    () =>
      Object.values(messages)
        .filter((message) => message.session_id === activeSessionId)
        .sort((a, b) => a.created_at.localeCompare(b.created_at)),
    [messages, activeSessionId],
  );
  const empty = !activeSessionId || activeMessages.length === 0;
  const activeSseRun = activeSseRunId ? runs[activeSseRunId] : null;
  const runningInActiveSession = Boolean(
    activeSseRun &&
    activeSessionId &&
    activeSseRun.session_id === activeSessionId &&
    !isTerminal(activeSseRun.status),
  );
  const running = runningInActiveSession;
  const busy = isSubmittingRun || running;

  useEffect(() => {
    const protectCenterRail = () => {
      const width = window.innerWidth;
      const shouldCollapseSidebar = empty ? width <= 1160 : width <= 1060;
      setSidebarCollapsed((current) =>
        current === shouldCollapseSidebar ? current : shouldCollapseSidebar,
      );
    };
    protectCenterRail();
    window.addEventListener("resize", protectCenterRail);
    return () => window.removeEventListener("resize", protectCenterRail);
  }, [empty]);

  async function loadSession(
    sessionId: string,
    options: { restoreRunId?: string | null } = {},
  ) {
    try {
      setHandoffTriggerRunId(null);
      const detail = await api.getSession(sessionId);
      setActiveSessionId(sessionId);
      setMessages((prev) => ({
        ...prev,
        ...Object.fromEntries(
          detail.messages.map((message) => [message.message_id, message]),
        ),
      }));
      setRuns((prev) => {
        const next = { ...prev };
        detail.runs.forEach((run) => {
          const merged = { ...run, events: prev[run.run_id]?.events ?? [] };
          next[run.run_id] = normalizeReconciledRun(run.run_id, merged);
        });
        return next;
      });
      const restoreRun = options.restoreRunId && detail.runs.some((run) => run.run_id === options.restoreRunId) ? options.restoreRunId : null;
      if (restoreRun) void reconcileRun(restoreRun, { subscribeIfActive: true });
      detail.runs
        .filter((run) => !isTerminal(run.status))
        .forEach((run) => {
          setActiveSseRunId(run.run_id);
          void reconcileRun(run.run_id, { subscribeIfActive: true });
        });
    } catch (error) {
      notify(`Could not open this conversation. ${friendlyError(error)}`);
    }
  }

  function newChat() {
    setHandoffTriggerRunId(null);
    setActiveSessionId(null);
    setInput("");
  }

  async function send() {
    const question = input.trim();
    if (!question || busy || submitLockRef.current) return;
    submitLockRef.current = true;

    const hadActiveSession = Boolean(activeSessionId);
    const draftSessionId = activeSessionId ?? createClientId("draft_sess");
    const draftUserId = createClientId("draft_user");
    const draftAssistantId = createClientId("draft_assistant");
    const draftRunId = createClientId("draft_run");
    const createdAt = new Date().toISOString();
    const draftUser: Message = {
      message_id: draftUserId,
      session_id: draftSessionId,
      role: "user",
      content: question,
      status: "completed",
      created_at: createdAt,
    };
    const draftAssistant: Message = {
      message_id: draftAssistantId,
      session_id: draftSessionId,
      role: "assistant",
      content: "",
      run_id: draftRunId,
      status: "running",
      created_at: createdAt,
    };
    const draftRun: Run = {
      run_id: draftRunId,
      session_id: draftSessionId,
      user_message_id: draftUserId,
      assistant_message_id: draftAssistantId,
      status: "queued",
      model: selectedModel || null,
      events: [],
      live: { streamed_chars: 0, current_label: "Preparing the run..." },
    };

    setInput("");
    setIsSubmittingRun(true);
    if (!activeSessionId) setActiveSessionId(draftSessionId);
    setMessages((prev) => ({
      ...prev,
      [draftUserId]: draftUser,
      [draftAssistantId]: draftAssistant,
    }));
    setRuns((prev) => ({ ...prev, [draftRunId]: draftRun }));
    setHandoffTriggerRunId(draftRunId);

    try {
      let sessionId = activeSessionId;
      if (!sessionId) {
        const session = await api.createSession();
        const createdSessionId = session.session_id;
        sessionId = createdSessionId;
        setActiveSessionId(createdSessionId);
        setSessions((prev) => sortSessions([session, ...prev]));
        setMessages((prev) =>
          remapDraftSession(prev, draftSessionId, createdSessionId),
        );
        setRuns((prev) => {
          const current = prev[draftRunId];
          if (!current) return prev;
          return {
            ...prev,
            [draftRunId]: { ...current, session_id: createdSessionId },
          };
        });
      }

      if (!sessionId) throw new Error("Session was not created.");
      const runSessionId = sessionId;
      const created = await api.createRun(
        runSessionId,
        question,
        selectedModel || undefined,
      );
      const realUser: Message = {
        message_id: created.user_message_id,
        session_id: runSessionId,
        role: "user",
        content: question,
        status: "completed",
        created_at: createdAt,
      };
      const realAssistant: Message = {
        message_id: created.assistant_message_id,
        session_id: runSessionId,
        role: "assistant",
        content: "",
        run_id: created.run_id,
        status: "running",
        created_at: createdAt,
      };
      const realRun: Run = {
        run_id: created.run_id,
        session_id: runSessionId,
        user_message_id: created.user_message_id,
        assistant_message_id: created.assistant_message_id,
        status: created.status,
        model: selectedModel || null,
        events: [],
        live: { streamed_chars: 0, current_label: "Preparing the run..." },
      };

      setMessages((prev) => {
        const next = { ...prev };
        delete next[draftUserId];
        delete next[draftAssistantId];
        next[realUser.message_id] = realUser;
        next[realAssistant.message_id] = realAssistant;
        return next;
      });
      setRuns((prev) => {
        const next = { ...prev };
        delete next[draftRunId];
        next[realRun.run_id] = realRun;
        return next;
      });
      setHandoffTriggerRunId(realRun.run_id);
      setActiveSseRunId(realRun.run_id);
      subscribeRun(realRun.run_id);
      void refreshSessions({ silent: true });
    } catch (error) {
      setInput(question);
      setMessages((prev) => {
        const next = { ...prev };
        delete next[draftUserId];
        delete next[draftAssistantId];
        return next;
      });
      setRuns((prev) => {
        const next = { ...prev };
        delete next[draftRunId];
        return next;
      });
      setHandoffTriggerRunId((current) =>
        current === draftRunId ? null : current,
      );
      if (!hadActiveSession) {
        setActiveSessionId(null);
      }
      notify(`Could not start the run. ${friendlyError(error)}`);
    } finally {
      setIsSubmittingRun(false);
      submitLockRef.current = false;
    }
  }

  function subscribeRun(runId: string) {
    if (subscriptionsRef.current[runId]) return subscriptionsRef.current[runId];
    const subscription = api.subscribeRunEvents(runId, applyRunEvent, () => {
      closeRunSubscription(runId, { keepPoll: true });
      void reconcileRun(runId, { subscribeIfActive: true });
    });
    subscriptionsRef.current[runId] = subscription;
    schedulePoll(runId);
    return subscription;
  }

  function closeRunSubscription(
    runId: string,
    options: { keepPoll?: boolean } = {},
  ) {
    subscriptionsRef.current[runId]?.close();
    delete subscriptionsRef.current[runId];
    if (!options.keepPoll) clearPoll(runId);
  }

  function closeAllRunSubscriptions() {
    Object.keys(subscriptionsRef.current).forEach((runId) =>
      closeRunSubscription(runId),
    );
    Object.keys(pollTimersRef.current).forEach((runId) => clearPoll(runId));
  }

  function schedulePoll(runId: string) {
    clearPoll(runId);
    pollTimersRef.current[runId] = setTimeout(() => {
      void reconcileRun(runId, { subscribeIfActive: true, silent: true });
    }, RUN_POLL_MS);
  }

  function clearPoll(runId: string) {
    if (pollTimersRef.current[runId])
      clearTimeout(pollTimersRef.current[runId]);
    delete pollTimersRef.current[runId];
  }

  async function reconcileRun(
    runId: string,
    options: { subscribeIfActive?: boolean; silent?: boolean } = {},
  ) {
    try {
      const detail = await api.getRun(runId);
      const nextRun = normalizeReconciledRun(runId, {
        ...detail.run,
        events: detail.events,
      });
      setRuns((prev) => ({ ...prev, [runId]: nextRun }));
      if (isTerminal(nextRun.status)) {
        closeRunSubscription(runId);
        setActiveSseRunId((current) => (current === runId ? null : current));
        if (cancelRequestedRunIdsRef.current.has(runId)) {
          setMessages((messagesPrev) =>
            markAssistant(
              messagesPrev,
              nextRun.assistant_message_id,
              "cancelled",
            ),
          );
          return nextRun;
        }
        await refreshSessionMessages(nextRun.session_id);
        return nextRun;
      }
      if (options.subscribeIfActive) {
        setActiveSseRunId(runId);
        subscribeRun(runId);
      } else {
        schedulePoll(runId);
      }
      return nextRun;
    } catch (error) {
      if (!options.silent)
        notify(`Could not refresh run status. ${friendlyError(error)}`);
      const current = runsRef.current[runId];
      if (current && !isTerminal(current.status)) schedulePoll(runId);
      return null;
    }
  }

  async function refreshSessionMessages(sessionId: string) {
    try {
      const detail = await api.getSession(sessionId);
      setSessions((prev) => sortSessions(upsertSession(prev, detail.session)));
      setMessages((prev) => ({
        ...prev,
        ...Object.fromEntries(
          detail.messages.map((message) => [message.message_id, message]),
        ),
      }));
      setRuns((prev) => {
        const next = { ...prev };
        detail.runs.forEach((run) => {
          const merged = { ...run, events: prev[run.run_id]?.events ?? [] };
          next[run.run_id] = normalizeReconciledRun(run.run_id, merged);
        });
        return next;
      });
    } catch {
      // A deleted session can no longer be refreshed; keep current UI stable.
    }
  }

  async function refreshSessions(
    options: { signal?: AbortSignal; silent?: boolean } = {},
  ) {
    try {
      const res = await api.listSessions(options.signal);
      setSessions(sortSessions(res.sessions));
      return res.sessions;
    } catch (error) {
      if (isAbortError(error)) return null;
      if (!options.silent)
        notify(`Could not load conversations. ${friendlyError(error)}`);
      return null;
    }
  }

  async function refreshSessionsWithRetry(
    signal: AbortSignal,
    isCancelled: () => boolean,
  ) {
    const attempts = [0, 350, 850, 1500];
    for (let index = 0; index < attempts.length; index += 1) {
      if (isCancelled() || signal.aborted) return;
      if (attempts[index] > 0) {
        await delay(attempts[index], signal);
        if (isCancelled() || signal.aborted) return;
      }
      const sessionsResult = await refreshSessions({
        signal,
        silent: index < attempts.length - 1,
      });
      if (sessionsResult) return sessionsResult;
    }
    return null;
  }

  async function restoreInitialSession(
    saved: PersistedUi,
    signal: AbortSignal,
    isCancelled: () => boolean,
  ) {
    const loadedSessions = await refreshSessionsWithRetry(signal, isCancelled);
    if (isCancelled() || signal.aborted || !loadedSessions?.length) return;

    const savedSession = saved.activeSessionId
      ? loadedSessions.find(
          (session) => session.session_id === saved.activeSessionId,
        )
      : null;
    const targetSessionId = savedSession?.session_id ?? loadedSessions[0].session_id;
    await loadSession(targetSessionId);
  }

  function applyRunEvent(event: RunEvent) {
    const currentSnapshot = runsRef.current[event.run_id];
    if (!currentSnapshot) return;
    if (
      currentSnapshot.events.some((item) => item.event_id === event.event_id) ||
      processedEventsRef.current.has(event.event_id)
    )
      return;
    processedEventsRef.current.add(event.event_id);

    const cancelRequested = cancelRequestedRunIdsRef.current.has(event.run_id);
    if (
      event.event_type === "answer_delta" &&
      (cancelRequested || isTerminal(currentSnapshot.status))
    )
      return;
    if (event.event_type === "run_completed" && cancelRequested) {
      closeRunSubscription(event.run_id);
      setActiveSseRunId((value) => (value === event.run_id ? null : value));
      return;
    }

    if (event.event_type === "answer_delta") {
      const delta = String(event.payload?.delta ?? "");
      setMessages((messagesPrev) => {
        const message = messagesPrev[currentSnapshot.assistant_message_id];
        if (!message) return messagesPrev;
        return {
          ...messagesPrev,
          [message.message_id]: {
            ...message,
            content: message.content + delta,
            status: "running",
          },
        };
      });
    }

    if (event.event_type === "run_completed") {
      closeRunSubscription(event.run_id);
      setActiveSseRunId((value) => (value === event.run_id ? null : value));
      setMessages((messagesPrev) =>
        markAssistant(
          messagesPrev,
          currentSnapshot.assistant_message_id,
          "completed",
        ),
      );
    }

    if (event.event_type === "run_failed") {
      closeRunSubscription(event.run_id);
      setActiveSseRunId((value) => (value === event.run_id ? null : value));
      setMessages((messagesPrev) =>
        markAssistant(
          messagesPrev,
          currentSnapshot.assistant_message_id,
          "failed",
        ),
      );
    }

    if (event.event_type === "run_cancelled") {
      cancelRequestedRunIdsRef.current.delete(event.run_id);
      closeRunSubscription(event.run_id);
      setActiveSseRunId((value) => (value === event.run_id ? null : value));
      setMessages((messagesPrev) =>
        markAssistant(
          messagesPrev,
          currentSnapshot.assistant_message_id,
          "cancelled",
        ),
      );
    }

    setRuns((prev) => {
      const current = prev[event.run_id];
      if (!current) return prev;
      if (current.events.some((item) => item.event_id === event.event_id))
        return prev;
      const events = [...current.events, event];
      const next: Run = { ...current, events };
      if (event.event_type === "thinking_started") next.status = "thinking";
      if (event.event_type === "answer_streaming_started")
        next.status = "streaming";
      if (
        event.event_type === "llm_call_started" &&
        typeof event.payload?.model === "string"
      )
        next.model = event.payload.model;
      if (event.event_type === "llm_call_started") {
        next.live = {
          streamed_chars: current.live?.streamed_chars ?? 0,
          current_label: "Calling model...",
        };
      }
      if (event.event_type === "tool_call_started") {
        const toolCall = event.payload?.tool_call as { name?: string } | undefined;
        next.live = {
          streamed_chars: current.live?.streamed_chars ?? 0,
          current_label: toolCall?.name ? `Using ${toolCall.name}...` : "Using tool...",
        };
      }
      if (event.event_type === "tool_call_completed") {
        const toolResult = event.payload?.tool_result as { name?: string } | undefined;
        next.live = {
          streamed_chars: current.live?.streamed_chars ?? 0,
          current_label: toolResult?.name ? `${toolResult.name} returned` : "Observation returned",
        };
      }
      if (event.event_type === "tool_call_failed") {
        const toolResult = event.payload?.tool_result as { name?: string } | undefined;
        next.live = {
          streamed_chars: current.live?.streamed_chars ?? 0,
          current_label: toolResult?.name ? `${toolResult.name} failed` : "Tool failed",
        };
      }
      if (event.event_type === "policy_stop") {
        next.live = {
          streamed_chars: current.live?.streamed_chars ?? 0,
          current_label: "Tool policy stopped",
        };
      }
      if (
        event.event_type === "hook_placement_started" ||
        event.event_type === "hook_placement_completed"
      ) {
        const placement = event.payload?.placement as string | undefined;
        next.live = {
          streamed_chars: current.live?.streamed_chars ?? 0,
          current_label: placement ? `${placement} hook` : "Runtime hook",
        };
      }
      if (event.event_type === "answer_delta") {
        if (cancelRequested || isTerminal(current.status)) return prev;
        next.status = "streaming";
        const delta = String(event.payload?.delta ?? "");
        next.live = {
          streamed_chars: Number(
            event.payload?.streamed_chars ??
              (current.live?.streamed_chars ?? 0) + delta.length,
          ),
          current_label: "Answer is streaming...",
        };
      }
      if (event.event_type === "module_started") {
        const moduleResult = event.payload?.module_result as { module_name?: string } | undefined;
        next.live = {
          streamed_chars: current.live?.streamed_chars ?? 0,
          current_label: moduleResult?.module_name ? `${moduleResult.module_name}...` : "Running module...",
        };
      }
      if (event.event_type === "trace_saved") next.trace_saved = true;
      if (event.event_type === "run_completed") {
        next.status = "completed";
        next.latency_ms = nullableNumber(event.payload?.latency_ms);
        next.prompt_tokens = nullableNumber(event.payload?.prompt_tokens);
        next.completion_tokens = nullableNumber(
          event.payload?.completion_tokens,
        );
        next.total_tokens = nullableNumber(event.payload?.total_tokens);
        next.token_source = parseTokenSource(event.payload?.token_source);
        next.trace_saved = Boolean(event.payload?.trace_saved);
        next.completed_at = event.created_at;
      }
      if (event.event_type === "run_failed") {
        next.status = "failed";
        next.error = event.payload?.error as Run["error"];
        next.completed_at = event.created_at;
      }
      if (event.event_type === "run_cancelled") {
        next.status = "cancelled";
        next.completed_at = event.created_at;
      }
      return { ...prev, [event.run_id]: next };
    });
  }

  function normalizeReconciledRun(runId: string, run: Run): Run {
    if (
      cancelRequestedRunIdsRef.current.has(runId) &&
      run.status === "completed"
    ) {
      const existing = runsRef.current[runId];
      return {
        ...run,
        status: "cancelled",
        completed_at: run.completed_at ?? new Date().toISOString(),
        events: [
          ...(run.events ?? []),
          {
            event_id: `${runId}_local_cancelled`,
            run_id: runId,
            event_type: "run_cancelled",
            message: "Run stopped locally; late completion ignored.",
            payload: {},
            created_at: new Date().toISOString(),
          },
        ],
        live: existing?.live ?? run.live,
      };
    }
    return run;
  }

  async function stop() {
    if (!activeSseRunId || cancellingRunId) return;
    const runId = activeSseRunId;
    cancelRequestedRunIdsRef.current.add(runId);
    setCancellingRunId(runId);
    try {
      await api.cancelRun(runId);
      setMessages((messagesPrev) => {
        const current = runsRef.current[runId];
        return current
          ? markAssistant(
              messagesPrev,
              current.assistant_message_id,
              "cancelled",
            )
          : messagesPrev;
      });
      setRuns((prev) => {
        const current = prev[runId];
        if (!current) return prev;
        return {
          ...prev,
          [runId]: {
            ...current,
            status: "cancelled",
            completed_at: new Date().toISOString(),
          },
        };
      });
      await reconcileRun(runId);
    } catch (error) {
      cancelRequestedRunIdsRef.current.delete(runId);
      notify(`Could not stop the run. ${friendlyError(error)}`);
    } finally {
      setCancellingRunId((value) => (value === runId ? null : value));
    }
  }

  async function renameSession(id: string, title: string) {
    setRenamingSessionIds((prev) => ({ ...prev, [id]: true }));
    try {
      const session = await api.renameSession(id, title);
      setSessions((prev) =>
        sortSessions(
          prev.map((item) => (item.session_id === id ? session : item)),
        ),
      );
    } catch (error) {
      notify(`Could not rename this conversation. ${friendlyError(error)}`);
    } finally {
      setRenamingSessionIds((prev) => ({ ...prev, [id]: false }));
    }
  }

  async function deleteSession(id: string) {
    setDeletingSessionIds((prev) => ({ ...prev, [id]: true }));
    try {
      const sessionRunIds = Object.values(runsRef.current)
        .filter((run) => run.session_id === id)
        .map((run) => run.run_id);
      const sessionMessageIds = Object.values(messagesRef.current)
        .filter((message) => message.session_id === id)
        .map((message) => message.message_id);
      sessionRunIds.forEach((runId) => closeRunSubscription(runId));
      await api.deleteSession(id);
      clearStoredFeedback(sessionMessageIds);
      setSessions((prev) => prev.filter((item) => item.session_id !== id));
      setMessages((prev) =>
        Object.fromEntries(
          Object.entries(prev).filter(
            ([, message]) => message.session_id !== id,
          ),
        ),
      );
      setRuns((prev) =>
        Object.fromEntries(
          Object.entries(prev).filter(([, run]) => run.session_id !== id),
        ),
      );
      if (activeSessionId === id) newChat();
    } catch (error) {
      notify(`Could not delete this conversation. ${friendlyError(error)}`);
    } finally {
      setDeletingSessionIds((prev) => ({ ...prev, [id]: false }));
    }
  }

  function notify(message: string) {
    const toast = {
      id: `toast_${Date.now()}_${Math.random().toString(36).slice(2)}`,
      message,
    };
    setToasts((prev) => [...prev, toast]);
    setTimeout(
      () => setToasts((prev) => prev.filter((item) => item.id !== toast.id)),
      4200,
    );
  }

  const shellClass = [
    "app-shell",
    empty ? "is-empty" : "has-chat",
    sidebarCollapsed ? "sidebar-collapsed" : "",
    theme === "dark" ? "theme-dark" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={shellClass}>
      <button
        className="mobile-sidebar-button"
        onClick={() => setSidebarCollapsed((value) => !value)}
        aria-label="Toggle mobile sidebar"
      >
        ☰
      </button>
      <Sidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        collapsed={sidebarCollapsed}
        deletingSessionIds={deletingSessionIds}
        renamingSessionIds={renamingSessionIds}
        onToggleCollapsed={() => setSidebarCollapsed((value) => !value)}
        onNewChat={newChat}
        onSelect={(id) => void loadSession(id)}
        onRename={renameSession}
        onDelete={deleteSession}
      />
      <ChatWorkspace
        activeSessionId={activeSessionId}
        messages={activeMessages}
        runs={runs}
        input={input}
        running={running}
        submitting={isSubmittingRun}
        cancelling={Boolean(cancellingRunId)}
        onInput={setInput}
        onSend={send}
        onStop={stop}
        modelOptions={modelOptions}
        selectedModel={selectedModel}
        onModelChange={setSelectedModel}
        theme={theme}
        onToggleTheme={() =>
          setTheme((value) => (value === "dark" ? "light" : "dark"))
        }
        handoffTriggerRunId={handoffTriggerRunId}
      />
      <ToastRegion toasts={toasts} />
    </div>
  );
}

function ToastRegion({ toasts }: { toasts: Toast[] }) {
  return (
    <div className="toast-region" aria-live="assertive">
      {toasts.map((toast) => (
        <div className="toast" key={toast.id}>
          {toast.message}
        </div>
      ))}
    </div>
  );
}


function parseTokenSource(value: unknown): Run["token_source"] {
  if (value === "reported" || value === "estimated" || value === "unknown") return value;
  return null;
}

function nullableNumber(value: unknown) {
  return typeof value === "number" ? value : null;
}
function delay(ms: number, signal?: AbortSignal) {
  return new Promise<void>((resolve) => {
    if (signal?.aborted) {
      resolve();
      return;
    }
    const timer = window.setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        window.clearTimeout(timer);
        resolve();
      },
      { once: true },
    );
  });
}
function isAbortError(error: unknown) {
  return error instanceof DOMException && error.name === "AbortError";
}
function isTerminal(status: Run["status"]) {
  return (
    status === "completed" || status === "failed" || status === "cancelled"
  );
}
function markAssistant(
  messages: Record<string, Message>,
  id: string,
  status: Message["status"],
) {
  const message = messages[id];
  if (!message) return messages;
  return { ...messages, [id]: { ...message, status } };
}
function sortSessions(items: Session[]) {
  return [...items].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
}
function clearStoredFeedback(messageIds: string[]) {
  try {
    messageIds.forEach((messageId) =>
      window.localStorage.removeItem(`klara_feedback_${messageId}`),
    );
  } catch {
    // Ignore storage cleanup failures; backend deletion is authoritative.
  }
}
function upsertSession(items: Session[], session: Session) {
  return items.some((item) => item.session_id === session.session_id)
    ? items.map((item) =>
        item.session_id === session.session_id ? session : item,
      )
    : [session, ...items];
}
function remapDraftSession(
  messages: Record<string, Message>,
  draftSessionId: string,
  sessionId: string,
) {
  return Object.fromEntries(
    Object.entries(messages).map(([id, message]) => [
      id,
      message.session_id === draftSessionId
        ? { ...message, session_id: sessionId }
        : message,
    ]),
  );
}
function createClientId(prefix: string) {
  const random =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now()}_${Math.random().toString(36).slice(2)}`;
  return `${prefix}_${String(random).replace(/[^a-zA-Z0-9_-]/g, "")}`;
}

function isMobileViewport() {
  try {
    return window.matchMedia("(max-width: 900px)").matches;
  } catch {
    return false;
  }
}

function readPersistedUi(): PersistedUi {
  try {
    const raw = window.localStorage.getItem(UI_STORAGE_KEY);
    if (!raw)
      return {
        activeSessionId: null,
        sidebarCollapsed: false,
      };
    const value = JSON.parse(raw) as Partial<PersistedUi>;
    return {
      activeSessionId: value.activeSessionId ?? null,
      sidebarCollapsed: Boolean(value.sidebarCollapsed),
    };
  } catch {
    return {
      activeSessionId: null,
      sidebarCollapsed: false,
    };
  }
}
function persistUi(value: PersistedUi) {
  try {
    window.localStorage.setItem(UI_STORAGE_KEY, JSON.stringify(value));
  } catch {
    /* ignore local storage failures */
  }
}
function readTheme(): "light" | "dark" {
  try {
    return window.localStorage.getItem(THEME_STORAGE_KEY) === "dark"
      ? "dark"
      : "light";
  } catch {
    return "light";
  }
}
function friendlyError(error: unknown) {
  if (error instanceof ApiError)
    return error.code ? `${error.code}` : `HTTP ${error.status}`;
  if (error instanceof Error) return error.message;
  return "Please try again.";
}
