from __future__ import annotations

from klara.core.events import KlaraEvent
from klara.core.hooks import HookManager
from klara.core.loop import FinalAnswerDecision, KlaraLoop, KlaraRunCheckpoint
from klara.core.messages import KlaraMessage, ModelCallError, ModelResponse
from klara.core.tools import ToolCall
from klara.tools.base import BaseTool
from klara.tools.executor import ToolExecutor
from klara.core.tools import ToolMetadata, ToolResult, ToolSpec


class EchoTool(BaseTool):
    spec = ToolSpec(
        name="echo",
        description="Echo text.",
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    )
    metadata = ToolMetadata(label="Echo", category="test")

    def __init__(self) -> None:
        self.calls = 0

    def run(self, arguments):
        self.calls += 1
        return ToolResult(
            tool_call_id=self.call_id(arguments),
            name="echo",
            content=str(arguments["text"]),
        )


class CrashAfterToolLlm:
    def complete(self, *, messages: tuple[KlaraMessage, ...], **_):
        if any(message.role == "tool" for message in messages):
            raise ModelCallError("simulated worker death", code="worker_lost")
        return ModelResponse(
            content="",
            tool_calls=(
                ToolCall(id="echo-1", name="echo", arguments={"text": "durable"}),
            ),
            usage={"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        )


class FinishFromCheckpointLlm:
    def complete(self, *, messages: tuple[KlaraMessage, ...], **_):
        assert sum(message.role == "tool" for message in messages) == 1
        return ModelResponse(
            content="durable",
            usage={"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5},
        )


class Capture:
    def __init__(self) -> None:
        self.events: list[KlaraEvent] = []

    def on_event(self, event: KlaraEvent) -> None:
        self.events.append(event)


class ReplayAwareController:
    def __init__(self) -> None:
        self.results: list[str] = []

    def on_run_start(self, *, user_input: str, run_id: str) -> None:
        self.results.clear()

    def system_prompt_suffix(self) -> str:
        return f"replayed={','.join(self.results)}"

    def on_tool_results(self, *, results: tuple[ToolResult, ...]) -> None:
        self.results.extend(result.content for result in results)

    def before_final_answer(self, *, content: str) -> FinalAnswerDecision:
        return FinalAnswerDecision()

    def prepare_next_turn(self, messages: list[KlaraMessage]) -> list[KlaraMessage]:
        return messages

    def drain_events(self):
        return ()


class FinishAfterControllerReplayLlm:
    def complete(self, *, system_prompt: str, **_):
        assert "replayed=durable" in system_prompt
        return ModelResponse(content="controller restored")


def test_loop_checkpoint_resumes_after_tool_without_repeating_effect() -> None:
    tool = EchoTool()
    checkpoints: list[KlaraRunCheckpoint] = []
    first = KlaraLoop(
        llm=CrashAfterToolLlm(),
        tool_executor=ToolExecutor([tool]),
        model="test-model",
        system_prompt="stable",
    )

    try:
        first.run(
            "echo durably",
            run_id="run-durable",
            checkpoint_sink=checkpoints.append,
        )
    except ModelCallError as exc:
        assert exc.code == "worker_lost"
    else:  # pragma: no cover - assertion guard
        raise AssertionError("simulated crash did not occur")

    checkpoint = KlaraRunCheckpoint.from_private_dict(
        checkpoints[-1].to_private_dict()
    )
    capture = Capture()
    resumed = KlaraLoop(
        llm=FinishFromCheckpointLlm(),
        tool_executor=ToolExecutor([tool]),
        hooks=HookManager([capture]),
        model="test-model",
        system_prompt="stable",
    ).run(
        "echo durably",
        run_id="run-durable",
        checkpoint=checkpoint,
    )

    assert resumed.final_answer == "durable"
    assert tool.calls == 1
    resumed_event = next(event for event in capture.events if event.type == "run.resumed")
    assert resumed_event.seq == checkpoint.next_event_sequence


def test_resume_replays_observations_into_fresh_controller_state() -> None:
    tool = EchoTool()
    checkpoints: list[KlaraRunCheckpoint] = []
    first = KlaraLoop(
        llm=CrashAfterToolLlm(),
        tool_executor=ToolExecutor([tool]),
        controllers=(ReplayAwareController(),),
        model="test-model",
        system_prompt="stable",
    )
    try:
        first.run("echo durably", run_id="run-controller", checkpoint_sink=checkpoints.append)
    except ModelCallError:
        pass

    controller = ReplayAwareController()
    result = KlaraLoop(
        llm=FinishAfterControllerReplayLlm(),
        tool_executor=ToolExecutor([tool]),
        controllers=(controller,),
        model="test-model",
        system_prompt="stable",
    ).run(
        "echo durably",
        run_id="run-controller",
        checkpoint=KlaraRunCheckpoint.from_private_dict(
            checkpoints[-1].to_private_dict()
        ),
    )

    assert result.final_answer == "controller restored"
    assert controller.results == ["durable"]
    assert tool.calls == 1
