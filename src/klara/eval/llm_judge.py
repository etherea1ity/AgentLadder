"""LLM-as-judge for AgentLadder public agent tasks.

Uses DeepSeek V4 Pro as an isolated judge (not one of the compared models).
Deterministic strict/normalized scorers remain the primary signal; the judge
adds a third column with a structured verdict and rationale for answer quality.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[3]
import sys
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

from klara.core.messages import KlaraMessage
from klara.infra.config.loader import load_models_config
from klara.infra.llm.openai_compatible import (
    OpenAICompatibleLlmClient,
    OpenAICompatibleSettings,
)

JUDGE_MODEL = "deepseek/deepseek-v4-pro"

JUDGE_SYSTEM_PROMPT = (
    "You are an evaluation judge for tool-calling agents. "
    "Judge only whether the agent's final answer correctly answers the user "
    "instruction, using the supplied gold reference facts. Do not require exact "
    "wording, and do not penalize paraphrasing or extra formatting. "
    "Return strict JSON only: {\"verdict\": 1 or 0, \"reason\": \"one short sentence\"}."
)


def _build_prompt(
    *,
    user_turn: str,
    expected_tool_calls: list[dict[str, Any]],
    reference_answer: str | None,
    acceptable_answers: list[str],
    observed_tool_calls: list[dict[str, Any]],
    final_answer: str,
) -> str:
    gold = {
        "expected_tool_calls": expected_tool_calls,
        "reference_answer": reference_answer,
        "acceptable_answers": acceptable_answers,
    }
    return (
        "Instruction:\n"
        f"{user_turn}\n\n"
        "Gold reference:\n"
        f"{json.dumps(gold, ensure_ascii=False, indent=2)}\n\n"
        "Agent observed tool calls:\n"
        f"{json.dumps(observed_tool_calls, ensure_ascii=False, indent=2)}\n\n"
        "Agent final answer:\n"
        f"{final_answer or '<empty>'}\n"
    )


def _extract_json(text: str) -> dict[str, Any]:
    if not text:
        return {}
    # Strip markdown code fences if present.
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            text = text[start : end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def make_judge_client(root: Path | str = ".") -> OpenAICompatibleLlmClient:
    root = Path(root)
    config = load_models_config(root / "config")
    provider = config.providers["deepseek"]
    return OpenAICompatibleLlmClient(
        provider_id="deepseek",
        provider=provider,
        settings=OpenAICompatibleSettings(
            max_tokens=256,
            temperature=0.0,
            timeout_seconds=60,
            retry_attempts=3,
        ),
        dotenv_path=str(root / ".env"),
    )


def judge_task(
    client: OpenAICompatibleLlmClient,
    *,
    user_turn: str,
    expected_tool_calls: list[dict[str, Any]],
    reference_answer: str | None,
    acceptable_answers: list[str],
    observed_tool_calls: list[dict[str, Any]],
    final_answer: str,
) -> dict[str, Any]:
    if not final_answer.strip():
        return {"verdict": 0, "reason": "empty final answer"}

    prompt = _build_prompt(
        user_turn=user_turn,
        expected_tool_calls=expected_tool_calls,
        reference_answer=reference_answer,
        acceptable_answers=acceptable_answers,
        observed_tool_calls=observed_tool_calls,
        final_answer=final_answer,
    )
    response = client.complete(
        system_prompt=JUDGE_SYSTEM_PROMPT,
        messages=(KlaraMessage(role="user", content=prompt),),
        tools=(),
        model=JUDGE_MODEL,
        thinking_enabled=False,
    )
    parsed = _extract_json(response.content or "")
    verdict = parsed.get("verdict")
    if isinstance(verdict, bool):
        verdict = int(verdict)
    if isinstance(verdict, str):
        verdict = int(verdict) if verdict.strip().isdigit() else 0
    if verdict not in (0, 1):
        verdict = 0
    reason = str(parsed.get("reason", ""))
    return {"verdict": verdict, "reason": reason, "raw": response.content}
