"""Training loop for the Klara 124M four-expert top-2 sparse MoE lane."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any

import torch
from torch import nn
from torch.optim import AdamW
from torch.optim.lr_scheduler import LambdaLR
from torch.utils.data import DataLoader

from klara.training.checkpoint import file_sha256
from klara.training.config import ModelConfig
from klara.training.moe import MoEConfig
from klara.training.model import TinyDecoderLM
from klara.training.shard_data import PackedShardDataset
from klara.training.trainer import model_state_sha256, resolve_device, seed_everything

MOE_PRETRAIN_CHECKPOINT_FORMAT = "klara.moe-pretrain.checkpoint.v1"
MOE_PRETRAIN_LOG_SCHEMA = "klara.moe-pretrain.log.v1"


@dataclass(frozen=True)
class MoEPretrainConfig:
    """Optimization contract for the sparse-MoE pretraining lane."""

    seed: int = 20260816
    steps: int = 200_000
    batch_size: int = 8
    gradient_accumulation_steps: int = 8
    learning_rate: float = 0.0003
    weight_decay: float = 0.1
    gradient_clip: float = 1.0
    precision: str = "bf16"
    device: str = "cuda"
    warmup_steps: int = 2000
    cosine_min_lr: float = 0.00003
    val_every: int = 100
    log_every: int = 10
    checkpoint_every: int = 1000
    loader_workers: int = 0

    def __post_init__(self) -> None:
        """Reject invalid or non-reproducible optimizer settings."""

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
            raise ValueError("the reproducible Windows streaming loader uses zero workers")
        if self.warmup_steps < 0:
            raise ValueError("warmup_steps must be non-negative")

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "MoEPretrainConfig":
        """Create a validated optimizer config from a TOML mapping."""

        return cls(**raw)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible optimizer manifest."""

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
        }


@dataclass(frozen=True)
class MoEPretrainResult:
    """Measured result from one sparse-MoE pretraining run."""

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
    final_expert_load: tuple[float, ...]
    final_router_entropy: float
    final_aux_loss: float

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible result."""

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
            "final_expert_load": list(self.final_expert_load),
            "final_router_entropy": self.final_router_entropy,
            "final_aux_loss": self.final_aux_loss,
        }


def _amp_context(
    device: torch.device,
    precision: str,
) -> tuple[Any, torch.amp.GradScaler, str]:
    """Return an autocast context, scaler, and the effective precision."""

    if device.type != "cuda":
        return nullcontext(), torch.amp.GradScaler("cuda", enabled=False), "fp32"
    if precision == "bf16" and not torch.cuda.is_bf16_supported():
        return nullcontext(), torch.amp.GradScaler("cuda", enabled=False), "fp32"
    if precision in {"fp16", "bf16"}:
        dtype = torch.bfloat16 if precision == "bf16" else torch.float16
        enabled = True
        context = torch.autocast("cuda", dtype=dtype)
        scaler = torch.amp.GradScaler("cuda", enabled=enabled)
        return context, scaler, precision
    return nullcontext(), torch.amp.GradScaler("cuda", enabled=False), "fp32"


def _build_optimizer(
    model: TinyDecoderLM,
    learning_rate: float,
    weight_decay: float,
) -> AdamW:
    """Create AdamW with a small epsilon suitable for long pretraining."""

    return AdamW(
        model.parameters(),
        lr=learning_rate,
        weight_decay=weight_decay,
        betas=(0.9, 0.95),
        eps=1e-8,
    )


def _build_scheduler(
    optimizer: AdamW,
    config: MoEPretrainConfig,
) -> LambdaLR:
    """Create linear warmup followed by cosine decay to ``cosine_min_lr``."""

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


def count_parameters(model: nn.Module) -> int:
    """Count all trainable and non-trainable parameters."""

    return sum(parameter.numel() for parameter in model.parameters())


def evaluate_val_loss(
    model: TinyDecoderLM,
    val_dataset: PackedShardDataset,
    device: torch.device,
    *,
    precision: str,
    max_batches: int | None = None,
) -> float:
    """Return token-weighted mean LM loss over the validation shards."""

    model.eval()
    loader = DataLoader(
        val_dataset,
        batch_size=None,
        num_workers=0,
    )
    context, _scaler, _effective_precision = _amp_context(device, precision)
    weighted_loss = 0.0
    token_count = 0
    batches_seen = 0
    with torch.inference_mode():
        for batch in loader:
            moved = batch.to(device)
            with context:
                output = model(moved.input_ids, labels=moved.labels)
            if output.language_model_loss is None:
                raise RuntimeError("validation forward pass did not produce LM loss")
            visible_tokens = int(moved.labels.numel())
            weighted_loss += float(output.language_model_loss.item()) * visible_tokens
            token_count += visible_tokens
            batches_seen += 1
            if max_batches is not None and batches_seen >= max_batches:
                break
    if token_count == 0:
        raise ValueError("validation dataset contains no tokens")
    return weighted_loss / token_count


def _aggregate_routing(
    metrics: dict[str, torch.Tensor],
    *,
    total_loads: torch.Tensor | None,
    entropy_sum: float,
) -> tuple[torch.Tensor, float]:
    """Accumulate expert loads and router entropy across micro-batches."""

    loads = metrics["expert_loads"].detach().float().cpu()
    if total_loads is None:
        total_loads = loads.clone()
    else:
        total_loads = total_loads + loads
    entropy_sum += float(metrics["router_entropy_sum"].detach().cpu().item())
    return total_loads, entropy_sum


def save_training_checkpoint(
    path: Path,
    *,
    model: TinyDecoderLM,
    optimizer: AdamW,
    scheduler: LambdaLR,
    scaler: torch.amp.GradScaler | None,
    step: int,
    metadata: dict[str, Any],
) -> str:
    """Atomically save model, optimizer, scheduler, and scaler state."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = {
        "format": MOE_PRETRAIN_CHECKPOINT_FORMAT,
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


