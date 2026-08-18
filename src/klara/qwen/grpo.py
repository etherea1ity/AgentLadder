"""GRPO training for Qwen2.5-1.5B-Instruct with a Klara-compatible reward.

The default path is a minimal, self-contained group-relative policy gradient
loop that does not require TRL. It performs multi-step rollouts against the
reference trajectory's frozen tool results and scores every rollout with the
same reward components used by the three-way harness:

    task_success + tool_selection + valid_arguments
    - illegal_calls - step_over_budget

If ``[grpo].use_trl = true`` and TRL is installed, ``train`` tries the TRL
``GRPOTrainer`` first and falls back to the minimal loop on import/API errors.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import tomllib

from klara.qwen.qlora_sft import (
    DEFAULT_LORA_TARGET_MODULES,
    QWEN_TOOL_SPECS,
    build_qwen_tools,
    load_jsonl,
    trajectory_to_hf_messages,
)

_QWEN_TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*(.*?)\s*</tool_call>",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class RewardWeights:
    """Weights for the Klara-compatible GRPO reward."""

    task_success: float = 1.0
    tool_selection: float = 0.5
    valid_arguments: float = 0.5
    illegal_call: float = 1.0
    step_over_budget: float = 0.1


@dataclass(frozen=True)
class RewardBreakdown:
    reward: float
    task_success: float
    tool_selection: float
    valid_arguments: float
    illegal_calls: int
    step_count: int
    max_steps: int
    step_over_budget: int


def _expect_dict(raw: dict[str, Any], key: str, *, path: str) -> dict[str, Any]:
    value = raw.get(key, {})
    if not isinstance(value, dict):
        raise ValueError(f"{path}.{key} must be a table")
    return value


def _expect_int(
    raw: dict[str, Any],
    key: str,
    *,
    default: int,
    minimum: int | None = None,
    path: str,
) -> int:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{path}.{key} must be an integer")
    if minimum is not None and value < minimum:
        raise ValueError(f"{path}.{key} must be >= {minimum}")
    return int(value)


def _expect_float(
    raw: dict[str, Any],
    key: str,
    *,
    default: float,
    minimum: float | None = None,
    path: str,
) -> float:
    value = raw.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path}.{key} must be a number")
    value = float(value)
    if minimum is not None and value < minimum:
        raise ValueError(f"{path}.{key} must be >= {minimum}")
    return value


def _expect_bool(raw: dict[str, Any], key: str, *, default: bool, path: str) -> bool:
    value = raw.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{path}.{key} must be a boolean")
    return value


def _expect_str(raw: dict[str, Any], key: str, *, default: str, path: str) -> str:
    value = raw.get(key, default)
    if not isinstance(value, str):
        raise ValueError(f"{path}.{key} must be a string")
    return value
def validate_config(config_path: str | Path) -> dict[str, Any]:
    """Validate ``qwen_grpo.toml`` and return normalized settings."""

    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"config file not found: {config_path}")
    raw = tomllib.loads(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(raw, dict):
        raise ValueError("config root must be a TOML table")

    experiment = _expect_dict(raw, "experiment", path="config")
    model = _expect_dict(raw, "model", path="config")
    lora = _expect_dict(raw, "lora", path="config")
    data = _expect_dict(raw, "data", path="config")
    reward_raw = _expect_dict(raw, "reward", path="config")
    grpo = _expect_dict(raw, "grpo", path="config")

    base_model = _expect_str(model, "base_model", default="Qwen/Qwen2.5-1.5B-Instruct", path="config.model")
    adapter_path = _expect_str(model, "adapter_path", default="", path="config.model")
    max_sequence_length = _expect_int(model, "max_sequence_length", default=1024, minimum=1, path="config.model")
    load_in_4bit = _expect_bool(model, "load_in_4bit", default=True, path="config.model")
    bnb_4bit_quant_type = _expect_str(model, "bnb_4bit_quant_type", default="nf4", path="config.model")
    if bnb_4bit_quant_type not in {"nf4", "fp4"}:
        raise ValueError("config.model.bnb_4bit_quant_type must be nf4 or fp4")
    bnb_4bit_compute_dtype = _expect_str(model, "bnb_4bit_compute_dtype", default="bfloat16", path="config.model")
    if bnb_4bit_compute_dtype not in {"bfloat16", "float16", "float32"}:
        raise ValueError("config.model.bnb_4bit_compute_dtype must be bfloat16, float16, or float32")
    attn_implementation = _expect_str(model, "attn_implementation", default="sdpa", path="config.model")

    target_modules = lora.get("target_modules", DEFAULT_LORA_TARGET_MODULES)
    if not isinstance(target_modules, list) or not target_modules:
        raise ValueError("config.lora.target_modules must be a non-empty list")
    if not all(isinstance(item, str) and item.strip() for item in target_modules):
        raise ValueError("config.lora.target_modules must contain strings")
    target_modules = [str(item).strip() for item in target_modules]

    lora_r = _expect_int(lora, "r", default=16, minimum=1, path="config.lora")
    lora_alpha = _expect_int(lora, "lora_alpha", default=32, minimum=1, path="config.lora")
    lora_dropout = _expect_float(lora, "lora_dropout", default=0.05, minimum=0.0, path="config.lora")

    data_path = _expect_str(data, "path", default="data/trajectories/clean.jsonl", path="config.data")
    max_records = _expect_int(data, "max_records", default=0, minimum=0, path="config.data")
    val_split = _expect_float(data, "val_split", default=0.05, minimum=0.0, path="config.data")
    if val_split >= 1.0:
        raise ValueError("config.data.val_split must be < 1.0")

    weights = RewardWeights(
        task_success=_expect_float(reward_raw, "task_success", default=1.0, minimum=0.0, path="config.reward"),
        tool_selection=_expect_float(reward_raw, "tool_selection", default=0.5, minimum=0.0, path="config.reward"),
        valid_arguments=_expect_float(reward_raw, "valid_arguments", default=0.5, minimum=0.0, path="config.reward"),
        illegal_call=_expect_float(reward_raw, "illegal_call", default=1.0, minimum=0.0, path="config.reward"),
        step_over_budget=_expect_float(reward_raw, "step_over_budget", default=0.1, minimum=0.0, path="config.reward"),
    )

    max_steps = _expect_int(grpo, "max_steps", default=8, minimum=1, path="config.grpo")
    generations_per_prompt = _expect_int(grpo, "generations_per_prompt", default=4, minimum=1, path="config.grpo")
    batch_size = _expect_int(grpo, "batch_size", default=2, minimum=1, path="config.grpo")
    max_completion_length = _expect_int(grpo, "max_completion_length", default=512, minimum=1, path="config.grpo")
    temperature = _expect_float(grpo, "temperature", default=0.7, minimum=0.0, path="config.grpo")
    learning_rate = _expect_float(grpo, "learning_rate", default=1e-5, minimum=0.0, path="config.grpo")
    weight_decay = _expect_float(grpo, "weight_decay", default=0.0, minimum=0.0, path="config.grpo")
    gradient_accumulation_steps = _expect_int(grpo, "gradient_accumulation_steps", default=4, minimum=1, path="config.grpo")
    num_steps = _expect_int(grpo, "num_steps", default=100, minimum=1, path="config.grpo")
    log_every = _expect_int(grpo, "log_every", default=1, minimum=1, path="config.grpo")
    save_every = _expect_int(grpo, "save_every", default=0, minimum=0, path="config.grpo")
    output_dir = _expect_str(grpo, "output_dir", default="artifacts/qwen-grpo", path="config.grpo")
    use_trl = _expect_bool(grpo, "use_trl", default=False, path="config.grpo")
    bf16 = _expect_bool(grpo, "bf16", default=True, path="config.grpo")
    seed = _expect_int(grpo, "seed", default=20260816, minimum=0, path="config.grpo")

    return {
        "experiment": {
            "name": _expect_str(experiment, "name", default="qwen-grpo", path="config.experiment"),
        },
        "model": {
            "base_model": base_model,
            "adapter_path": adapter_path,
            "max_sequence_length": max_sequence_length,
            "load_in_4bit": load_in_4bit,
            "bnb_4bit_quant_type": bnb_4bit_quant_type,
            "bnb_4bit_compute_dtype": bnb_4bit_compute_dtype,
            "attn_implementation": attn_implementation,
        },
        "lora": {
            "r": lora_r,
            "lora_alpha": lora_alpha,
            "lora_dropout": lora_dropout,
            "target_modules": target_modules,
        },
        "data": {
            "path": data_path,
            "max_records": max_records,
            "val_split": val_split,
        },
        "reward": weights,
        "grpo": {
            "max_steps": max_steps,
            "generations_per_prompt": generations_per_prompt,
            "batch_size": batch_size,
            "max_completion_length": max_completion_length,
            "temperature": temperature,
            "learning_rate": learning_rate,
            "weight_decay": weight_decay,
            "gradient_accumulation_steps": gradient_accumulation_steps,
            "num_steps": num_steps,
            "log_every": log_every,
            "save_every": save_every,
            "output_dir": output_dir,
            "use_trl": use_trl,
            "bf16": bf16,
            "seed": seed,
        },
    }


def _resolve_path(value: str, *, config_dir: Path, repo_root: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    if (config_dir / path).exists():
        return config_dir / path
    return repo_root / path

def _json_loads(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value) if value.strip() else {}
        except json.JSONDecodeError:
            return {}
    if isinstance(value, dict):
        return value
    return {}


def parse_qwen_completion(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Split Qwen output into final text and parsed tool calls."""

    tool_calls: list[dict[str, Any]] = []
    pieces = _QWEN_TOOL_CALL_RE.split(text)
    text_outside: list[str] = []
    for index, piece in enumerate(pieces):
        if index % 2 == 0:
            text_outside.append(piece)
        else:
            try:
                raw_call = json.loads(piece.strip())
                if not isinstance(raw_call, dict):
                    continue
                arguments = _json_loads(raw_call.get("arguments"))
                name = str(raw_call.get("name", ""))
                if name:
                    tool_calls.append({"name": name, "arguments": arguments})
            except json.JSONDecodeError:
                tool_calls.append({"name": "", "arguments": {}})
    final_answer = "".join(text_outside).strip()
    return final_answer, tool_calls


