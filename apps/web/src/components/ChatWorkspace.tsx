import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import "katex/dist/katex.min.css";
import {
  Check,
  Copy,
  Moon,
  SlidersHorizontal,
  Sparkles,
  Sun,
  ThumbsDown,
  ThumbsUp,
} from "lucide-react";
import type {
  Message,
  ModelOption,
  Run,
} from "../types/domain";
import { KlaraHero } from "./klara/KlaraHero";
import { KlaraThinkingDrawer } from "./klara/KlaraThinkingDrawer";
import { KlaraPresence } from "./klara/KlaraPresence";
import { KlaraRunSurface } from "./klara/KlaraRunSurface";
import { KlaraRunStatus } from "./klara/KlaraRunStatus";
import { KlaraThinkingBlock } from "./klara/KlaraThinkingBlock";
import { KlaraHandoffOverlay, useKlaraHandoff } from "./klara/useKlaraHandoff";
import { isKlaraRunActive } from "./klara/useKlaraRunMotion";
import { normalizeMathMarkdown } from "../utils/markdown";
import { useDismissibleDetails } from "../hooks/useDismissibleDetails";

type Props = {
  activeSessionId: string | null;
  messages: Message[];
  runs: Record<string, Run>;
  input: string;
  running: boolean;
  submitting: boolean;
  cancelling: boolean;
  onInput: (value: string) => void;
  onSend: () => void;
  onStop: () => void;
  modelOptions: ModelOption[];
  selectedModel: string;
  thinkingEnabled: boolean;
  onModelChange: (model: string) => void;
  onThinkingChange: (enabled: boolean) => void;
  theme: "light" | "dark";
  onToggleTheme: () => void;
  handoffTriggerRunId?: string | null;
};

export function ChatWorkspace(props: Props) {
  const empty = !props.activeSessionId || props.messages.length === 0;
  const [composerFocused, setComposerFocused] = useState(false);
  const [typingPulse, setTypingPulse] = useState(0);
  const [activeThinkingRunId, setActiveThinkingRunId] = useState<string | null>(
    null,
  );
  const lastTypingPulseRef = useRef(0);
  const thinkingTriggerRef = useRef<HTMLButtonElement | null>(null);
  const activeRun = [...props.messages]
    .reverse()
    .map((message) => (message.run_id ? props.runs[message.run_id] : undefined))
    .find((run): run is Run => isKlaraRunActive(run));
  const activeThinkingRun = activeThinkingRunId
    ? props.runs[activeThinkingRunId]
    : null;
  const toggleThinking = useCallback(
    (runId: string, trigger: HTMLButtonElement) => {
      thinkingTriggerRef.current = trigger;
      setActiveThinkingRunId((current) => (current === runId ? null : runId));
    },
    [],
  );
  const closeThinking = useCallback(() => {
    setActiveThinkingRunId(null);
    window.setTimeout(() => thinkingTriggerRef.current?.focus(), 0);
  }, []);
  const pulseTyping = () => {
    const now = Date.now();
    if (now - lastTypingPulseRef.current < 700) return;
    lastTypingPulseRef.current = now;
    setTypingPulse((value) => value + 1);
  };
  const { handoff, handoffRunId, arrivalRunId } = useKlaraHandoff(
    activeRun,
    props.handoffTriggerRunId,
  );

  useEffect(() => {
    if (activeThinkingRunId && !props.runs[activeThinkingRunId]) {
      setActiveThinkingRunId(null);
    }
  }, [activeThinkingRunId, props.runs]);

  const workspaceClass = [
    "chat-workspace",
    empty ? "is-empty" : "has-messages",
    activeThinkingRun ? "is-thinking-open" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <main className={workspaceClass}>
      <TopPath
        compact={!empty}
        theme={props.theme}
        onToggleTheme={props.onToggleTheme}
      />
      {empty ? (
        <section className="home-stack">
          <EmptyHome
            inputActive={composerFocused || Boolean(props.input)}
            pulseKey={typingPulse}
          />
          <ChatInput
            input={props.input}
            running={props.running}
            submitting={props.submitting}
            cancelling={props.cancelling}
            onInput={props.onInput}
            onSend={props.onSend}
            onStop={props.onStop}
            placeholder="Ask your first question..."
            home
            modelOptions={props.modelOptions}
            selectedModel={props.selectedModel}
            thinkingEnabled={props.thinkingEnabled}
            onModelChange={props.onModelChange}
            onThinkingChange={props.onThinkingChange}
            onFocusChange={setComposerFocused}
            onTypingPulse={pulseTyping}
          />
        </section>
      ) : (
        <>
          <MessageList
            messages={props.messages}
            runs={props.runs}
            activeRunId={activeRun?.run_id ?? null}
            handoffRunId={handoffRunId}
            arrivalRunId={arrivalRunId}
            activeThinkingRunId={activeThinkingRunId}
            onToggleThinking={toggleThinking}
          />
          <div className="composer-footer">
            <ChatInput
              input={props.input}
              running={props.running}
              submitting={props.submitting}
              cancelling={props.cancelling}
              onInput={props.onInput}
              onSend={props.onSend}
              onStop={props.onStop}
              placeholder="Ask anything..."
              modelOptions={props.modelOptions}
              selectedModel={props.selectedModel}
              thinkingEnabled={props.thinkingEnabled}
              onModelChange={props.onModelChange}
              onThinkingChange={props.onThinkingChange}
              onFocusChange={setComposerFocused}
              onTypingPulse={pulseTyping}
            />
          </div>
          {handoff ? <KlaraHandoffOverlay handoff={handoff} /> : null}
        </>
      )}
      <KlaraThinkingDrawer
        run={activeThinkingRun}
        open={Boolean(activeThinkingRun)}
        onClose={closeThinking}
      />
    </main>
  );
}

