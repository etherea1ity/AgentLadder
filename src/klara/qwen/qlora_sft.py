"""Qwen2.5-1.5B-Instruct QLoRA SFT entry points.

This module intentionally keeps heavy training dependencies (``torch``,
``transformers``, ``peft``, ``bitsandbytes``) inside functions so the module can
be imported and its TOML configuration validated on a CPU-only machine that has
not installed the optional training stack.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path
from typing import Any
import tomllib

DEFAULT_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"
DEFAULT_LORA_TARGET_MODULES = [
    "q_proj",
    "k_proj",
    "v_proj",
    "o_proj",
    "gate_proj",
    "up_proj",
    "down_proj",
]

# Frozen-tool schema used by the teacher trajectories. Keeping these schemas in
# one place makes the Qwen prompt align with the Klara three-way eval contract.
QWEN_TOOL_SPECS: dict[str, dict[str, Any]] = {
    "web_search": {
        "description": (
            "Search the public web and return candidate result cards as public "
            "links with titles, URLs, snippets, provider, and searched_at metadata."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "allowed_domains": {"type": "array", "items": {"type": "string"}},
                "blocked_domains": {"type": "array", "items": {"type": "string"}},
                "count": {"type": "integer", "minimum": 1, "maximum": 20},
                "freshness": {
                    "type": "string",
                    "enum": ["day", "week", "month", "year", "any"],
                },
                "language": {"type": "string"},
                "country": {"type": "string"},
                "search_depth": {"type": "string", "enum": ["basic", "advanced"]},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    "web_fetch": {
        "description": (
            "Fetch one public HTTP(S) page and return readable text, final URL, "
            "status, content type, title, and truncation metadata."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "candidate_id": {"type": "string"},
                "source_id": {"type": "string"},
                "max_chars": {"type": "integer", "minimum": 200, "maximum": 12000},
                "query_terms": {"type": "array", "items": {"type": "string"}},
                "extract_mode": {
                    "type": "string",
                    "enum": ["plain", "relevant_snippets", "summary_snippets"],
                },
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    },
    "memory_search": {
        "description": (
            "Search only this user's durable memory and return provenance-aware "
            "results."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "mode": {
                    "type": "string",
                    "enum": [
                        "hybrid",
                        "lexical",
                        "vector",
                        "recent",
                        "full_context",
                        "semantic_recency",
                        "mem0_compatible",
                    ],
                },
                "at_time": {"type": "string", "format": "date-time"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    "current_time": {
        "description": (
            "Return exact current wall-clock date, time, weekday, and UTC offset "
            "for a requested timezone."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"timezone": {"type": "string"}},
            "required": [],
            "additionalProperties": False,
        },
    },
    "evidence_submit": {
        "description": (
            "Submit a web-backed proposed answer, material claims, exact fetched-source "
            "links, citations, or an explicit abstention for runtime verification."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "final_text": {"type": "string"},
                "claims": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "claim_id": {"type": "string"},
                            "text": {"type": "string"},
                            "required": {"type": "boolean"},
                        },
                        "required": ["claim_id", "text"],
                        "additionalProperties": False,
                    },
                },
                "links": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "claim_id": {"type": "string"},
                            "source_id": {"type": "string"},
                            "judgment": {
                                "type": "string",
                                "enum": ["supported", "contradicted", "insufficient"],
                            },
                            "support_note": {"type": "string"},
                        },
                        "required": ["claim_id", "source_id", "judgment", "support_note"],
                        "additionalProperties": False,
                    },
                },
                "citations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "claim_id": {"type": "string"},
                            "source_id": {"type": "string"},
                        },
                        "required": ["claim_id", "source_id"],
                        "additionalProperties": False,
                    },
                },
                "abstain": {"type": "boolean"},
                "abstention_reason": {"type": "string"},
            },
            "required": ["final_text", "claims", "links", "citations", "abstain"],
            "additionalProperties": False,
        },
    },
    "update_activity": {
        "description": (
            "Append Klara's public thinking update for the current step. "
            "This is not the final answer."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
    },
    "skills_list": {
        "description": "List available procedural Skills as metadata.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "skill_view": {
        "description": "Load one relevant Skill body or declared reference on demand.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "reference": {"type": "string"},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
}


def build_qwen_tools(available_tools: list[str] | tuple[str, ...]) -> list[dict[str, Any]]:
    """Build Qwen-style tool declarations from frozen tool names."""

    tools: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name in available_tools:
        name = str(name)
        if name in seen:
            continue
        seen.add(name)
        spec = QWEN_TOOL_SPECS.get(name)
        if spec is None:
            # Unknown tools in new data should not be silently dropped.
            raise KeyError(f"unknown frozen tool: {name}")
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": spec["description"],
                    "parameters": spec["input_schema"],
                },
            }
        )
    return tools


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Load JSONL trajectories and fail closed on malformed lines."""

    data: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"trajectory record must be an object: {path}:{line_number}")
            data.append(value)
    return data


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
    """Validate ``qwen_qlora.toml`` and return normalized settings."""

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
    train = _expect_dict(raw, "train", path="config")

    seed = _expect_int(train, "seed", default=20260816, minimum=0, path="config.train")
    base_model = _expect_str(
        model, "base_model", default=DEFAULT_MODEL, path="config.model"
    )
    max_sequence_length = _expect_int(
        model, "max_sequence_length", default=1024, minimum=1, path="config.model"
    )
    load_in_4bit = _expect_bool(
        model, "load_in_4bit", default=True, path="config.model"
    )
    bnb_4bit_quant_type = _expect_str(
        model, "bnb_4bit_quant_type", default="nf4", path="config.model"
    )
    if bnb_4bit_quant_type not in {"nf4", "fp4"}:
        raise ValueError("config.model.bnb_4bit_quant_type must be nf4 or fp4")
    bnb_4bit_compute_dtype = _expect_str(
        model, "bnb_4bit_compute_dtype", default="bfloat16", path="config.model"
    )
    if bnb_4bit_compute_dtype not in {"bfloat16", "float16", "float32"}:
        raise ValueError(
            "config.model.bnb_4bit_compute_dtype must be bfloat16, float16, or float32"
        )
    attn_implementation = _expect_str(
        model, "attn_implementation", default="sdpa", path="config.model"
    )

    target_modules = lora.get("target_modules", DEFAULT_LORA_TARGET_MODULES)
    if not isinstance(target_modules, list) or not target_modules:
        raise ValueError("config.lora.target_modules must be a non-empty list")
    if not all(isinstance(item, str) and item.strip() for item in target_modules):
        raise ValueError("config.lora.target_modules must contain strings")
    target_modules = [str(item).strip() for item in target_modules]

    r = _expect_int(lora, "r", default=16, minimum=1, path="config.lora")
    lora_alpha = _expect_int(
        lora, "lora_alpha", default=32, minimum=1, path="config.lora"
    )
    lora_dropout = _expect_float(
        lora, "lora_dropout", default=0.05, minimum=0.0, path="config.lora"
    )

    data_path = _expect_str(
        data, "path", default="data/trajectories/clean.jsonl", path="config.data"
    )
    max_records = _expect_int(
        data, "max_records", default=0, minimum=0, path="config.data"
    )
    val_split = _expect_float(
        data, "val_split", default=0.05, minimum=0.0, path="config.data"
    )
    if val_split >= 1.0:
        raise ValueError("config.data.val_split must be < 1.0")

    output_dir = _expect_str(
        train, "output_dir", default="artifacts/qwen-qlora-sft", path="config.train"
    )
    num_train_epochs = _expect_float(
        train, "num_train_epochs", default=3.0, minimum=0.0, path="config.train"
    )
    per_device_train_batch_size = _expect_int(
        train,
        "per_device_train_batch_size",
        default=1,
        minimum=1,
        path="config.train",
    )
    per_device_eval_batch_size = _expect_int(
        train,
        "per_device_eval_batch_size",
        default=1,
        minimum=1,
        path="config.train",
    )
    gradient_accumulation_steps = _expect_int(
        train,
        "gradient_accumulation_steps",
        default=8,
        minimum=1,
        path="config.train",
    )
    learning_rate = _expect_float(
        train, "learning_rate", default=2e-4, minimum=0.0, path="config.train"
    )
    warmup_ratio = _expect_float(
        train, "warmup_ratio", default=0.03, minimum=0.0, path="config.train"
    )
    weight_decay = _expect_float(
        train, "weight_decay", default=0.0, minimum=0.0, path="config.train"
    )
    gradient_clipping = _expect_float(
        train, "gradient_clipping", default=1.0, minimum=0.0, path="config.train"
    )
    logging_steps = _expect_int(
        train, "logging_steps", default=10, minimum=1, path="config.train"
    )
    save_steps = _expect_int(
        train, "save_steps", default=200, minimum=1, path="config.train"
    )
    eval_steps = _expect_int(
        train, "eval_steps", default=200, minimum=1, path="config.train"
    )
    save_total_limit = _expect_int(
        train, "save_total_limit", default=3, minimum=0, path="config.train"
    )
    bf16 = _expect_bool(train, "bf16", default=True, path="config.train")
    gradient_checkpointing = _expect_bool(
        train, "gradient_checkpointing", default=True, path="config.train"
    )
    dataloader_num_workers = _expect_int(
        train, "dataloader_num_workers", default=0, minimum=0, path="config.train"
    )
    resume_from_checkpoint = _expect_str(
        train, "resume_from_checkpoint", default="", path="config.train"
    )

    return {
        "experiment": {
            "name": _expect_str(
                experiment, "name", default="qwen-qlora-sft", path="config.experiment"
            ),
        },
        "model": {
            "base_model": base_model,
            "max_sequence_length": max_sequence_length,
            "load_in_4bit": load_in_4bit,
            "bnb_4bit_quant_type": bnb_4bit_quant_type,
            "bnb_4bit_compute_dtype": bnb_4bit_compute_dtype,
            "attn_implementation": attn_implementation,
        },
        "lora": {
            "r": r,
            "lora_alpha": lora_alpha,
            "lora_dropout": lora_dropout,
            "target_modules": target_modules,
        },
        "data": {
            "path": data_path,
            "max_records": max_records,
            "val_split": val_split,
        },
        "train": {
            "seed": seed,
            "output_dir": output_dir,
            "num_train_epochs": num_train_epochs,
            "per_device_train_batch_size": per_device_train_batch_size,
            "per_device_eval_batch_size": per_device_eval_batch_size,
            "gradient_accumulation_steps": gradient_accumulation_steps,
            "learning_rate": learning_rate,
            "warmup_ratio": warmup_ratio,
            "weight_decay": weight_decay,
            "gradient_clipping": gradient_clipping,
            "logging_steps": logging_steps,
            "save_steps": save_steps,
            "eval_steps": eval_steps,
            "save_total_limit": save_total_limit,
            "bf16": bf16,
            "gradient_checkpointing": gradient_checkpointing,
            "dataloader_num_workers": dataloader_num_workers,
            "resume_from_checkpoint": resume_from_checkpoint,
        },
    }


