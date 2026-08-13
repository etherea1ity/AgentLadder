"""Fail-closed boundary for model text that contains internal wire protocols."""

from __future__ import annotations

from dataclasses import replace
import re

from klara.core.messages import KlaraMessage, ModelCallError, ModelResponse
from klara.core.tools import ToolSpec


_INTERNAL_PROTOCOL_PATTERN = re.compile(
    r"<\s*(?:\|DSML\||｜DSML｜|｜｜DSML｜｜)"
    r"(?:tool_calls|function_calls|invoke|parameter)\b",
    re.IGNORECASE,
)
WITHHELD_PROTOCOL_ANSWER = (
    "This historical response was withheld because it contained an unparsed "
    "provider tool-call protocol. Please retry the request."
)


def contains_internal_protocol(text: str) -> bool:
    """Return whether text contains a model/provider tool wire marker."""

    return bool(_INTERNAL_PROTOCOL_PATTERN.search(text))


def public_answer_text(text: str) -> str:
    """Project stored assistant content without replaying protocol markup."""

    return WITHHELD_PROTOCOL_ANSWER if contains_internal_protocol(text) else text


class OutputContractLlmClient:
    """Reject protocol leakage after provider normalization and before the loop."""

    def __init__(self, delegate) -> None:
        self.delegate = delegate

    def complete(
        self,
        *,
        system_prompt: str,
        messages: tuple[KlaraMessage, ...],
        tools: tuple[ToolSpec, ...],
        model: str,
        thinking_enabled: bool | None = None,
    ) -> ModelResponse:
        response = self.delegate.complete(
            system_prompt=system_prompt,
            messages=messages,
            tools=tools,
            model=model,
            thinking_enabled=thinking_enabled,
        )
        if not contains_internal_protocol(response.content):
            return response
        if response.tool_calls:
            return replace(response, content="")
        raise ModelCallError(
            "provider returned an unparsed internal tool protocol",
            code="provider_tool_protocol_invalid",
        )
