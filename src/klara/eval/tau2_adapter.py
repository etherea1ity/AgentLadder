"""Official tau2-bench adapter for the frozen Klara model boundary.

The benchmark owns tool execution, user simulation, and reward calculation.
Klara owns the candidate-side persona, provider adapter, tool schema conversion,
provider response normalization, and protocol-leak guard.  Keeping this seam
explicit prevents an official tau2 score from being mislabeled as a full
AgentLadder product-runtime score.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable

from klara.app.output_contract import OutputContractLlmClient
from klara.core.messages import KlaraMessage, ModelResponse
from klara.core.tools import ToolCall, ToolSpec
from klara.infra.config.loader import load_models_config
from klara.infra.llm.openai_compatible import (
    OpenAICompatibleLlmClient,
    OpenAICompatibleSettings,
)


TAU2_AGENT_NAME = "klara_agentladder"
TAU2_MODEL = "deepseek/deepseek-v4-flash"
TAU2_AGENT_INSTRUCTION = """
You are the customer-service agent in an official tau2-bench evaluation.
Follow the domain policy exactly. In each turn, either send one message to the
user or make tool calls; never do both. Use only the tools exposed by the tau2
environment. Do not reveal hidden reasoning or internal provider protocols.
""".strip()


@dataclass(frozen=True)
class Tau2AdapterMetadata:
    """Public, reproducible identity for one registered adapter."""

    agent_name: str
    model: str
    persona_sha256: str
    prompt_sha256: str


def tau2_tools_to_klara(tools: Iterable[Any]) -> tuple[ToolSpec, ...]:
    """Convert official tau2 tool schemas without changing their semantics."""

    converted: list[ToolSpec] = []
    for tool in tools:
        schema = tool.openai_schema
        function = schema.get("function", {})
        converted.append(
            ToolSpec(
                name=str(function.get("name") or tool.name),
                description=str(function.get("description") or tool.name),
                input_schema=dict(function.get("parameters") or {"type": "object"}),
            )
        )
    return tuple(converted)


def tau2_messages_to_klara(messages: Iterable[Any]) -> tuple[KlaraMessage, ...]:
    """Convert a tau2 transcript while preserving tool-call/result joins."""

    converted: list[KlaraMessage] = []
    tool_names: dict[str, str] = {}
    for message in messages:
        role = str(message.role)
        raw_calls = getattr(message, "tool_calls", None) or []
        calls = tuple(
            ToolCall(
                id=str(call.id),
                name=str(call.name),
                arguments=dict(call.arguments),
            )
            for call in raw_calls
        )
        for call in calls:
            tool_names[call.id] = call.name
        content = str(getattr(message, "content", None) or "")
        if role == "tool":
            tool_call_id = str(message.id)
            converted.append(
                KlaraMessage(
                    role="tool",
                    content=content,
                    name=tool_names.get(tool_call_id, "tau2_tool"),
                    tool_call_id=tool_call_id,
                )
            )
        elif role in {"user", "assistant"}:
            converted.append(
                KlaraMessage(
                    role=role,
                    content=content,
                    tool_calls=calls,
                )
            )
    return tuple(converted)


def build_tau2_system_prompt(*, persona: str, domain_policy: str) -> str:
    """Build the candidate prompt without importing product-only tool advice."""

    return "\n\n".join(
        [
            persona.strip(),
            "<tau2_benchmark_contract>\n"
            f"{TAU2_AGENT_INSTRUCTION}\n"
            "</tau2_benchmark_contract>",
            f"<domain_policy>\n{domain_policy.strip()}\n</domain_policy>",
        ]
    )


def register_tau2_agent(
    *,
    root: Path,
    model: str = TAU2_MODEL,
    max_tokens: int = 700,
) -> Tau2AdapterMetadata:
    """Register the Klara candidate in an installed tau2 runtime.

    tau2 is deliberately an optional benchmark dependency, so imports stay
    inside this function and the main AgentLadder environment remains clean.
    """

    from tau2.agent.llm_agent import LLMAgent, LLMAgentState
    from tau2.data_model.message import (
        AssistantMessage,
        MultiToolMessage,
        ToolCall as Tau2ToolCall,
    )
    from tau2.registry import registry

    persona_path = root / "src" / "klara" / "prompts" / "persona.md"
    persona = persona_path.read_text(encoding="utf-8")
    models = load_models_config(root / "config")
    provider_id = model.split("/", 1)[0]
    delegate = OpenAICompatibleLlmClient(
        provider_id=provider_id,
        provider=models.providers[provider_id],
        settings=OpenAICompatibleSettings(
            max_tokens=max_tokens,
            temperature=0.0,
            timeout_seconds=90,
            retry_attempts=2,
            retry_base_delay_seconds=0.5,
            retry_max_delay_seconds=2.0,
        ),
        dotenv_path=str(root / ".env"),
    )
    client = OutputContractLlmClient(delegate)

    class KlaraTau2Agent(LLMAgent):
        """Half-duplex tau2 participant backed by Klara's real model boundary."""

        def __init__(self, tools, domain_policy, **_: Any) -> None:
            super().__init__(
                tools=tools,
                domain_policy=domain_policy,
                llm=model,
                llm_args={},
            )
            self.klara_system_prompt = build_tau2_system_prompt(
                persona=persona,
                domain_policy=domain_policy,
            )
            self.klara_tools = tau2_tools_to_klara(tools)

        def _generate_next_message(self, message, state: LLMAgentState):
            if isinstance(message, MultiToolMessage):
                state.messages.extend(message.tool_messages)
            else:
                state.messages.append(message)
            started = perf_counter()
            response: ModelResponse = client.complete(
                system_prompt=self.klara_system_prompt,
                messages=tau2_messages_to_klara(state.messages),
                tools=self.klara_tools,
                model=model,
                thinking_enabled=False,
            )
            generation_seconds = perf_counter() - started
            tool_calls = [
                Tau2ToolCall(
                    id=call.id,
                    name=call.name,
                    arguments=call.arguments,
                    requestor="assistant",
                )
                for call in response.tool_calls
            ]
            # tau2's half-duplex protocol forbids mixing text and tool calls.
            content = None if tool_calls else response.content.strip()
            if not tool_calls and not content:
                raise ValueError("Klara returned an empty tau2 message")
            return AssistantMessage(
                role="assistant",
                content=content,
                tool_calls=tool_calls or None,
                cost=_deepseek_flash_cost(response.usage),
                usage=response.usage,
                generation_time_seconds=generation_seconds,
                raw_data={
                    "model_used": response.model_used,
                    "adapter": TAU2_AGENT_NAME,
                },
            )

    def factory(tools, domain_policy, **kwargs):
        return KlaraTau2Agent(tools=tools, domain_policy=domain_policy, **kwargs)

    if TAU2_AGENT_NAME not in registry.get_agents():
        registry.register_agent_factory(
            factory,
            TAU2_AGENT_NAME,
            metadata={"adapter": "AgentLadder", "full_product_runtime": False},
        )
    prompt = build_tau2_system_prompt(persona=persona, domain_policy="<per-domain>")
    return Tau2AdapterMetadata(
        agent_name=TAU2_AGENT_NAME,
        model=model,
        persona_sha256=sha256(persona.encode("utf-8")).hexdigest(),
        prompt_sha256=sha256(prompt.encode("utf-8")).hexdigest(),
    )


def _deepseek_flash_cost(usage: dict[str, Any] | None) -> float:
    """Conservative cache-miss price used by the frozen live manifest."""

    values = usage or {}
    prompt = int(values.get("prompt_tokens", 0))
    completion = int(values.get("completion_tokens", 0))
    return (prompt * 0.14 + completion * 0.28) / 1_000_000