def _resolve_path(value: str, *, config_dir: Path, repo_root: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    if (config_dir / path).exists():
        return config_dir / path
    return repo_root / path


def trajectory_to_hf_messages(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert one clean trajectory into HF/Qwen chat-template messages."""

    raw_messages = record.get("messages")
    if not isinstance(raw_messages, list):
        raise ValueError("trajectory record requires a messages list")

    messages: list[dict[str, Any]] = []
    for raw in raw_messages:
        if not isinstance(raw, dict):
            raise ValueError("trajectory message must be an object")
        role = raw.get("role")
        content = raw.get("content", "")
        if role == "assistant":
            item: dict[str, Any] = {"role": "assistant", "content": str(content or "")}
            tool_calls: list[dict[str, Any]] = []
            for call in raw.get("tool_calls", []):
                if not isinstance(call, dict):
                    continue
                function = call.get("function", call)
                arguments = function.get("arguments", {}) if isinstance(function, dict) else {}
                if isinstance(arguments, str):
                    arguments = json.loads(arguments) if arguments.strip() else {}
                tool_calls.append(
                    {
                        "type": "function",
                        "function": {
                            "name": str(function.get("name", "")) if isinstance(function, dict) else "",
                            "arguments": arguments,
                        },
                    }
                )
            if tool_calls:
                item["tool_calls"] = tool_calls
            messages.append(item)
        elif role == "tool":
            messages.append(
                {
                    "role": "tool",
                    "content": str(content or ""),
                }
            )
        elif role in {"system", "user"}:
            messages.append({"role": str(role), "content": str(content or "")})
        else:
            raise ValueError(f"unsupported trajectory message role: {role}")
    return messages


def tokenize_example(
    record: dict[str, Any],
    tokenizer: Any,
    *,
    max_length: int,
) -> dict[str, Any]:
    """Tokenize one SFT example using Qwen's native chat template."""

    messages = trajectory_to_hf_messages(record)
    task = record.get("task") or {}
    available_tools = task.get("available_tools", [])
    if not isinstance(available_tools, list):
        available_tools = []
    tools = build_qwen_tools(available_tools) if available_tools else None

    text = tokenizer.apply_chat_template(
        messages,
        tools=tools,
        add_generation_prompt=False,
        tokenize=False,
    )
    tokenized = tokenizer(
        text,
        truncation=True,
        max_length=max_length,
        padding=False,
        return_tensors=None,
    )
    input_ids = tokenized["input_ids"]
    return {
        "input_ids": input_ids,
        "labels": _assistant_only_labels(input_ids, tokenizer),
    }


def _assistant_only_labels(input_ids: list[int], tokenizer: Any) -> list[int]:
    """Mask every token except assistant content so only assistant CE loss remains.

    Qwen renders assistant tool calls and final answers inside
    ``<|im_start|>assistant`` ... ``<|im_end|>``.  Everything else (system,
    user, and tool responses) is set to ``-100``.  The marker tokens themselves
    are also masked; only the assistant payload contributes loss.
    """

    start_marker = tokenizer.encode(
        "<|im_start|>assistant\n", add_special_tokens=False
    )
    end_marker = tokenizer.encode("<|im_end|>", add_special_tokens=False)
    labels = [-100] * len(input_ids)
    start_len = len(start_marker)
    end_len = len(end_marker)
    n = len(input_ids)

    index = 0
    while index < n:
        if input_ids[index : index + start_len] == start_marker:
            body_start = index + start_len
            cursor = body_start
            while cursor < n and input_ids[cursor : cursor + end_len] != end_marker:
                cursor += 1
            for position in range(body_start, min(cursor, n)):
                labels[position] = input_ids[position]
            index = cursor + end_len if cursor < n else n
        else:
            index += 1
    return labels


def load_training_examples(
    config: dict[str, Any],
    *,
    repo_root: Path,
    config_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Load and deterministically split clean trajectory records."""

    data_path = _resolve_path(
        config["data"]["path"],
        config_dir=config_dir,
        repo_root=repo_root,
    )
    records = load_jsonl(data_path)
    max_records = int(config["data"]["max_records"])
    if max_records > 0:
        records = records[:max_records]
    if not records:
        raise ValueError(f"no SFT records found in {data_path}")

    val_split = float(config["data"]["val_split"])
    random.seed(int(config["train"]["seed"]))
    indices = list(range(len(records)))
    random.shuffle(indices)
    val_count = int(round(len(indices) * val_split)) if val_split else 0
    if val_count >= len(indices):
        val_count = max(0, len(indices) - 1)
    train_indices = sorted(indices[val_count:])
    val_indices = sorted(indices[:val_count])
    return [records[index] for index in train_indices], [records[index] for index in val_indices]


class _TorchSftDataset:
    """Small map-style dataset used when ``datasets`` is not available."""

    def __init__(self, records: list[dict[str, Any]], tokenizer: Any, max_length: int):
        self.records = records
        self.tokenizer = tokenizer
        self.max_length = max_length

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, index: int) -> dict[str, Any]:
        return tokenize_example(
            self.records[index],
            self.tokenizer,
            max_length=self.max_length,
        )


def train(
    config_path: str | Path,
    *,
    model_override: str | None = None,
    output_dir_override: str | Path | None = None,
    resume_from_checkpoint_override: str | None = None,
) -> dict[str, Any]:
    """Run QLoRA SFT.

    This function loads model weights only when invoked, so local config/import
    smoke tests never download or allocate ``Qwen2.5-1.5B-Instruct``.
    """

    config_path = Path(config_path).resolve()
    config = validate_config(config_path)
    repo_root = Path(__file__).resolve().parents[3]
    config_dir = config_path.parent

    try:
        import torch  # noqa: F401
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            BitsAndBytesConfig,
            DataCollatorForLanguageModeling,
            Trainer,
            TrainingArguments,
        )
        from peft import LoraConfig, TaskType, get_peft_model, prepare_model_for_kbit_training
    except Exception as exc:  # pragma: no cover - depends on remote environment
        raise RuntimeError(
            "QLoRA SFT requires torch, transformers, peft, and bitsandbytes. "
            "Install them in the HKU environment before training."
        ) from exc

    model_name = model_override or config["model"]["base_model"]
    max_length = int(config["model"]["max_sequence_length"])
    train_cfg = config["train"]
    lora_cfg = config["lora"]
    model_cfg = config["model"]

    torch.manual_seed(int(train_cfg["seed"]))

    compute_dtype = {
        "bfloat16": torch.bfloat16,
        "float16": torch.float16,
        "float32": torch.float32,
    }[model_cfg["bnb_4bit_compute_dtype"]]
    quantization_config = None
    if model_cfg["load_in_4bit"]:
        quantization_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type=model_cfg["bnb_4bit_quant_type"],
            bnb_4bit_compute_dtype=compute_dtype,
            bnb_4bit_use_double_quant=True,
        )

    tokenizer = AutoTokenizer.from_pretrained(model_name)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        quantization_config=quantization_config,
        device_map="auto",
        torch_dtype=compute_dtype,
        attn_implementation=model_cfg["attn_implementation"],
        trust_remote_code=True,
    )
    model = prepare_model_for_kbit_training(
        model,
        use_gradient_checkpointing=bool(train_cfg["gradient_checkpointing"]),
    )
    lora_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        inference_mode=False,
        r=int(lora_cfg["r"]),
        lora_alpha=int(lora_cfg["lora_alpha"]),
        lora_dropout=float(lora_cfg["lora_dropout"]),
        target_modules=list(lora_cfg["target_modules"]),
        bias="none",
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    train_records, val_records = load_training_examples(
        config,
        repo_root=repo_root,
        config_dir=config_dir,
    )
    train_dataset = _TorchSftDataset(train_records, tokenizer, max_length)
    val_dataset = _TorchSftDataset(val_records, tokenizer, max_length) if val_records else None

    output_dir = Path(output_dir_override or train_cfg["output_dir"])
    if not output_dir.is_absolute():
        output_dir = repo_root / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    training_args = TrainingArguments(
        output_dir=str(output_dir),
        num_train_epochs=float(train_cfg["num_train_epochs"]),
        per_device_train_batch_size=int(train_cfg["per_device_train_batch_size"]),
        per_device_eval_batch_size=int(train_cfg["per_device_eval_batch_size"]),
        gradient_accumulation_steps=int(train_cfg["gradient_accumulation_steps"]),
        learning_rate=float(train_cfg["learning_rate"]),
        weight_decay=float(train_cfg["weight_decay"]),
        max_grad_norm=float(train_cfg["gradient_clipping"]),
        logging_steps=int(train_cfg["logging_steps"]),
        save_steps=int(train_cfg["save_steps"]),
        eval_steps=int(train_cfg["eval_steps"]),
        save_total_limit=int(train_cfg["save_total_limit"]),
        bf16=bool(train_cfg["bf16"]),
        gradient_checkpointing=bool(train_cfg["gradient_checkpointing"]),
        dataloader_num_workers=int(train_cfg["dataloader_num_workers"]),
        remove_unused_columns=False,
        report_to=[],
        seed=int(train_cfg["seed"]),
        run_name=config["experiment"]["name"],
    )

    data_collator = DataCollatorForLanguageModeling(tokenizer=tokenizer, mlm=False)
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        data_collator=data_collator,
    )

    resume = resume_from_checkpoint_override
    if resume is None and train_cfg["resume_from_checkpoint"]:
        resume = train_cfg["resume_from_checkpoint"]
    train_result = trainer.train(resume_from_checkpoint=resume or None)
    trainer.save_model()
    tokenizer.save_pretrained(output_dir)

    summary = {
        "schema_version": "klara.qwen-qlora-sft.v1",
        "experiment": config["experiment"]["name"],
        "base_model": model_name,
        "output_dir": str(output_dir),
        "train_records": len(train_records),
        "val_records": len(val_records),
        "metrics": {
            "train_loss": getattr(train_result, "training_loss", None),
            "train_runtime_seconds": train_result.metrics.get("train_runtime")
            if getattr(train_result, "metrics", None) is not None
            else None,
        },
    }
    output_dir.joinpath("run_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate-config", help="validate qwen_qlora.toml")
    validate.add_argument("--config", required=True)

    train_parser = subparsers.add_parser("train", help="run QLoRA SFT")
    train_parser.add_argument("--config", required=True)
    train_parser.add_argument("--model", default=None)
    train_parser.add_argument("--output-dir", default=None)
    train_parser.add_argument("--resume-from-checkpoint", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "validate-config":
        normalized = validate_config(args.config)
        print(json.dumps(normalized, ensure_ascii=False, indent=2))
        return 0
    if args.command == "train":
        summary = train(
            args.config,
            model_override=args.model,
            output_dir_override=args.output_dir,
            resume_from_checkpoint_override=args.resume_from_checkpoint,
        )
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    raise AssertionError(f"unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())

# Public aliases used by the package-level lazy exports.
validate_qlora_config = validate_config
train_qlora_sft = train
