"""SFT training for the Klara four-expert top-2 sparse MoE model.

The trainer consumes teacher-rollout JSONL trajectories and converts the
OpenAI-style message list into a ChatML-like byte-BPE sequence.  It performs
full-parameter supervised next-token training with bf16/fp16 AMP, AdamW,
warmup+cosine scheduling, and atomic resume checkpoints.  It can also start
from a MoE pretraining checkpoint without loading pretraining optimizer state.
"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, field
import json
import math
from pathlib import Path
from typing import Any, Iterator

import torch
from torch import nn
from torch.optim import AdamW
from torch.optim.lr_scheduler import LambdaLR
from torch.utils.data import DataLoader, Dataset

from klara.training.checkpoint import file_sha256
from klara.training.config import ModelConfig
from klara.training.moe import MoEConfig
from klara.training.model import TinyDecoderLM
from klara.training.trainer import model_state_sha256, resolve_device, seed_everything

SFT_CHECKPOINT_FORMAT = "klara.moe-sft.checkpoint.v1"
SFT_LOG_SCHEMA = "klara.moe-sft.log.v1"
IGNORE_INDEX = -100


@dataclass(frozen=True)
class SFTConfig:
    """Optimization contract for full-parameter trajectory SFT."""

    seed: int = 20260816
    steps: int = 2000
    batch_size: int = 4
    gradient_accumulation_steps: int = 8
    learning_rate: float = 2e-5
    weight_decay: float = 0.01
    gradient_clip: float = 1.0
    precision: str = "bf16"
    device: str = "auto"
    warmup_steps: int = 100
    cosine_min_lr: float = 0.0
    val_every: int = 50
    log_every: int = 10
    checkpoint_every: int = 500
    loader_workers: int = 0
    val_ratio: float = 0.01

    def __post_init__(self) -> None:
        if self.steps < 1 or self.batch_size < 1:
            raise ValueError("steps and batch_size must be positive")
        if self.gradient_accumulation_steps < 1:
            raise ValueError("gradient_accumulation_steps must be positive")
        if self.learning_rate <= 0 or self.gradient_clip <= 0:
            raise ValueError("learning_rate and gradient_clip must be positive")
        if self.cosine_min_lr < 0 or self.cosine_min_lr > self.learning_rate:
            raise ValueError("cosine_min_lr must be in [0, learning_rate]")
        if self.precision not in {"fp32", "fp16", "bf16"}:
            raise ValueError("precision must be fp32, fp16, or bf16")
        if self.device not in {"auto", "cpu", "cuda"}:
            raise ValueError("device must be auto, cpu, or cuda")
        if self.loader_workers != 0:
            raise ValueError("reproducible Windows training uses zero loader workers")
        if not 0.0 <= self.val_ratio < 1.0:
            raise ValueError("val_ratio must be in [0, 1)")
        if self.warmup_steps < 0:
            raise ValueError("warmup_steps must be non-negative")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SFTConfig":
        return cls(**raw)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "steps": self.steps,
            "batch_size": self.batch_size,
            "gradient_accumulation_steps": self.gradient_accumulation_steps,
            "learning_rate": self.learning_rate,
            "weight_decay": self.weight_decay,
            "gradient_clip": self.gradient_clip,
            "precision": self.precision,
            "device": self.device,
            "warmup_steps": self.warmup_steps,
            "cosine_min_lr": self.cosine_min_lr,
            "val_every": self.val_every,
            "log_every": self.log_every,
            "checkpoint_every": self.checkpoint_every,
            "loader_workers": self.loader_workers,
            "val_ratio": self.val_ratio,
        }


@dataclass(frozen=True)
class SFTBatch:
    """One padded causal batch for trajectory SFT."""

    input_ids: torch.Tensor
    labels: torch.Tensor

    def to(self, device: torch.device) -> "SFTBatch":
        return SFTBatch(
            input_ids=self.input_ids.to(device),
            labels=self.labels.to(device),
        )


@dataclass(frozen=True)
class SFTResult:
    """Measured result from one trajectory SFT run."""

    initial_val_loss: float
    final_val_loss: float
    loss_reduction_fraction: float
    final_train_loss: float
    gradients_finite: bool
    parameter_count: int
    final_step: int
    device: str
    precision: str
    logs: tuple[dict[str, Any], ...]
    model_state_sha256: str
    final_checkpoint_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "initial_val_loss": self.initial_val_loss,
            "final_val_loss": self.final_val_loss,
            "loss_reduction_fraction": self.loss_reduction_fraction,
            "final_train_loss": self.final_train_loss,
            "gradients_finite": self.gradients_finite,
            "parameter_count": self.parameter_count,
            "final_step": self.final_step,
            "device": self.device,
            "precision": self.precision,
            "logs": list(self.logs),
            "model_state_sha256": self.model_state_sha256,
            "final_checkpoint_sha256": self.final_checkpoint_sha256,
        }


def _amp_context(
    device: torch.device,
    precision: str,
) -> tuple[Any, torch.amp.GradScaler, str]:
    """Return autocast context, scaler, and effective precision."""
    if device.type != "cuda":
        return nullcontext(), torch.amp.GradScaler("cuda", enabled=False), "fp32"
    if precision == "bf16" and not torch.cuda.is_bf16_supported():
        return nullcontext(), torch.amp.GradScaler("cuda", enabled=False), "fp32"
    if precision in {"fp16", "bf16"}:
        dtype = torch.bfloat16 if precision == "bf16" else torch.float16
        return (
            torch.autocast("cuda", dtype=dtype),
            torch.amp.GradScaler("cuda", enabled=True),
            precision,
        )
    return nullcontext(), torch.amp.GradScaler("cuda", enabled=False), "fp32"


def count_parameters(model: nn.Module) -> int:
    """Count every parameter in a model."""
    return sum(parameter.numel() for parameter in model.parameters())


def _json_compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parse_arguments_text(arguments_text: Any) -> dict[str, Any]:
    """Parse OpenAI-style tool-call arguments into a JSON object."""
    if isinstance(arguments_text, dict):
        return arguments_text
    try:
        parsed = json.loads(arguments_text or "{}")
    except (json.JSONDecodeError, TypeError):
        parsed = {}
    if not isinstance(parsed, dict):
        return {}
    return parsed


def render_message(message: dict[str, Any]) -> str:
    """Render one OpenAI-style message as a compact ChatML-like string."""
    return "".join(
        text for text, _trainable in _render_message_parts(message)
    )


def _render_message_parts(
    message: dict[str, Any],
) -> list[tuple[str, bool]]:
    """Render one message and mark which target tokens should be trained.

    The boolean on each rendered segment means ``True`` when predicting those
    tokens should contribute to SFT cross-entropy.  Only assistant tool-call
    blocks and assistant final-answer content are trainable; the ChatML role
    markers, the system/user/tool-result bodies, and the end marker are masked.
    """

    role = str(message.get("role", "")).strip()
    content = str(message.get("content") or "")
    parts: list[tuple[str, bool]] = []
    parts.append((f"<|im_start|>{role}\n", False))
    tool_calls = message.get("tool_calls") or []
    trainable_body = role == "assistant"
    for call in tool_calls:
        function = call.get("function") or call
        name = str(function.get("name", ""))
        arguments = _parse_arguments_text(function.get("arguments", "{}"))
        parts.append(("<tool_call>", trainable_body))
        parts.append(
            (_json_compact({"name": name, "arguments": arguments}), trainable_body)
        )
        parts.append(("</tool_call>\n", trainable_body))
    if content:
        parts.append((content.rstrip() + "\n", trainable_body))
    parts.append(("<|im_end|>\n", False))
    return parts


def render_trajectory(record: dict[str, Any]) -> str:
    """Render a clean.jsonl teacher trajectory into one training string."""
    messages = record.get("messages")
    if not isinstance(messages, list) or not messages:
        raise ValueError("trajectory must contain a messages list")
    return "".join(render_message(message) for message in messages if isinstance(message, dict))


def load_trajectories(path: str | Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    """Load JSONL trajectories in file order."""
    path = Path(path)
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="\n") as handle:
        for line in handle:
            if not line.strip():
                continue
            records.append(json.loads(line))
            if limit is not None and len(records) >= limit:
                break
    if not records:
        raise ValueError(f"no trajectories found in {path}")
    return records


def _fixed_sequence(
    tokens: list[int],
    sequence_length: int,
    pad_token_id: int,
    *,
    trainable_targets: list[bool] | None = None,
) -> tuple[list[int], list[int]] | None:
    """Turn token IDs into fixed-length causal input/label rows.

    ``trainable_targets`` must have one entry per token.  Position ``i`` in the
    output labels predicts token ``i + 1``, so it is kept only when the target
    token is marked trainable; every other position receives ``IGNORE_INDEX``.
    """

    if len(tokens) < 2:
        return None
    if trainable_targets is not None and len(trainable_targets) != len(tokens):
        raise ValueError("trainable_targets must have exactly one flag per token")
    target_flags = (
        [True] * len(tokens)
        if trainable_targets is None
        else list(trainable_targets)
    )
    inputs = tokens[:-1][:sequence_length]
    target_tokens = tokens[1:][:sequence_length]
    target_flags = target_flags[1:][:sequence_length]
    if not inputs:
        return None
    input_ids = inputs + [pad_token_id] * (sequence_length - len(inputs))
    label_ids = [
        token if flag else IGNORE_INDEX
        for token, flag in zip(target_tokens, target_flags)
    ]
    label_ids = label_ids + [IGNORE_INDEX] * (sequence_length - len(label_ids))
    return input_ids, label_ids


class SFTDataset(Dataset):
    """In-memory fixed-length causal dataset for trajectory SFT."""

    def __init__(
        self,
        rows: list[tuple[list[int], list[int]]],
    ) -> None:
        self.rows = rows

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, index: int) -> SFTBatch:
        input_ids, labels = self.rows[index]
        return SFTBatch(
            input_ids=torch.tensor(input_ids, dtype=torch.long),
            labels=torch.tensor(labels, dtype=torch.long),
        )


def _collate_sft(batches: list[SFTBatch]) -> SFTBatch:
    return SFTBatch(
        input_ids=torch.stack([batch.input_ids for batch in batches]),
        labels=torch.stack([batch.labels for batch in batches]),
    )


def build_sft_rows(
    records: list[dict[str, Any]],
    tokenizer: Any,
    *,
    sequence_length: int,
    pad_token_id: int,
) -> list[tuple[list[int], list[int]]]:
    """Tokenize trajectories into fixed-length causal rows with role masking.

    Only assistant tool-call tokens and assistant final-answer tokens are
    labeled.  System, user, and tool-result positions receive ``IGNORE_INDEX``
    so they cannot contribute to the SFT cross-entropy objective.
    """

    rows: list[tuple[list[int], list[int]]] = []
    for record in records:
        messages = record.get("messages")
        if not isinstance(messages, list) or not messages:
            continue
        token_pieces: list[list[int]] = []
        target_flags: list[bool] = []
        for message in messages:
            if not isinstance(message, dict):
                continue
            for text, is_trainable in _render_message_parts(message):
                piece_tokens = tokenizer.encode(
                    text,
                    add_bos=False,
                    add_eos=False,
                )
                token_pieces.append(piece_tokens)
                target_flags.extend([is_trainable] * len(piece_tokens))
        if not token_pieces:
            continue
        tokens = [tokenizer.bos_token_id]
        for piece_tokens in token_pieces:
            tokens.extend(piece_tokens)
        tokens.append(tokenizer.eos_token_id)
        target_flags = [False] + target_flags + [False]
        row = _fixed_sequence(
            tokens,
            sequence_length,
            pad_token_id,
            trainable_targets=target_flags,
        )
        if row is not None:
            rows.append(row)
    if not rows:
        raise ValueError("no valid SFT rows could be built from trajectories")
    return rows


def _split_rows(
    rows: list[tuple[list[int], list[int]]],
    *,
    val_ratio: float,
    seed: int,
) -> tuple[list[tuple[list[int], list[int]]], list[tuple[list[int], list[int]]]]:
    """Split rows deterministically while preserving at least one val row."""
    if val_ratio <= 0:
        return rows, []
    val_count = max(1, int(round(len(rows) * val_ratio)))
    val_count = min(val_count, len(rows) - 1) if len(rows) > 1 else 0
    indices = list(range(len(rows)))
    import random

    random.Random(seed).shuffle(indices)
    val_indices = set(indices[:val_count])
    train = [row for index, row in enumerate(rows) if index not in val_indices]
    val = [row for index, row in enumerate(rows) if index in val_indices]
    if not val:
        val = [rows[0]]
    return train, val


def _build_optimizer(model: TinyDecoderLM, config: SFTConfig) -> AdamW:
    return AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
        betas=(0.9, 0.95),
        eps=1e-8,
    )


def _build_scheduler(optimizer: AdamW, config: SFTConfig) -> LambdaLR:
    total_steps = max(1, config.steps)
    warmup_steps = max(0, config.warmup_steps)
    min_lr_ratio = config.cosine_min_lr / config.learning_rate

    def lr_lambda(step: int) -> float:
        if step < warmup_steps:
            return float(step) / float(max(1, warmup_steps))
        progress = (step - warmup_steps) / max(1, total_steps - warmup_steps)
        cosine = 0.5 * (1.0 + math.cos(math.pi * progress))
        return min_lr_ratio + (1.0 - min_lr_ratio) * cosine

    return LambdaLR(optimizer, lr_lambda)


def save_sft_checkpoint(
    path: Path,
    *,
    model: TinyDecoderLM,
    optimizer: AdamW,
    scheduler: LambdaLR,
    scaler: torch.amp.GradScaler | None,
    step: int,
    metadata: dict[str, Any],
) -> str:
    """Atomically save an SFT training checkpoint."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = {
        "format": SFT_CHECKPOINT_FORMAT,
        "model_config": model.config.to_dict(),
        "model_state": {
            key: value.detach().cpu() for key, value in model.state_dict().items()
        },
        "optimizer_state": optimizer.state_dict(),
        "scheduler_state": scheduler.state_dict(),
        "scaler_state": scaler.state_dict() if scaler is not None else None,
        "step": step,
        "metadata": metadata,
    }
    torch.save(payload, temporary)
    temporary.replace(path)
    return file_sha256(path)


