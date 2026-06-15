from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
from uuid import uuid4

from klara.core.events import KlaraEvent
from klara.core.hooks import HookManager
from klara.core.messages import KlaraMessage, ModelResponse
from klara.core.policies import LoopPolicy, StopReason
from klara.core.tool_executor import ToolExecutor
from klara.core.tools import ToolSpec


class LlmClient(Protocol):
    def complete(
        self,
        *,
        system_prompt: str,
        messages: tuple[KlaraMessage, ...],
        tools: tuple[ToolSpec, ...],
        model: str,
    ) -> ModelResponse:
        ...


@dataclass(frozen=True)
class KlaraRunResult:
    run_id: str
    messages: tuple[KlaraMessage, ...]
    final_answer: str
    stop_reason: StopReason
    hook_failures: tuple[tuple[str, str], ...] = field(default_factory=tuple)


class KlaraLoop:
    def __init__(
        self,
        *,
        llm: LlmClient,
        tool_executor: ToolExecutor,
        hooks: HookManager | None = None,
        policy: LoopPolicy | None = None,
        model: str = "fake-model",
        system_prompt: str = "",
    ) -> None:
        self.llm = llm
        self.tool_executor = tool_executor
        self.hooks = hooks or HookManager()
        self.policy = policy or LoopPolicy()
        self.model = model
        self.system_prompt = system_prompt

    def run(self, user_input: str, *, run_id: str | None = None) -> KlaraRunResult:
        active_run_id = run_id or str(uuid4())
        messages: list[KlaraMessage] = [KlaraMessage(role="user", content=user_input)]
        self._emit(active_run_id, "run.started", {"model": self.model})

        try:
            for turn_index in range(1, self.policy.max_turns + 1):
                self._emit(active_run_id, "turn.started", {"turn_index": turn_index})
                self._emit(active_run_id, "llm.started", {"turn_index": turn_index})
                response = self.llm.complete(
                    system_prompt=self.system_prompt,
                    messages=tuple(messages),
                    tools=self.tool_executor.specs,
                    model=self.model,
                )
                self._emit(
                    active_run_id,
                    "llm.completed",
                    {
                        "turn_index": turn_index,
                        "tool_call_count": len(response.tool_calls),
                        "usage": response.usage or {},
                    },
                )
                assistant_message = KlaraMessage(
                    role="assistant",
                    content=response.content,
                    tool_calls=response.tool_calls,
                )
                messages.append(assistant_message)

                if not response.tool_calls:
                    self._emit(active_run_id, "turn.completed", {"turn_index": turn_index})
                    return self._complete(
                        active_run_id,
                        messages,
                        response.content,
                        StopReason.FINAL,
                    )

                for call in response.tool_calls:
                    self._emit(
                        active_run_id,
                        "tool.started",
                        {"turn_index": turn_index, "tool_call": call.to_public_dict()},
                    )
                    result = self.tool_executor.execute(call)
                    self._emit(
                        active_run_id,
                        "tool.completed",
                        {
                            "turn_index": turn_index,
                            "tool_result": result.to_public_dict(),
                        },
                    )
                    messages.append(
                        KlaraMessage(
                            role="tool",
                            name=result.name,
                            tool_call_id=result.tool_call_id,
                            content=result.content if result.ok else result.error or "",
                        )
                    )

                self._emit(
                    active_run_id,
                    "prepare_next_turn.started",
                    {"turn_index": turn_index},
                )
                messages = self.prepare_next_turn(messages)
                self._emit(
                    active_run_id,
                    "prepare_next_turn.completed",
                    {"turn_index": turn_index, "message_count": len(messages)},
                )
                self._emit(active_run_id, "turn.completed", {"turn_index": turn_index})

            final_answer = messages[-1].content if messages else ""
            return self._complete(
                active_run_id,
                messages,
                final_answer,
                StopReason.MAX_TURNS,
            )
        except Exception as exc:
            self._emit(
                active_run_id,
                "run.failed",
                {"error": f"{type(exc).__name__}: {exc}"},
            )
            raise

    def prepare_next_turn(self, messages: list[KlaraMessage]) -> list[KlaraMessage]:
        return messages

    def _complete(
        self,
        run_id: str,
        messages: list[KlaraMessage],
        final_answer: str,
        stop_reason: StopReason,
    ) -> KlaraRunResult:
        self._emit(run_id, "run.completed", {"stop_reason": stop_reason.value})
        return KlaraRunResult(
            run_id=run_id,
            messages=tuple(messages),
            final_answer=final_answer,
            stop_reason=stop_reason,
            hook_failures=tuple(self.hooks.failures),
        )

    def _emit(self, run_id: str, event_type: str, payload: dict[str, object]) -> None:
        self.hooks.emit(KlaraEvent(type=event_type, run_id=run_id, payload=payload))
