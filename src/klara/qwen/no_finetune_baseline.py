"""No-finetune Qwen2.5-1.5B-Instruct baseline through the unified harness.

This module implements a local :class:`~klara.eval.three_way_eval.ModelAdapter`
for a Hugging Face Qwen checkpoint and feeds it into
:func:`klara.eval.three_way_eval.evaluate`. The harness remains the same frozen
benchmark used by Klara and DeepSeek.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any
import tomllib

from klara.core.messages import KlaraMessage, ModelResponse
from klara.core.tools import ToolCall, ToolSpec
from klara.eval.three_way_eval import EvalHarness, Pricing, evaluate, load_eval_bundle

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_QWEN_TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*(.*?)\s*</tool_call>",
    re.IGNORECASE | re.DOTALL,
)


def _resolve_path(value: str, *, root: Path, config_dir: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    if (config_dir / path).exists():
        return config_dir / path
    return root / path


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"config file not found: {path}")
    return tomllib.loads(path.read_text(encoding="utf-8-sig"))


def _table(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{key} must be a table")
    return value


def _int_config(raw: dict[str, Any], key: str, default: int) -> int:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return int(value)


def _float_config(raw: dict[str, Any], key: str, default: float) -> float:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be a number")
    return float(value)


def _bool_config(raw: dict[str, Any], key: str, default: bool) -> bool:
    value = raw.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


def _tool_to_qwen_function(tool: ToolSpec) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
        },
    }


def _klara_messages_to_qwen(
    *,
    system_prompt: str,
    messages: tuple[KlaraMessage, ...],
) -> list[dict[str, Any]]:
    """Convert Klara transcript messages into Qwen chat-template messages."""

    converted: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    for message in messages:
        if message.role == "tool":
            converted.append({"role": "tool", "content": message.content})
            continue
        item: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.role == "assistant" and message.tool_calls:
            tool_calls = [
                {
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": dict(call.arguments),
                    },
                }
                for call in message.tool_calls
            ]
            item["tool_calls"] = tool_calls
        converted.append(item)
    return converted


def _parse_qwen_completion(text: str) -> tuple[str, list[ToolCall]]:
    """Parse Qwen's native ``<tool_call>`` blocks into Klara tool calls."""

    tool_calls: list[ToolCall] = []
    pieces = _QWEN_TOOL_CALL_RE.split(text)
    text_outside: list[str] = []
    for index, piece in enumerate(pieces):
        if index % 2 == 0:
            text_outside.append(piece)
            continue
        try:
            raw_call = json.loads(piece.strip())
        except json.JSONDecodeError:
            text_outside.append(piece)
            continue
        if not isinstance(raw_call, dict):
            continue
        arguments = raw_call.get("arguments", {})
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments.strip() else {}
            except json.JSONDecodeError:
                arguments = {}
        name = str(raw_call.get("name", ""))
        if name:
            tool_calls.append(
                ToolCall(
                    id=f"qwen-local-{len(tool_calls)}",
                    name=name,
                    arguments=arguments,
                )
            )
    return "".join(text_outside).strip(), tool_calls
class LocalQwenModelAdapter:
    """Local Qwen adapter compatible with :class:`ModelAdapter`.

    Weights are loaded lazily on the first ``complete`` call, so importing this
    module and building the adapter do not allocate the 1.5B checkpoint.
    """

    def __init__(
        self,
        model_path: str = "Qwen/Qwen2.5-1.5B-Instruct",
        *,
        adapter_path: str | Path | None = None,
        load_in_4bit: bool = True,
        max_new_tokens: int = 512,
        temperature: float = 0.0,
        attn_implementation: str = "sdpa",
    ) -> None:
        self.model_path = model_path
        self.adapter_path = str(adapter_path) if adapter_path else None
        self.load_in_4bit = load_in_4bit
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature
        self.attn_implementation = attn_implementation
        self._model: Any = None
        self._tokenizer: Any = None

    @property
    def model(self) -> str:
        return self.model_path

    def _ensure_loaded(self) -> None:
        if self._model is not None:
            return

        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

        quantization_config = None
        dtype = torch.bfloat16 if torch.cuda.is_available() else torch.float32
        if self.load_in_4bit and torch.cuda.is_available():
            quantization_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=dtype,
                bnb_4bit_use_double_quant=True,
            )

        self._tokenizer = AutoTokenizer.from_pretrained(self.model_path)
        if self._tokenizer.pad_token_id is None:
            self._tokenizer.pad_token = self._tokenizer.eos_token

        self._model = AutoModelForCausalLM.from_pretrained(
            self.model_path,
            quantization_config=quantization_config,
            device_map="auto" if torch.cuda.is_available() else None,
            torch_dtype=dtype,
            attn_implementation=self.attn_implementation,
            trust_remote_code=True,
        )
        if self.adapter_path:
            from peft import PeftModel

            self._model = PeftModel.from_pretrained(self._model, self.adapter_path)
        self._model.eval()

    def complete(
        self,
        *,
        system_prompt: str,
        messages: tuple[KlaraMessage, ...],
        tools: tuple[ToolSpec, ...],
    ) -> ModelResponse:
        self._ensure_loaded()
        import torch

        qwen_messages = _klara_messages_to_qwen(
            system_prompt=system_prompt,
            messages=messages,
        )
        qwen_tools = [_tool_to_qwen_function(tool) for tool in tools]

        encoding = self._tokenizer.apply_chat_template(
            qwen_messages,
            tools=qwen_tools,
            add_generation_prompt=True,
            tokenize=True,
            return_tensors="pt",
        )
        input_ids = encoding["input_ids"].to(next(self._model.parameters()).device)

        with torch.no_grad():
            outputs = self._model.generate(
                input_ids,
                max_new_tokens=self.max_new_tokens,
                do_sample=self.temperature > 0.0,
                temperature=self.temperature if self.temperature > 0.0 else None,
                pad_token_id=self._tokenizer.pad_token_id,
                eos_token_id=self._tokenizer.eos_token_id,
            )
        generated = outputs[0][input_ids.shape[-1] :]
        text = self._tokenizer.decode(generated, skip_special_tokens=False)
        final_text, tool_calls = _parse_qwen_completion(text)

        prompt_tokens = int(input_ids.shape[-1])
        completion_tokens = int(generated.shape[-1])
        return ModelResponse(
            content=final_text,
            tool_calls=tuple(tool_calls),
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        )