def _normalize_answer(value: str) -> str:
    text = value.casefold().strip()
    text = "".join(text.split())
    return text.replace("“", '"').replace("”", '"')


def _arguments_valid(arguments: dict[str, Any], schema: dict[str, Any]) -> bool:
    """Small JSON-schema subset used by the frozen tool backend."""

    if not isinstance(schema, dict):
        return True
    required = schema.get("required")
    if isinstance(required, list):
        for key in required:
            if key not in arguments:
                return False
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for key, value in arguments.items():
            expected = properties.get(key)
            if expected is None:
                if schema.get("additionalProperties") is False:
                    return False
                continue
            if not _json_value_matches(value, expected):
                return False
    return True


def _json_value_matches(value: Any, schema: dict[str, Any]) -> bool:
    expected_type = schema.get("type")
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "object":
        return isinstance(value, dict)
    return True


def _expected_tool_call_match(
    expected: dict[str, Any],
    observed: dict[str, Any],
) -> bool:
    return expected.get("name") == observed.get("name") and expected.get("arguments", {}) == observed.get("arguments", {})


def _tool_call_accuracy(
    expected_calls: list[dict[str, Any]],
    observed_calls: list[dict[str, Any]],
) -> float:
    if not expected_calls and not observed_calls:
        return 1.0
    if not expected_calls or not observed_calls:
        return 0.0
    remaining = list(observed_calls)
    matched = 0
    for want in expected_calls:
        for index, candidate in enumerate(remaining):
            if _expected_tool_call_match(want, candidate):
                matched += 1
                remaining.pop(index)
                break
    return matched / max(len(expected_calls), len(observed_calls))