function TopPath({
  compact,
  theme,
  onToggleTheme,
}: {
  compact: boolean;
  theme: "light" | "dark";
  onToggleTheme: () => void;
}) {
  return (
    <div className={`top-path ${compact ? "is-compact" : ""}`}>
      <span>Klara</span>
      {compact ? (
        <div className="top-actions">
          <button
            onClick={onToggleTheme}
            aria-label={
              theme === "dark"
                ? "Switch to light theme"
                : "Switch to dark theme"
            }
            title={theme === "dark" ? "Light theme" : "Dark theme"}
          >
            {theme === "dark" ? <Sun size={20} /> : <Moon size={20} />}
          </button>
          <a
            href="https://github.com/etherea1ity/AgentLadder"
            target="_blank"
            rel="noreferrer"
            aria-label="Open GitHub project"
            title="Open GitHub project"
          >
            <GitHubMark />
          </a>
        </div>
      ) : null}
    </div>
  );
}

function GitHubMark() {
  return (
    <svg
      aria-hidden="true"
      width="21"
      height="21"
      viewBox="0 0 24 24"
      fill="currentColor"
    >
      <path d="M12 .5C5.65.5.5 5.65.5 12c0 5.08 3.29 9.39 7.86 10.91.58.11.79-.25.79-.56v-2.14c-3.2.7-3.87-1.36-3.87-1.36-.52-1.33-1.28-1.69-1.28-1.69-1.05-.72.08-.7.08-.7 1.16.08 1.77 1.19 1.77 1.19 1.03 1.76 2.7 1.25 3.36.96.1-.75.4-1.25.73-1.54-2.56-.29-5.25-1.28-5.25-5.7 0-1.26.45-2.29 1.19-3.1-.12-.29-.52-1.47.11-3.05 0 0 .97-.31 3.18 1.18A11.1 11.1 0 0 1 12 6.01c.98 0 1.96.13 2.88.39 2.2-1.49 3.17-1.18 3.17-1.18.63 1.58.23 2.76.11 3.05.74.81 1.19 1.84 1.19 3.1 0 4.43-2.7 5.4-5.27 5.69.41.36.78 1.06.78 2.14v3.15c0 .31.21.68.8.56A11.51 11.51 0 0 0 23.5 12C23.5 5.65 18.35.5 12 .5Z" />
    </svg>
  );
}