def load_sft_checkpoint(
    path: Path,
    *,
    model: TinyDecoderLM,
    optimizer: AdamW,
    scheduler: LambdaLR,
    scaler: torch.amp.GradScaler | None = None,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Verify and restore one SFT training checkpoint."""
    actual_hash = file_sha256(path)
    if expected_sha256 is not None and actual_hash != expected_sha256:
        raise ValueError("checkpoint SHA-256 mismatch")
    payload = torch.load(path, map_location="cpu", weights_only=False)
    if not isinstance(payload, dict) or payload.get("format") != SFT_CHECKPOINT_FORMAT:
        raise ValueError("unsupported SFT checkpoint format")
    saved_config = ModelConfig.from_dict(dict(payload.get("model_config", {})))
    if saved_config != model.config:
        raise ValueError("checkpoint model config does not match target model")
    model.load_state_dict(payload["model_state"], strict=True)
    optimizer.load_state_dict(payload["optimizer_state"])
    scheduler.load_state_dict(payload["scheduler_state"])
    if scaler is not None and payload.get("scaler_state") is not None:
        scaler.load_state_dict(payload["scaler_state"])
    return {
        "sha256": actual_hash,
        "step": int(payload.get("step", 0)),
        "metadata": dict(payload.get("metadata", {})),
    }


def load_pretrain_model_weights(
    path: Path,
    *,
    model: TinyDecoderLM,
) -> dict[str, Any]:
    """Load model weights from a MoE-pretrain or tiny-LM checkpoint."""
    payload = torch.load(path, map_location="cpu", weights_only=False)
    if not isinstance(payload, dict):
        raise ValueError("unsupported pretraining checkpoint format")
    format_name = payload.get("format")
    if format_name not in {
        "klara.moe-pretrain.checkpoint.v1",
        "klara.tiny-lm.checkpoint.v1",
    }:
        raise ValueError(f"unsupported pretraining checkpoint format: {format_name!r}")
    saved_config = ModelConfig.from_dict(dict(payload.get("model_config", {})))
    if saved_config != model.config:
        raise ValueError("pretraining checkpoint model config does not match target model")
    model.load_state_dict(payload["model_state"], strict=True)
    return {
        "format": format_name,
        "step": int(payload.get("step", 0)),
        "metadata": dict(payload.get("metadata", {})),
    }


def evaluate_sft_loss(
    model: TinyDecoderLM,
    dataset: SFTDataset,
    *,
    batch_size: int,
    device: torch.device,
    precision: str,
    max_batches: int | None = None,
) -> float:
    """Return token-weighted mean next-token loss on an SFT split."""
    model.eval()
    loader = DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=False,
        num_workers=0,
        collate_fn=_collate_sft,
    )
    context, _scaler, _effective_precision = _amp_context(device, precision)
    weighted_loss = 0.0
    token_count = 0
    batches_seen = 0
    with torch.inference_mode():
        for batch in loader:
            moved = batch.to(device)
            with context:
                output = model(
                    moved.input_ids,
                    attention_mask=moved.input_ids.ne(model.config.pad_token_id),
                    labels=moved.labels,
                )
            if output.language_model_loss is None:
                raise RuntimeError("SFT validation forward did not produce LM loss")
            visible_tokens = int(moved.labels.ne(IGNORE_INDEX).sum().item())
            weighted_loss += float(output.language_model_loss.item()) * visible_tokens
            token_count += visible_tokens
            batches_seen += 1
            if max_batches is not None and batches_seen >= max_batches:
                break
    if token_count == 0:
        raise ValueError("SFT validation split contains no labeled tokens")
    return weighted_loss / token_count


def train_sft(
    model: TinyDecoderLM,
    moe_config: MoEConfig,
    config: SFTConfig,
    *,
    records: list[dict[str, Any]],
    tokenizer: Any,
    artifact_dir: Path,
    resume_from: Path | None = None,
    pretrain_from: Path | None = None,
) -> SFTResult:
    """Run full-parameter SFT with AMP, AdamW, cosine schedule, and resume."""
    seed_everything(config.seed)
    device = resolve_device(config.device)
    model.to(device)
    if pretrain_from is not None:
        load_pretrain_model_weights(pretrain_from, model=model)

    optimizer = _build_optimizer(model, config)
    scheduler = _build_scheduler(optimizer, config)
    context, scaler, effective_precision = _amp_context(device, config.precision)

    rows = build_sft_rows(
        records,
        tokenizer,
        sequence_length=model.config.max_sequence_length,
        pad_token_id=model.config.pad_token_id,
    )
    train_rows, val_rows = _split_rows(rows, val_ratio=config.val_ratio, seed=config.seed)
    train_dataset = SFTDataset(train_rows)
    val_dataset = SFTDataset(val_rows if val_rows else train_rows)

    def make_train_iter() -> Iterator[SFTBatch]:
        while True:
            loader = DataLoader(
                train_dataset,
                batch_size=config.batch_size,
                shuffle=True,
                num_workers=config.loader_workers,
                drop_last=False,
                collate_fn=_collate_sft,
            )
            yield from loader

    start_step = 0
    if resume_from is not None:
        restore = load_sft_checkpoint(
            resume_from,
            model=model,
            optimizer=optimizer,
            scheduler=scheduler,
            scaler=scaler if scaler.is_enabled() else None,
        )
        start_step = restore["step"]

    initial_val_loss = evaluate_sft_loss(
        model,
        val_dataset,
        batch_size=config.batch_size,
        device=device,
        precision=effective_precision,
    )
    model.train()
    train_iter = make_train_iter()
    logs: list[dict[str, Any]] = []
    final_train_loss = initial_val_loss
    gradients_finite = True
    last_checkpoint_hash = ""

    for step in range(start_step, config.steps):
        optimizer.zero_grad(set_to_none=True)
        language_model_sum = 0.0
        auxiliary_sum = 0.0
        for _ in range(config.gradient_accumulation_steps):
            batch = next(train_iter).to(device)
            with context:
                output = model(
                    batch.input_ids,
                    attention_mask=batch.input_ids.ne(model.config.pad_token_id),
                    labels=batch.labels,
                )
            if output.loss is None or output.language_model_loss is None:
                raise RuntimeError("SFT training forward did not produce loss")
            if not bool(torch.isfinite(output.loss)):
                raise FloatingPointError("non-finite SFT training loss")
            loss = output.loss / config.gradient_accumulation_steps
            language_model_sum += float(output.language_model_loss.detach().cpu().item())
            auxiliary_sum += float(output.auxiliary_loss.detach().cpu().item())
            scaler.scale(loss).backward()

        if scaler.is_enabled():
            scaler.unscale_(optimizer)
        step_gradients_finite = all(
            parameter.grad is None or bool(torch.isfinite(parameter.grad).all())
            for parameter in model.parameters()
        )
        gradients_finite = gradients_finite and step_gradients_finite
        if not step_gradients_finite:
            raise FloatingPointError("non-finite SFT model gradient")
        grad_norm = torch.nn.utils.clip_grad_norm_(
            model.parameters(),
            config.gradient_clip,
        )
        scaler.step(optimizer)
        scaler.update()
        scheduler.step()

        final_train_loss = language_model_sum / config.gradient_accumulation_steps
        current_lr = float(scheduler.get_last_lr()[0])
        completed_step = step + 1
        if completed_step % config.log_every == 0 or completed_step == config.steps:
            logs.append(
                {
                    "step": completed_step,
                    "train_loss": final_train_loss,
                    "auxiliary_loss": auxiliary_sum / config.gradient_accumulation_steps,
                    "lr": current_lr,
                    "grad_norm": float(grad_norm),
                    "val_loss": None,
                }
            )
        if completed_step % config.val_every == 0 or completed_step == config.steps:
            val_loss = evaluate_sft_loss(
                model,
                val_dataset,
                batch_size=config.batch_size,
                device=device,
                precision=effective_precision,
            )
            if logs and logs[-1]["step"] == completed_step:
                logs[-1]["val_loss"] = val_loss
            else:
                logs.append(
                    {
                        "step": completed_step,
                        "train_loss": final_train_loss,
                        "auxiliary_loss": auxiliary_sum / config.gradient_accumulation_steps,
                        "lr": current_lr,
                        "grad_norm": float(grad_norm),
                        "val_loss": val_loss,
                    }
                )
            model.train()
        if config.checkpoint_every and completed_step % config.checkpoint_every == 0:
            last_checkpoint_hash = save_sft_checkpoint(
                artifact_dir / f"checkpoint_{completed_step:07d}.pt",
                model=model,
                optimizer=optimizer,
                scheduler=scheduler,
                scaler=scaler if scaler.is_enabled() else None,
                step=completed_step,
                metadata={
                    "precision": effective_precision,
                    "num_experts": moe_config.num_experts,
                    "top_k": moe_config.top_k,
                },
            )

    final_val_loss = evaluate_sft_loss(
        model,
        val_dataset,
        batch_size=config.batch_size,
        device=device,
        precision=effective_precision,
    )
    reduction = (
        (initial_val_loss - final_val_loss) / initial_val_loss
        if initial_val_loss > 0
        else 0.0
    )
    return SFTResult(
        initial_val_loss=initial_val_loss,
        final_val_loss=final_val_loss,
        loss_reduction_fraction=reduction,
        final_train_loss=final_train_loss,
        gradients_finite=gradients_finite,
        parameter_count=count_parameters(model),
        final_step=config.steps,
        device=str(device),
        precision=effective_precision,
        logs=tuple(logs),
        model_state_sha256=model_state_sha256(model),
        final_checkpoint_sha256=last_checkpoint_hash,
    )
