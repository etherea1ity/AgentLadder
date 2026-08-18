"""Local Klara MoE adapter for the unified three-way evaluation harness.

This adapter owns the local-policy boundary that ``three_way_eval`` leaves open.
It loads a repository-native Klara MoE checkpoint (either the pretraining
format or the trajectory-SFT format), builds the matching four-expert top-2
sparse model, and performs deterministic greedy decoding with the portable
256-byte :class:`ByteTokenizer`.

The generated text follows the same frozen tool protocol used by SFT: a
ChatML-like transcript where assistant tool requests are compact
``<tool_call>{...}</tool_call>`` blocks and the final answer is ordinary
assistant text.  The harness still receives a provider-independent
:class:`ModelResponse`, so it can run klara/qwen/deepseek through the exact
same loop.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

import torch

from klara.core.messages import KlaraMessage, ModelResponse
from klara.core.tools import ToolCall, ToolSpec
from klara.training.config import ModelConfig
from klara.training.moe import MoEConfig, build_moe_model
from klara.training.moe_pretrain import MOE_PRETRAIN_CHECKPOINT_FORMAT
from klara.training.sft import SFT_CHECKPOINT_FORMAT
from klara.training.tokenizer import ByteTokenizer

DEFAULT_KLARA_MODEL = "klara/klara-124m"
SUPPORTED_CHECKPOINT_FORMATS = {
    MOE_PRETRAIN_CHECKPOINT_FORMAT,
    SFT_CHECKPOINT_FORMAT,
}

_IM_START = "<|im_start|>"
_IM_END = "<|im_end|>"
_TOOL_CALL_RE = re.compile(r"<tool_call>(.*?)</tool_call>", flags=re.S)


def _json_compact(value: Any) -> str:
    """Serialize a JSON value without whitespace for stable prompts."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(frozen=True)
class _CheckpointInfo:
    """Metadata returned after a local checkpoint is loaded."""

    format: str
    step: int
    metadata: dict[str, Any]