def load_training_checkpoint(
    path: Path,
    *,
    model: TinyDecoderLM,
    optimizer: AdamW,
    scheduler: LambdaLR,
    scaler: torch.amp.GradScaler | None = None,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Verify and restore one training checkpoint."""

    actual_hash = file_sha256(path)
    if expected_sha256 is not None and actual_hash != expected_sha256:
        raise ValueError("checkpoint SHA-256 mismatch")
    payload = torch.load(path, map_location="cpu", weights_only=False)
    if (
        not isinstance(payload, dict)
        or payload.get("format") != MOE_PRETRAIN_CHECKPOINT_FORMAT
    ):
        raise ValueError("unsupported MoE pretraining checkpoint format")
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


def train_moe_pretrain(
    model: TinyDecoderLM,
    moe_config: MoEConfig,
    config: MoEPretrainConfig,
    *,
    train_dataset: PackedShardDataset,
    val_dataset: PackedShardDataset,
    artifact_dir: Path,
    resume_from: Path | None = None,
) -> MoEPretrainResult:
    """Train the sparse MoE with bf16/fp16 AMP, warmup+cosine, and resume."""

    seed_everything(config.seed)
    device = resolve_device(config.device)
    model.to(device)
    optimizer = _build_optimizer(model, config.learning_rate, config.weight_decay)
    scheduler = _build_scheduler(optimizer, config)
    context, scaler, effective_precision = _amp_context(device, config.precision)

    start_step = 0
    if resume_from is not None:
        details = load_training_checkpoint(
            resume_from,
            model=model,
            optimizer=optimizer,
            scheduler=scheduler,
            scaler=scaler,
        )
        start_step = details["step"]
        if start_step > config.steps:
            raise ValueError("resume checkpoint is already past the configured step budget")

    initial_val_loss = evaluate_val_loss(
        model,
        val_dataset,
        device,
        precision=effective_precision,
    )

    train_loader = DataLoader(
        train_dataset,
        batch_size=None,
        num_workers=config.loader_workers,
    )
    train_iter = iter(train_loader)
    logs: list[dict[str, Any]] = []
    gradients_finite = True
    final_expert_load: tuple[float, ...] = (0.0, 0.0, 0.0, 0.0)
    final_router_entropy = 0.0
    final_aux_loss = 0.0
    final_train_loss = initial_val_loss
    last_checkpoint_hash = ""

    model.train()
    for step in range(start_step, config.steps):
        optimizer.zero_grad(set_to_none=True)
        language_model_sum = 0.0
        auxiliary_sum = 0.0
        entropy_sum = 0.0
        total_loads: torch.Tensor | None = None
        for _accumulation_index in range(config.gradient_accumulation_steps):
            batch = next(train_iter).to(device)
            with context:
                output = model(batch.input_ids, labels=batch.labels)
            if output.loss is None or output.language_model_loss is None:
                raise RuntimeError("training forward pass did not produce a loss")
            if not bool(torch.isfinite(output.loss)):
                raise FloatingPointError("non-finite training loss")
            loss = output.loss / config.gradient_accumulation_steps
            language_model_sum += float(output.language_model_loss.detach().cpu().item())
            auxiliary_sum += float(output.auxiliary_loss.detach().cpu().item())
            total_loads, entropy_sum = _aggregate_routing(
                output.routing_metrics,
                total_loads=total_loads,
                entropy_sum=entropy_sum,
            )
            scaler.scale(loss).backward()

        if scaler.is_enabled():
            scaler.unscale_(optimizer)
        gradients_finite = gradients_finite and all(
            parameter.grad is None
            or bool(torch.isfinite(parameter.grad).all())
            for parameter in model.parameters()
        )
        if not gradients_finite:
            raise FloatingPointError("non-finite model gradient")
        grad_norm = torch.nn.utils.clip_grad_norm_(
            model.parameters(),
            config.gradient_clip,
        )
        scaler.step(optimizer)
        scaler.update()
        scheduler.step()

        micro_batches = config.gradient_accumulation_steps
        avg_train_loss = language_model_sum / micro_batches
        avg_aux_loss = auxiliary_sum / micro_batches
        avg_entropy = entropy_sum / micro_batches / len(model.blocks)
        if total_loads is None:
            load_fractions = (0.0, 0.0, 0.0, 0.0)
        else:
            load_fractions = tuple(
                float(value)
                for value in (total_loads / total_loads.sum().clamp_min(1.0)).tolist()
            )
        final_train_loss = avg_train_loss
        final_aux_loss = avg_aux_loss
        final_router_entropy = avg_entropy
        final_expert_load = load_fractions
        current_lr = float(scheduler.get_last_lr()[0])

        completed_step = step + 1
        if (
            completed_step % config.log_every == 0
            or completed_step == config.steps
        ):
            logs.append(
                {
                    "step": completed_step,
                    "train_loss": avg_train_loss,
                    "lr": current_lr,
                    "grad_norm": float(grad_norm),
                    "aux_loss": avg_aux_loss,
                    "router_entropy": avg_entropy,
                    "expert_load": list(load_fractions),
                    "expert_load_counts": (
                        list(total_loads.tolist()) if total_loads is not None else []
                    ),
                    "val_ppl": None,
                }
            )
        if (
            completed_step % config.val_every == 0
            or completed_step == config.steps
        ):
            val_loss = evaluate_val_loss(
                model,
                val_dataset,
                device,
                precision=effective_precision,
            )
            if logs and logs[-1]["step"] == completed_step:
                logs[-1]["val_ppl"] = math.exp(val_loss)
            else:
                logs.append(
                    {
                        "step": completed_step,
                        "train_loss": avg_train_loss,
                        "lr": current_lr,
                        "grad_norm": float(grad_norm),
                        "aux_loss": avg_aux_loss,
                        "router_entropy": avg_entropy,
                        "expert_load": list(load_fractions),
                        "expert_load_counts": (
                            list(total_loads.tolist()) if total_loads is not None else []
                        ),
                        "val_ppl": math.exp(val_loss),
                    }
                )
            model.train()
        if (
            config.checkpoint_every
            and completed_step % config.checkpoint_every == 0
        ):
            last_checkpoint_hash = save_training_checkpoint(
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

    final_val_loss = evaluate_val_loss(
        model,
        val_dataset,
        device,
        precision=effective_precision,
    )
    final_checkpoint_path = artifact_dir / "checkpoint_final.pt"
    final_checkpoint_hash = save_training_checkpoint(
        final_checkpoint_path,
        model=model,
        optimizer=optimizer,
        scheduler=scheduler,
        scaler=scaler if scaler.is_enabled() else None,
        step=config.steps,
        metadata={
            "precision": effective_precision,
            "num_experts": moe_config.num_experts,
            "top_k": moe_config.top_k,
        },
    )
    if not last_checkpoint_hash:
        last_checkpoint_hash = final_checkpoint_hash
    reduction = (
        (initial_val_loss - final_val_loss) / initial_val_loss
        if initial_val_loss > 0
        else 0.0
    )
    return MoEPretrainResult(
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
        final_checkpoint_sha256=final_checkpoint_hash,
        final_expert_load=final_expert_load,
        final_router_entropy=final_router_entropy,
        final_aux_loss=final_aux_loss,
    )