def run_baseline(
    eval_config_path: str | Path,
    *,
    model_path: str = "Qwen/Qwen2.5-1.5B-Instruct",
    adapter_path: str | Path | None = None,
    load_in_4bit: bool = True,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run the no-finetune baseline against a frozen eval bundle."""

    config_path = Path(eval_config_path).resolve()
    raw = _load_toml(config_path)
    config_dir = config_path.parent

    model = str(raw.get("model", model_path))
    fixture_path = _resolve_path(
        str(raw["benchmark_fixture"]),
        root=REPOSITORY_ROOT,
        config_dir=config_dir,
    )
    benchmark, backend = load_eval_bundle(fixture_path)

    harness_raw = _table(raw, "harness")
    pricing_raw = _table(raw, "pricing")
    harness = EvalHarness(
        backend=backend,
        max_steps=_int_config(harness_raw, "max_steps", 8),
        max_tokens=_int_config(harness_raw, "max_tokens", 512),
        temperature=_float_config(harness_raw, "temperature", 0.0),
        timeout_seconds=_int_config(harness_raw, "timeout_seconds", 120),
        retry_attempts=_int_config(harness_raw, "retry_attempts", 2),
        retry_base_delay_seconds=_float_config(
            harness_raw, "retry_base_delay_seconds", 0.0
        ),
        retry_max_delay_seconds=_float_config(
            harness_raw, "retry_max_delay_seconds", 0.0
        ),
        ordered_tool_calls=_bool_config(
            harness_raw, "ordered_tool_calls", False
        ),
        pricing=Pricing(
            currency=str(pricing_raw.get("currency", "USD")),
            input_usd_per_million=_float_config(
                pricing_raw, "input_usd_per_million", 0.0
            ),
            output_usd_per_million=_float_config(
                pricing_raw, "output_usd_per_million", 0.0
            ),
        ),
        root=REPOSITORY_ROOT,
    )

    adapter = LocalQwenModelAdapter(
        model_path=model_path or model,
        adapter_path=adapter_path,
        load_in_4bit=load_in_4bit,
        max_new_tokens=harness.max_tokens,
        temperature=harness.temperature,
    )
    report = evaluate(model, benchmark, harness, adapter=adapter)

    results_dir = _resolve_path(
        str(raw.get("results_dir", "results")),
        root=REPOSITORY_ROOT,
        config_dir=config_dir,
    )
    if output_path:
        output_file = _resolve_path(str(output_path), root=REPOSITORY_ROOT, config_dir=config_dir)
    else:
        output_name = model_path.replace("/", "-").replace("\\", "-") + ".json"
        output_file = results_dir / output_name
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    smoke = subparsers.add_parser("smoke", help="import/adapter smoke test without loading weights")
    run = subparsers.add_parser("run", help="run the no-finetune baseline")
    run.add_argument("--eval-config", required=True)
    run.add_argument("--model", default="Qwen/Qwen2.5-1.5B-Instruct")
    run.add_argument("--adapter", default=None)
    run.add_argument("--load-in-4bit", action="store_true", default=True)
    run.add_argument("--no-4bit", action="store_true")
    run.add_argument("--output", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "smoke":
        adapter = LocalQwenModelAdapter(args.model if hasattr(args, "model") else "Qwen/Qwen2.5-1.5B-Instruct")
        print(json.dumps({
            "schema_version": "klara.qwen-no-finetune-baseline.v1",
            "model": adapter.model,
            "adapter_model": adapter.model,
            "weights_loaded": False,
            "ok": True,
        }, ensure_ascii=False, indent=2))
        return 0
    if args.command == "run":
        report = run_baseline(
            args.eval_config,
            model_path=args.model,
            adapter_path=args.adapter,
            load_in_4bit=not args.no_4bit,
            output_path=args.output,
        )
        metrics = report["metrics"]
        print(json.dumps({
            "model": report["model"],
            "benchmark": report["benchmark"],
            "metrics": metrics,
            "counts": report["counts"],
        }, ensure_ascii=False, indent=2))
        return 0
    raise AssertionError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