def reward_breakdown_for_rollout(
    record: dict[str, Any],
    *,
    final_answer: str,
    tool_calls: list[dict[str, Any]],
    weights: RewardWeights,
    default_max_steps: int,
) -> RewardBreakdown:
    """Score one rollout against a reference trajectory.

    ``tool_calls`` are the model's observed calls in execution order. Expected
    calls and the final answer come from the clean teacher trajectory, while
    argument validity is checked against the frozen tool schema.
    """

    task = record.get("task") or {}
    available_tools = task.get("available_tools", [])
    if not isinstance(available_tools, list):
        available_tools = []
    tool_specs = {name: QWEN_TOOL_SPECS.get(name) for name in available_tools}

    expected_tool_calls: list[dict[str, Any]] = []
    for call in record.get("tool_calls", []):
        if isinstance(call, dict):
            expected_tool_calls.append(
                {
                    "name": str(call.get("name", "")),
                    "arguments": dict(call.get("arguments", {}) or {}),
                }
            )

    expected_behavior = task.get("expected_behavior") or {}
    max_steps = int(expected_behavior.get("max_tool_calls", default_max_steps) or default_max_steps)

    explicit_reference = None
    task = record.get("task") or {}
    for key in ("reference_answer", "acceptable_answers"):
        value = task.get(key)
        if isinstance(value, str) and value:
            explicit_reference = value
            break
        if isinstance(value, list) and value:
            explicit_reference = str(value[0])
            break

    tool_selection = _tool_call_accuracy(expected_tool_calls, tool_calls)

    if explicit_reference:
        task_success = (
            1.0
            if _normalize_answer(explicit_reference) in _normalize_answer(final_answer)
            else 0.0
        )
    else:
        # Mirrors three_way_eval's no-reference fallback: a task succeeds when
        # the expected tools are reproduced and a non-empty final answer is
        # produced.
        task_success = 1.0 if tool_selection >= 1.0 and bool(final_answer.strip()) else 0.0

    illegal_calls = 0
    valid_calls = 0
    for call in tool_calls:
        name = str(call.get("name", ""))
        arguments = dict(call.get("arguments", {}) or {})
        spec = tool_specs.get(name) if name else None
        if spec is None or not _arguments_valid(arguments, spec.get("input_schema", {})):
            illegal_calls += 1
        else:
            valid_calls += 1
    valid_arguments = valid_calls / len(tool_calls) if tool_calls else 1.0
    step_count = len(tool_calls)
    step_over_budget = max(0, step_count - max_steps)

    reward = (
        task_success * weights.task_success
        + tool_selection * weights.tool_selection
        + valid_arguments * weights.valid_arguments
        - illegal_calls * weights.illegal_call
        - step_over_budget * weights.step_over_budget
    )
    return RewardBreakdown(
        reward=float(reward),
        task_success=task_success,
        tool_selection=tool_selection,
        valid_arguments=valid_arguments,
        illegal_calls=illegal_calls,
        step_count=step_count,
        max_steps=max_steps,
        step_over_budget=step_over_budget,
    )