function EmptyHome({
  inputActive,
  pulseKey,
}: {
  inputActive: boolean;
  pulseKey: number;
}) {
  return <KlaraHero inputActive={inputActive} pulseKey={pulseKey} />;
}

type ConversationTurn = {
  key: string;
  user?: Message;
  assistant?: Message;
  run?: Run;
};

function MessageList({
  messages,
  runs,
  activeRunId,
  handoffRunId,
  arrivalRunId,
  activeThinkingRunId,
  onToggleThinking,
}: {
  messages: Message[];
  runs: Record<string, Run>;
  activeRunId: string | null;
  handoffRunId: string | null;
  arrivalRunId: string | null;
  activeThinkingRunId: string | null;
  onToggleThinking: (runId: string, trigger: HTMLButtonElement) => void;
}) {
  const scrollerRef = useRef<HTMLElement | null>(null);
  const shouldFollowRef = useRef(true);
  const previousCountRef = useRef(0);
  const turns = buildConversationTurns(messages, runs);
  const streamSignature =
    messages
      .map(
        (message) =>
          `${message.message_id}:${message.content.length}:${message.status ?? ""}`,
      )
      .join("|") +
    Object.values(runs)
      .map(
        (run) => `${run.run_id}:${run.status}:${run.live?.streamed_chars ?? 0}`,
      )
      .join("|");

  useEffect(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    const countChanged = previousCountRef.current !== messages.length;
    previousCountRef.current = messages.length;
    if (!countChanged && !shouldFollowRef.current) return;
    const scrollToBottom = () => {
      scroller.scrollTop = scroller.scrollHeight;
    };
    scrollToBottom();
    requestAnimationFrame(scrollToBottom);
  }, [messages.length, streamSignature]);

  const rememberScrollIntent = () => {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    shouldFollowRef.current =
      scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 96;
  };

  return (
    <section
      ref={scrollerRef}
      className="message-list"
      aria-label="Messages"
      onScroll={rememberScrollIntent}
    >
      {turns.map((turn) => (
        <article className="conversation-turn" key={turn.key}>
          {turn.user ? <UserMessage message={turn.user} /> : null}
          {turn.assistant ? (
            <AssistantMessage
              message={turn.assistant}
              run={turn.run}
              visuallyActive={Boolean(
                turn.run && activeRunId === turn.run.run_id,
              )}
              handoffActive={Boolean(
                turn.run && handoffRunId === turn.run.run_id,
              )}
              arrivalActive={Boolean(
                turn.run && arrivalRunId === turn.run.run_id,
              )}
              thinkingOpen={Boolean(
                turn.run && activeThinkingRunId === turn.run.run_id,
              )}
              onToggleThinking={onToggleThinking}
            />
          ) : null}
        </article>
      ))}
    </section>
  );
}

function buildConversationTurns(
  messages: Message[],
  runs: Record<string, Run>,
): ConversationTurn[] {
  const byId = new Map(
    messages.map((message) => [message.message_id, message]),
  );
  const runByUser = new Map<string, Run>();
  const runByAssistant = new Map<string, Run>();
  Object.values(runs).forEach((run) => {
    runByUser.set(run.user_message_id, run);
    runByAssistant.set(run.assistant_message_id, run);
  });

  const used = new Set<string>();
  const turns: ConversationTurn[] = [];
  messages.forEach((message, index) => {
    if (used.has(message.message_id)) return;
    if (message.role === "user") {
      const run = runByUser.get(message.message_id);
      let assistant = run ? byId.get(run.assistant_message_id) : undefined;
      if (!assistant) {
        assistant = messages
          .slice(index + 1)
          .find(
            (candidate) =>
              candidate.role === "assistant" && !used.has(candidate.message_id),
          );
      }
      used.add(message.message_id);
      if (assistant) used.add(assistant.message_id);
      turns.push({
        key:
          run?.run_id ??
          `${message.message_id}:${assistant?.message_id ?? "pending"}`,
        user: message,
        assistant,
        run:
          run ??
          (assistant?.run_id
            ? runByAssistant.get(assistant.run_id)
            : undefined),
      });
      return;
    }

    const run = message.run_id
      ? runs[message.run_id]
      : runByAssistant.get(message.message_id);
    used.add(message.message_id);
    turns.push({
      key: run?.run_id ?? message.message_id,
      assistant: message,
      run,
    });
  });
  return turns;
}