class KlaraModelAdapter:
    """Load a Klara checkpoint and adapt it to ``three_way_eval.ModelAdapter``."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_KLARA_MODEL,
        checkpoint: str | Path | None = None,
        checkpoint_path: str | Path | None = None,
        device: str | torch.device | None = None,
        max_new_tokens: int = 512,
        **_: Any,
    ) -> None:
        self._model = str(model)
        checkpoint_value = checkpoint_path if checkpoint_path is not None else checkpoint
        if checkpoint_value is None:
            raise ValueError(
                "KlaraModelAdapter requires a local checkpoint; pass "
                "checkpoint=/path/to/checkpoint.pt"
            )
        self.checkpoint_path = Path(checkpoint_value)
        self._tokenizer = ByteTokenizer()
        self._max_new_tokens = max_new_tokens
        if max_new_tokens < 1:
            raise ValueError("max_new_tokens must be positive")

        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self._device = torch.device(device)

        self._model_config, self._model_torch, self._checkpoint_info = (
            self._load_checkpoint(self.checkpoint_path)
        )
        if self._tokenizer.vocab_size != self._model_config.vocab_size:
            raise ValueError(
                "ByteTokenizer vocabulary does not match checkpoint model config: "
                f"{self._tokenizer.vocab_size} != {self._model_config.vocab_size}"
            )
        self._model_torch.to(self._device).eval()

    @property
    def model(self) -> str:
        return self._model

    @property
    def device(self) -> torch.device:
        return self._device

    @property
    def checkpoint_info(self) -> _CheckpointInfo:
        return self._checkpoint_info

    def _load_checkpoint(
        self,
        path: Path,
    ) -> tuple[ModelConfig, Any, _CheckpointInfo]:
        """Load and validate one supported Klara checkpoint."""

        if not path.exists():
            raise FileNotFoundError(f"Klara checkpoint not found: {path}")
        payload = torch.load(path, map_location="cpu", weights_only=False)
        if not isinstance(payload, dict):
            raise ValueError("unsupported Klara checkpoint payload")
        checkpoint_format = str(payload.get("format") or "")
        if checkpoint_format not in SUPPORTED_CHECKPOINT_FORMATS:
            raise ValueError(
                "unsupported Klara checkpoint format: "
                f"{checkpoint_format!r}; expected one of "
                f"{sorted(SUPPORTED_CHECKPOINT_FORMATS)}"
            )
        model_config = ModelConfig.from_dict(dict(payload.get("model_config", {})))
        moe_config = MoEConfig()
        model_torch = build_moe_model(model_config, moe_config)
        model_torch.load_state_dict(payload["model_state"], strict=True)
        return (
            model_config,
            model_torch,
            _CheckpointInfo(
                format=checkpoint_format,
                step=int(payload.get("step", 0)),
                metadata=dict(payload.get("metadata", {})),
            ),
        )

    def complete(
        self,
        *,
        system_prompt: str,
        messages: tuple[KlaraMessage, ...],
        tools: tuple[ToolSpec, ...],
    ) -> ModelResponse:
        """Produce one local Klara response for the current transcript."""

        prompt_text = _render_prompt(system_prompt, messages, tools)
        prompt_ids = self._tokenizer.encode(
            prompt_text,
            add_bos=True,
            add_eos=False,
        )
        prompt_tensor = torch.tensor(
            [prompt_ids],
            dtype=torch.long,
            device=self._device,
        )
        with torch.inference_mode():
            generated = self._model_torch.generate(
                prompt_tensor,
                max_new_tokens=self._max_new_tokens,
                eos_token_id=self._tokenizer.eos_token_id,
            )
        new_tokens = generated[0, prompt_tensor.shape[1] :].tolist()
        completion_text = self._tokenizer.decode(new_tokens, skip_special=True)
        tool_calls = _parse_tool_calls(completion_text)
        content = "" if tool_calls else completion_text.strip()
        return ModelResponse(
            content=content,
            tool_calls=tuple(tool_calls),
            usage={
                "prompt_tokens": len(prompt_ids),
                "completion_tokens": len(new_tokens),
                "total_tokens": len(prompt_ids) + len(new_tokens),
            },
        )


def _render_prompt(
    system_prompt: str,
    messages: tuple[KlaraMessage, ...],
    tools: tuple[ToolSpec, ...],
) -> str:
    """Render the frozen local-policy prompt in SFT-compatible ChatML."""

    parts = [f"{_IM_START}system\n{system_prompt.rstrip()}\n"]
    if tools:
        parts.append("Available tools:\n")
        for tool in tools:
            parts.append(_json_compact(tool.to_public_dict()))
            parts.append("\n")
    parts.append(f"{_IM_END}\n")
    for message in messages:
        parts.append(_render_message(message))
    parts.append(f"{_IM_START}assistant\n")
    return "".join(parts)


def _render_message(message: KlaraMessage) -> str:
    """Render one Klara core message using the same compact protocol as SFT."""

    role = message.role
    content = str(message.content or "")
    parts = [f"{_IM_START}{role}\n"]
    if role == "assistant":
        for call in message.tool_calls:
            parts.append("<tool_call>")
            parts.append(
                _json_compact(
                    {"name": call.name, "arguments": dict(call.arguments)}
                )
            )
            parts.append("</tool_call>\n")
    if content:
        parts.append(content.rstrip() + "\n")
    parts.append(f"{_IM_END}\n")
    return "".join(parts)


def _parse_tool_calls(text: str) -> list[ToolCall]:
    """Parse frozen-protocol tool calls from decoded completion text."""

    calls: list[ToolCall] = []
    for match in _TOOL_CALL_RE.findall(text):
        raw = match.strip()
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        name = parsed.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        arguments = parsed.get("arguments")
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            try:
                arguments = dict(arguments)
            except (TypeError, ValueError):
                arguments = {}
        calls.append(
            ToolCall(
                id=f"call_{len(calls) + 1}",
                name=name,
                arguments=dict(arguments),
            )
        )
    return calls


__all__ = ["KlaraModelAdapter"]