def klara_reward(
    record: dict[str, Any],
    completion_text: str,
    *,
    weights: RewardWeights | None = None,
    default_max_steps: int = 8,
) -> RewardBreakdown:
    """Return the public reward for one generated completion."""

    final_answer, tool_calls = parse_qwen_completion(completion_text)
    return reward_breakdown_for_rollout(
        record,
        final_answer=final_answer,
        tool_calls=tool_calls,
        weights=weights or RewardWeights(),
        default_max_steps=default_max_steps,
    )

def _build_reference_tool_result(
    record: dict[str, Any],
    call: dict[str, Any],
    *,
    available_tools: list[str],
) -> dict[str, Any]:
    """Return a deterministic observation from the teacher trajectory when possible."""

    name = str(call.get("name", ""))
    arguments = dict(call.get("arguments", {}) or {})
    if name in available_tools:
        for ref_call in record.get("tool_calls", []):
            if not isinstance(ref_call, dict):
                continue
            ref_name = str(ref_call.get("name", ""))
            ref_arguments = dict(ref_call.get("arguments", {}) or {})
            if ref_name == name and ref_arguments == arguments:
                result = ref_call.get("result")
                return {"ok": True, "content": json.dumps(result, ensure_ascii=False)}
        return {
            "ok": False,
            "content": f"FrozenToolBackend.missing_fixture:{name}:{json.dumps(arguments, sort_keys=True, ensure_ascii=False)}",
        }
    return {"ok": False, "content": f"FrozenToolBackend.unknown_tool:{name}"}