function UserMessage({ message }: { message: Message }) {
  return (
    <article className="message user-message">
      <div className="message-label user-label">
        <span className="user-identity">
          <span className="user-avatar" aria-hidden="true">
            Y
          </span>
          <span>You</span>
        </span>
        <time>{formatClock(message.created_at)}</time>
      </div>
      <p>{message.content}</p>
    </article>
  );
}

function AssistantMessage({
  message,
  run,
  handoffActive,
  visuallyActive,
  arrivalActive,
  thinkingOpen,
  onToggleThinking,
}: {
  message: Message;
  run?: Run;
  handoffActive: boolean;
  visuallyActive: boolean;
  arrivalActive: boolean;
  thinkingOpen: boolean;
  onToggleThinking: (runId: string, trigger: HTMLButtonElement) => void;
}) {
  const [feedback, setFeedback] = useState<"up" | "down" | null>(() =>
    readFeedback(message.message_id),
  );
  const [copied, setCopied] = useState(false);
  const setExclusiveFeedback = (value: "up" | "down") =>
    setFeedback((current) => {
      const next = current === value ? null : value;
      writeFeedback(message.message_id, next);
      return next;
    });
  const copyAnswer = async () => {
    await copyText(message.content);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  };
  return (
    <article className="message assistant-message">
      <div className="message-label assistant-label">
        <KlaraRunStatus
          run={run}
          handoffActive={handoffActive}
          visuallyActive={visuallyActive}
          arrivalActive={arrivalActive}
          hideActivePhaseCopy
        />
        <KlaraThinkingBlock
          run={run}
          isThinkingOpen={thinkingOpen}
          onToggleThinking={onToggleThinking}
        />
      </div>
      <AssistantContent
        content={message.content}
        running={message.status === "running"}
      />
      <KlaraRunSurface run={run} developerCollapsed />
      {message.status !== "running" && message.content ? (
        <div className="message-actions">
          <button
            aria-label="Copy answer"
            className={copied ? "is-copied" : ""}
            onClick={copyAnswer}
          >
            {copied ? <Check size={16} /> : <Copy size={16} />}
            <span>{copied ? "Copied" : "Copy"}</span>
          </button>
          <button
            aria-label="Like answer"
            className={feedback === "up" ? "is-active" : ""}
            aria-pressed={feedback === "up"}
            onClick={() => setExclusiveFeedback("up")}
          >
            <ThumbsUp size={16} />
            <span>Good</span>
          </button>
          <button
            aria-label="Dislike answer"
            className={feedback === "down" ? "is-active" : ""}
            aria-pressed={feedback === "down"}
            onClick={() => setExclusiveFeedback("down")}
          >
            <ThumbsDown size={16} />
            <span>Bad</span>
          </button>
        </div>
      ) : null}
    </article>
  );
}

function AssistantContent({
  content,
  running,
}: {
  content: string;
  running: boolean;
}) {
  return (
    <div
      className={`assistant-content rich-answer ${running ? "is-running" : ""}`}
    >
      {content ? (
        <ReactMarkdown
          remarkPlugins={[remarkGfm, remarkMath]}
          rehypePlugins={[rehypeKatex]}
          components={{
            img: ({ src, alt }) => (
              <GeneratedImage src={String(src ?? "")} alt={alt ?? ""} />
            ),
          }}
        >
          {normalizeMathMarkdown(content)}
        </ReactMarkdown>
      ) : null}
    </div>
  );
}