def run_rollout(
    model: Any,
    tokenizer: Any,
    record: dict[str, Any],
    *,
    max_steps: int,
    max_new_tokens: int,
    temperature: float,
) -> dict[str, Any]:
    """Run one multi-turn rollout against reference trajectory tool results."""

    import torch

    task = record.get("task") or {}
    available_tools = task.get("available_tools", [])
    if not isinstance(available_tools, list):
        available_tools = []
    tools = build_qwen_tools(available_tools) if available_tools else []
    messages: list[dict[str, Any]] = trajectory_to_hf_messages(record)[:2]
    observed_calls: list[dict[str, Any]] = []
    final_answer = ""

    device = next(model.parameters()).device
    for _ in range(max_steps):
        inputs = tokenizer.apply_chat_template(
            messages,
            tools=tools,
            add_generation_prompt=True,
            tokenize=True,
            return_tensors="pt",
        ).to(device)
        with torch.no_grad():
            outputs = model.generate(
                inputs,
                max_new_tokens=max_new_tokens,
                do_sample=temperature > 0.0,
                temperature=temperature if temperature > 0.0 else None,
                pad_token_id=tokenizer.pad_token_id,
                eos_token_id=tokenizer.eos_token_id,
            )
        generated = outputs[0][inputs.shape[-1] :]
        text = tokenizer.decode(generated, skip_special_tokens=False)
        answer, calls = parse_qwen_completion(text)
        if not calls:
            final_answer = answer
            break

        assistant_message: dict[str, Any] = {"role": "assistant", "content": answer}
        tool_call_items: list[dict[str, Any]] = []
        for call in calls:
            tool_call_items.append(
                {
                    "type": "function",
                    "function": {
                        "name": str(call.get("name", "")),
                        "arguments": dict(call.get("arguments", {}) or {}),
                    },
                }
            )
            observed_calls.append(call)
        assistant_message["tool_calls"] = tool_call_items
        messages.append(assistant_message)

        for call in calls:
            result = _build_reference_tool_result(record, call, available_tools=available_tools)
            messages.append({"role": "tool", "content": result["content"]})

        if len(observed_calls) >= 3:
            recent = [str(item.get("name")) for item in observed_calls[-3:]]
            if len(set(recent)) == 1:
                final_answer = ""
                break
    else:
        final_answer = ""

    return {
        "final_answer": final_answer,
        "tool_calls": observed_calls,
        "messages": messages,
    }

def _build_policy_model_and_tokenizer(config: dict[str, Any]):
    """Load a 4-bit base model, optionally attach an SFT adapter, and add LoRA."""

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from peft import LoraConfig, TaskType, get_peft_model, prepare_model_for_kbit_training

    model_cfg = config["model"]
    lora_cfg = config["lora"]
    compute_dtype = {
        "bfloat16": torch.bfloat16,
        "float16": torch.float16,
        "float32": torch.float32,
    }[model_cfg["bnb_4bit_compute_dtype"]]

    tokenizer = AutoTokenizer.from_pretrained(model_cfg["base_model"])
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token

    quantization_config = None
    if model_cfg["load_in_4bit"]:
        quantization_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type=model_cfg["bnb_4bit_quant_type"],
            bnb_4bit_compute_dtype=compute_dtype,
            bnb_4bit_use_double_quant=True,
        )

    model = AutoModelForCausalLM.from_pretrained(
        model_cfg["base_model"],
        quantization_config=quantization_config,
        device_map="auto",
        torch_dtype=compute_dtype,
        attn_implementation=model_cfg["attn_implementation"],
        trust_remote_code=True,
    )

    if model_cfg.get("adapter_path"):
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, model_cfg["adapter_path"], is_trainable=True)
    else:
        model = get_peft_model(
            model,
            LoraConfig(
                task_type=TaskType.CAUSAL_LM,
                inference_mode=False,
                r=int(lora_cfg["r"]),
                lora_alpha=int(lora_cfg["lora_alpha"]),
                lora_dropout=float(lora_cfg["lora_dropout"]),
                target_modules=list(lora_cfg["target_modules"]),
                bias="none",
            ),
        )
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    model.print_trainable_parameters()
    return model, tokenizer

def _minimal_grpo_train(config: dict[str, Any], *, repo_root: Path, config_dir: Path) -> dict[str, Any]:
    """Run a compact REINFORCE-with-group-baseline GRPO-style loop."""

    import torch
    from torch.optim import AdamW

    grpo_cfg = config["grpo"]
    data_path = _resolve_path(config["data"]["path"], config_dir=config_dir, repo_root=repo_root)
    records = load_jsonl(data_path)
    max_records = int(config["data"]["max_records"])
    if max_records > 0:
        records = records[:max_records]
    if not records:
        raise ValueError(f"no GRPO records found in {data_path}")

    model, tokenizer = _build_policy_model_and_tokenizer(config)
    optimizer = AdamW(
        [param for param in model.parameters() if param.requires_grad],
        lr=float(grpo_cfg["learning_rate"]),
        weight_decay=float(grpo_cfg["weight_decay"]),
    )
    model.train()
    weights: RewardWeights = config["reward"]
    max_steps = int(grpo_cfg["max_steps"])
    generations_per_prompt = int(grpo_cfg["generations_per_prompt"])
    batch_size = int(grpo_cfg["batch_size"])
    max_completion_length = int(grpo_cfg["max_completion_length"])
    temperature = float(grpo_cfg["temperature"])
    gradient_accumulation_steps = int(grpo_cfg["gradient_accumulation_steps"])
    num_steps = int(grpo_cfg["num_steps"])
    log_every = int(grpo_cfg["log_every"])
    save_every = int(grpo_cfg["save_every"])
    output_dir = Path(grpo_cfg["output_dir"])
    if not output_dir.is_absolute():
        output_dir = repo_root / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    metrics: list[dict[str, Any]] = []
    for step in range(1, num_steps + 1):
        batch = random.sample(records, min(batch_size, len(records)))
        step_rewards: list[float] = []
        loss_accum = 0.0
        completed_rollouts = 0

        for record in batch:
            model.eval()
            rollouts = [
                run_rollout(
                    model,
                    tokenizer,
                    record,
                    max_steps=max_steps,
                    max_new_tokens=max_completion_length,
                    temperature=temperature,
                )
                for _ in range(generations_per_prompt)
            ]
            model.train()
            breakdowns = [
                reward_breakdown_for_rollout(
                    record,
                    final_answer=rollout["final_answer"],
                    tool_calls=rollout["tool_calls"],
                    weights=weights,
                    default_max_steps=max_steps,
                )
                for rollout in rollouts
            ]
            rewards = [item.reward for item in breakdowns]
            step_rewards.extend(rewards)
            mean = sum(rewards) / len(rewards)
            std = (sum((item - mean) ** 2 for item in rewards) / len(rewards)) ** 0.5 + 1e-6
            advantages = [(item - mean) / std for item in rewards]

            for rollout, advantage in zip(rollouts, advantages):
                messages = rollout["messages"]
                available_tools = (record.get("task") or {}).get("available_tools", [])
                if not isinstance(available_tools, list):
                    available_tools = []
                text = tokenizer.apply_chat_template(
                    messages,
                    tools=build_qwen_tools(available_tools) if available_tools else [],
                    add_generation_prompt=False,
                    tokenize=False,
                )
                tokenized = tokenizer(
                    text,
                    truncation=True,
                    max_length=int(config["model"]["max_sequence_length"]),
                    return_tensors="pt",
                ).to(next(model.parameters()).device)
                labels = tokenized["input_ids"].clone()
                start = max(0, labels.shape[1] - max_completion_length)
                labels[:, :start] = -100
                outputs = model(**tokenized, labels=labels)
                per_token_loss = outputs.loss
                policy_loss = advantage * per_token_loss / gradient_accumulation_steps
                policy_loss.backward()
                loss_accum += float(per_token_loss.detach().cpu().item())
                completed_rollouts += 1

        optimizer.step()
        optimizer.zero_grad(set_to_none=True)

        mean_reward = sum(step_rewards) / len(step_rewards) if step_rewards else 0.0
        metric = {
            "step": step,
            "mean_reward": mean_reward,
            "mean_token_loss": loss_accum / completed_rollouts if completed_rollouts else 0.0,
        }
        metrics.append(metric)
        if step % log_every == 0:
            print(json.dumps(metric, ensure_ascii=False))
        if save_every > 0 and step % save_every == 0:
            checkpoint_dir = output_dir / f"checkpoint-{step}"
            model.save_pretrained(checkpoint_dir)
            tokenizer.save_pretrained(checkpoint_dir)

    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)
    summary = {
        "schema_version": "klara.qwen-grpo.v1",
        "experiment": config["experiment"]["name"],
        "trainer": "minimal-grpo",
        "steps": num_steps,
        "output_dir": str(output_dir),
        "final_mean_reward": metrics[-1]["mean_reward"] if metrics else 0.0,
        "metrics": metrics,
    }
    output_dir.joinpath("run_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary

def _try_trl_train(config: dict[str, Any], *, repo_root: Path, config_dir: Path) -> dict[str, Any]:
    """Best-effort TRL GRPO path.

    TRL's API changes across releases, so this function is intentionally narrow
    and raises an informative error when the installed version does not match
    the expected ``GRPOTrainer`` surface.
    """

    from datasets import Dataset
    from trl import GRPOConfig, GRPOTrainer

    model, tokenizer = _build_policy_model_and_tokenizer(config)
    data_path = _resolve_path(config["data"]["path"], config_dir=config_dir, repo_root=repo_root)
    records = load_jsonl(data_path)
    max_records = int(config["data"]["max_records"])
    if max_records > 0:
        records = records[:max_records]

    dataset = Dataset.from_list(
        [
            {
                "prompt": tokenizer.apply_chat_template(
                    trajectory_to_hf_messages(record)[:2],
                    tools=build_qwen_tools((record.get("task") or {}).get("available_tools", [])),
                    add_generation_prompt=True,
                    tokenize=False,
                ),
                "reference": json.dumps(record, ensure_ascii=False),
            }
            for record in records
        ]
    )

    def reward_func(completions: list[str], **kwargs: Any) -> list[float]:
        del kwargs
        return [
            klara_reward(
                json.loads(reference),
                completion,
                weights=config["reward"],
                default_max_steps=int(config["grpo"]["max_steps"]),
            ).reward
            for completion, reference in zip(completions, dataset["reference"])
        ]

    grpo_cfg = config["grpo"]
    output_dir = Path(grpo_cfg["output_dir"])
    if not output_dir.is_absolute():
        output_dir = repo_root / output_dir

    training_args = GRPOConfig(
        output_dir=str(output_dir),
        per_device_train_batch_size=1,
        gradient_accumulation_steps=int(grpo_cfg["gradient_accumulation_steps"]),
        learning_rate=float(grpo_cfg["learning_rate"]),
        logging_steps=1,
        max_steps=int(grpo_cfg["num_steps"]),
        num_generations=int(grpo_cfg["generations_per_prompt"]),
        max_completion_length=int(grpo_cfg["max_completion_length"]),
        temperature=float(grpo_cfg["temperature"]),
        bf16=bool(grpo_cfg["bf16"]),
        report_to=[],
        seed=int(grpo_cfg["seed"]),
    )
    trainer = GRPOTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        reward_funcs=reward_func,
    )
    trainer.train()
    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)
    return {
        "schema_version": "klara.qwen-grpo.v1",
        "experiment": config["experiment"]["name"],
        "trainer": "trl-grpo",
        "output_dir": str(output_dir),
    }