function GeneratedImage({ src, alt }: { src: string; alt: string }) {
  const [failed, setFailed] = useState(false);
  const resolvedSrc = resolveAssetSrc(src);
  const label = alt || "Generated image";

  if (!resolvedSrc) return null;
  if (failed) {
    return (
      <span className="generated-image-fallback" title={resolvedSrc}>
        Generated image unavailable
      </span>
    );
  }

  return (
    <a className="generated-image-link" href={resolvedSrc} target="_blank" rel="noreferrer">
      <img
        className="generated-image"
        src={resolvedSrc}
        alt={label}
        loading="lazy"
        decoding="async"
        onError={() => setFailed(true)}
      />
    </a>
  );
}

function resolveAssetSrc(src: string) {
  if (!src) return "";
  if (!src.startsWith("/api/assets/local")) return src;
  const apiBase = import.meta.env.VITE_API_BASE_URL ?? "";
  return `${apiBase}${src}`;
}

function ChatInput({
  input,
  running,
  submitting,
  cancelling,
  placeholder,
  home = false,
  onInput,
  onSend,
  onStop,
  modelOptions,
  selectedModel,
  thinkingEnabled,
  onModelChange,
  onThinkingChange,
  onFocusChange,
  onTypingPulse,
}: {
  input: string;
  running: boolean;
  submitting: boolean;
  cancelling: boolean;
  placeholder: string;
  home?: boolean;
  onInput: (value: string) => void;
  onSend: () => void;
  onStop: () => void;
  modelOptions: ModelOption[];
  selectedModel: string;
  thinkingEnabled: boolean;
  onModelChange: (model: string) => void;
  onThinkingChange: (enabled: boolean) => void;
  onFocusChange?: (focused: boolean) => void;
  onTypingPulse?: () => void;
}) {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const [focused, setFocused] = useState(false);
  const selectedOption = modelOptions.find(
    (option) => option.model === selectedModel,
  );
  const supportsThinking = Boolean(selectedOption?.supports_thinking);
  const busy = running || submitting || cancelling;
  const canSend = Boolean(input.trim()) && !submitting && !cancelling;
  const klaraEngaged = running || submitting || canSend || focused;
  const buttonLabel = running
    ? cancelling
      ? "Stopping run"
      : "Stop run"
    : submitting
      ? "Starting run"
      : "Send";
  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, home ? 210 : 180)}px`;
  }, [input, home]);

  return (
    <div
      className={`input-wrap ${home ? "home-input" : ""} ${focused ? "is-focused" : ""} ${running || submitting ? "is-running" : ""}`}
      data-klara-input-anchor
    >
      <textarea
        ref={textareaRef}
        value={input}
        placeholder={placeholder}
        rows={home ? 3 : 1}
        onFocus={() => {
          setFocused(true);
          onFocusChange?.(true);
        }}
        onBlur={() => {
          setFocused(false);
          onFocusChange?.(false);
        }}
        onChange={(event) => {
          onInput(event.target.value);
          onTypingPulse?.();
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            if (!busy) onSend();
          }
        }}
        readOnly={busy}
        aria-disabled={busy}
      />
      <div className="input-footer">
        <span className="input-tools">
          <ModelPicker
            options={modelOptions}
            selectedModel={selectedModel}
            selectedLabel={selectedOption?.label ?? selectedModel}
            onChange={onModelChange}
            disabled={busy}
          />
          <ThinkingToggle
            enabled={thinkingEnabled && supportsThinking}
            supported={supportsThinking}
            disabled={busy}
            onChange={onThinkingChange}
          />
          <span>Enter to send, Shift + Enter for new line</span>
        </span>
        {running ? (
          <span className="run-state-hint">
            {cancelling ? "Stopping..." : "Klara is running"}
          </span>
        ) : null}
        <button
          className={`${running ? "stop-button" : "send-button"} ${klaraEngaged ? "is-klara-awake" : ""}`}
          data-klara-composer-anchor
          onClick={running ? onStop : onSend}
          disabled={running ? cancelling : !canSend}
          aria-label={buttonLabel}
          title={buttonLabel}
        >
          <span className="send-klara-mark" aria-hidden="true">
            <KlaraPresence
              active={klaraEngaged}
              phase={running || submitting ? "writing" : klaraEngaged ? "listening" : "idle"}
              size="status"
              elevated={running || submitting || focused || canSend}
              pulseKey={running || submitting ? 1 : focused ? 1 : input.length}
            />
          </span>
        </button>
      </div>
    </div>
  );
}

function ThinkingToggle({
  enabled,
  supported,
  disabled,
  onChange,
}: {
  enabled: boolean;
  supported: boolean;
  disabled: boolean;
  onChange: (enabled: boolean) => void;
}) {
  const locked = disabled || !supported;
  const label = !supported
    ? "Thinking unavailable for this model"
    : enabled
      ? "Turn thinking off"
      : "Turn thinking on";
  return (
    <button
      type="button"
      className={`thinking-toggle ${enabled ? "is-enabled" : ""}`}
      aria-label={label}
      aria-pressed={supported ? enabled : false}
      aria-disabled={locked}
      title={label}
      onClick={() => {
        if (!locked) onChange(!enabled);
      }}
    >
      <Sparkles size={15} />
      <span>{enabled ? "Thinking On" : "Thinking Off"}</span>
    </button>
  );
}

function ModelPicker({
  options,
  selectedModel,
  selectedLabel,
  onChange,
  disabled = false,
}: {
  options: ModelOption[];
  selectedModel: string;
  selectedLabel: string;
  onChange: (model: string) => void;
  disabled?: boolean;
}) {
  const pickerRef = useRef<HTMLDetailsElement | null>(null);
  const closePicker = useCallback(() => {
    const picker = pickerRef.current;
    if (!picker?.open) return;
    picker.open = false;
  }, []);

  useDismissibleDetails(pickerRef);

  return (
    <details
      ref={pickerRef}
      className="model-picker"
      onToggle={(event) => {
        if (disabled && event.currentTarget.open)
          event.currentTarget.open = false;
      }}
    >
      <summary
        aria-label="Choose model"
        aria-disabled={disabled}
        title={
          disabled
            ? "Model changes apply after the current run finishes"
            : "Choose model"
        }
        onClick={(event) => {
          if (disabled) event.preventDefault();
        }}
      >
        <SlidersHorizontal size={17} />
        <span>{selectedLabel || "Model"}</span>
      </summary>
      <div className="model-menu">
        {options.map((option) => (
          <button
            key={option.model}
            className={option.model === selectedModel ? "is-selected" : ""}
            onClick={() => {
              onChange(option.model);
              closePicker();
            }}
          >
            <span>{option.label}</span>
            <small>
              {option.use_when ?? option.model}
              {option.supports_thinking ? (
                <span className="model-capability">Thinking</span>
              ) : null}
            </small>
            {option.model === selectedModel ? <Check size={15} /> : null}
          </button>
        ))}
      </div>
    </details>
  );
}

function formatClock(value: string) {
  return new Date(value).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

async function copyText(value: string) {
  await navigator.clipboard?.writeText(value);
}

const FEEDBACK_STORAGE_PREFIX = "klara_feedback_";
function readFeedback(messageId: string): "up" | "down" | null {
  try {
    const value = window.localStorage.getItem(
      `${FEEDBACK_STORAGE_PREFIX}${messageId}`,
    );
    return value === "up" || value === "down" ? value : null;
  } catch {
    return null;
  }
}
function writeFeedback(messageId: string, value: "up" | "down" | null) {
  try {
    const key = `${FEEDBACK_STORAGE_PREFIX}${messageId}`;
    if (value) window.localStorage.setItem(key, value);
    else window.localStorage.removeItem(key);
  } catch {
    // localStorage can be unavailable in restricted browsers; feedback remains session-local.
  }
}