def train(
    config_path: str | Path,
    *,
    model_override: str | None = None,
    output_dir_override: str | Path | None = None,
    force_minimal: bool = False,
) -> dict[str, Any]:
    """Run GRPO, preferring TRL when configured and available."""

    config_path = Path(config_path).resolve()
    config = validate_config(config_path)
    if model_override:
        config["model"]["base_model"] = model_override
    if output_dir_override is not None:
        config["grpo"]["output_dir"] = str(output_dir_override)

    repo_root = Path(__file__).resolve().parents[3]
    config_dir = config_path.parent

    if bool(config["grpo"]["use_trl"]) and not force_minimal:
        try:
            return _try_trl_train(config, repo_root=repo_root, config_dir=config_dir)
        except Exception as exc:
            print(
                f"TRL GRPO unavailable, falling back to minimal GRPO loop: {type(exc).__name__}: {exc}"
            )
    return _minimal_grpo_train(config, repo_root=repo_root, config_dir=config_dir)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate-config", help="validate qwen_grpo.toml")
    validate.add_argument("--config", required=True)

    train_parser = subparsers.add_parser("train", help="run GRPO")
    train_parser.add_argument("--config", required=True)
    train_parser.add_argument("--model", default=None)
    train_parser.add_argument("--output-dir", default=None)
    train_parser.add_argument("--force-minimal", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "validate-config":
        normalized = validate_config(args.config)
        print(json.dumps(normalized, ensure_ascii=False, indent=2, default=str))
        return 0
    if args.command == "train":
        summary = train(
            args.config,
            model_override=args.model,
            output_dir_override=args.output_dir,
            force_minimal=args.force_minimal,
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        return 0
    raise AssertionError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())

# Public aliases used by the package-level lazy exports.
validate_grpo_config = validate_config
train_grpo = train
