"""Bounded deterministic trainer and reproducibility probes."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
import hashlib
import random
from time import perf_counter
from typing import Any

import torch

from klara.training.config import ModelConfig, TrainConfig
from klara.training.data import CausalBatch
from klara.training.model import TinyDecoderLM
from klara.training.tokenizer import ByteTokenizer


PRETRAIN_SCORER_VERSION = "klara.pretrain-eval.v1"


@dataclass(frozen=True)
class TrainingResult:
    """Measured result from one bounded language-model training run."""

    initial_loss: float
    final_loss: float
    loss_reduction_fraction: float
    loss_curve: tuple[float, ...]
    duration_seconds: float
    peak_allocated_bytes: int
    gradients_finite: bool
    parameter_count: int
    model_state_sha256: str
    generated_token_ids: tuple[int, ...]
    generated_text: str
    device: str
    precision: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible training result."""

        return {
            "initial_loss": self.initial_loss,
            "final_loss": self.final_loss,
            "loss_reduction_fraction": self.loss_reduction_fraction,
            "loss_curve": list(self.loss_curve),
            "duration_seconds": self.duration_seconds,
            "peak_allocated_bytes": self.peak_allocated_bytes,
            "gradients_finite": self.gradients_finite,
            "parameter_count": self.parameter_count,
            "model_state_sha256": self.model_state_sha256,
            "generated_token_ids": list(self.generated_token_ids),
            "generated_text": self.generated_text,
            "device": self.device,
            "precision": self.precision,
        }


def seed_everything(seed: int) -> None:
    """Seed Python and PyTorch without requiring NumPy."""

    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False


def resolve_device(requested: str) -> torch.device:
    """Resolve the portable auto/cpu/cuda experiment setting."""

    if requested == "auto":
        return torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is not available")
    return torch.device(requested)


def evaluate_loss(
    model: TinyDecoderLM,
    batches: tuple[CausalBatch, ...],
    device: torch.device,
) -> float:
    """Return token-weighted mean cross entropy over fixed batches."""

    model.eval()
    weighted_loss = 0.0
    token_count = 0
    with torch.inference_mode():
        # Use every frozen row so start/end loss comparisons share the same data.
        for batch in batches:
            moved = batch.to(device)
            output = model(
                moved.input_ids,
                attention_mask=moved.attention_mask,
                labels=moved.labels,
            )
            if output.language_model_loss is None:
                raise RuntimeError("evaluation did not produce a language-model loss")
            visible_tokens = int(moved.labels.ne(-100).sum().item())
            weighted_loss += float(output.language_model_loss.item()) * visible_tokens
            token_count += visible_tokens
    if token_count == 0:
        raise ValueError("evaluation batches contain no labeled tokens")
    return weighted_loss / token_count


def train_language_model(
    model: TinyDecoderLM,
    batches: tuple[CausalBatch, ...],
    config: TrainConfig,
    *,
    tokenizer: ByteTokenizer,
    generation_prompt: str,
) -> tuple[TrainingResult, torch.optim.Optimizer]:
    """Train within a fixed step budget and return measured proof artifacts."""

    if not batches:
        raise ValueError("training requires at least one causal batch")
    seed_everything(config.seed)
    device = resolve_device(config.device)
    model.to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    use_fp16 = config.precision == "fp16" and device.type == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=use_fp16)
    autocast_context = (
        lambda: torch.amp.autocast("cuda", dtype=torch.float16)
        if use_fp16
        else nullcontext()
    )
    initial_loss = evaluate_loss(model, batches, device)
    generator = torch.Generator(device="cpu").manual_seed(config.seed)
    order: list[int] = []
    order_index = 0
    losses: list[float] = []
    gradients_finite = True
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)
        torch.cuda.synchronize(device)
    started = perf_counter()
    model.train()
    # A seeded epoch permutation prevents an accidental dependency on DataLoader workers.
    for _ in range(config.steps):
        if order_index >= len(order):
            order = torch.randperm(len(batches), generator=generator).tolist()
            order_index = 0
        batch = batches[order[order_index]].to(device)
        order_index += 1
        optimizer.zero_grad(set_to_none=True)
        with autocast_context():
            output = model(
                batch.input_ids,
                attention_mask=batch.attention_mask,
                labels=batch.labels,
            )
            if output.loss is None:
                raise RuntimeError("training forward pass did not produce loss")
            loss = output.loss
        if not bool(torch.isfinite(loss)):
            raise FloatingPointError("non-finite training loss")
        scaler.scale(loss).backward()
        scaler.unscale_(optimizer)
        step_gradients_finite = all(
            parameter.grad is None or bool(torch.isfinite(parameter.grad).all())
            for parameter in model.parameters()
        )
        gradients_finite = gradients_finite and step_gradients_finite
        if not step_gradients_finite:
            raise FloatingPointError("non-finite model gradient")
        torch.nn.utils.clip_grad_norm_(model.parameters(), config.gradient_clip)
        scaler.step(optimizer)
        scaler.update()
        losses.append(float(loss.detach().item()))
    if device.type == "cuda":
        torch.cuda.synchronize(device)
    duration_seconds = perf_counter() - started
    peak_allocated_bytes = (
        int(torch.cuda.max_memory_allocated(device)) if device.type == "cuda" else 0
    )
    final_loss = evaluate_loss(model, batches, device)
    prompt_ids = tokenizer.encode(generation_prompt, add_bos=True, add_eos=False)
    prompt = torch.tensor([prompt_ids], dtype=torch.long, device=device)
    model.eval()
    generated = model.generate(
        prompt,
        max_new_tokens=24,
        eos_token_id=tokenizer.eos_token_id,
    )[0].detach().cpu()
    sampled_curve = tuple(
        losses[index]
        for index in sorted(
            set(
                [0, len(losses) - 1]
                + list(range(9, len(losses), 10))
            )
        )
    )
    reduction = (initial_loss - final_loss) / initial_loss
    result = TrainingResult(
        initial_loss=initial_loss,
        final_loss=final_loss,
        loss_reduction_fraction=reduction,
        loss_curve=sampled_curve,
        duration_seconds=duration_seconds,
        peak_allocated_bytes=peak_allocated_bytes,
        gradients_finite=gradients_finite,
        parameter_count=sum(parameter.numel() for parameter in model.parameters()),
        model_state_sha256=model_state_sha256(model),
        generated_token_ids=tuple(int(value) for value in generated.tolist()),
        generated_text=tokenizer.decode(generated.tolist()),
        device=str(device),
        precision=config.precision,
    )
    return result, optimizer


def cpu_reproducibility_hash(
    model_config: ModelConfig,
    *,
    tokenizer: ByteTokenizer,
    prompt: str,
    seed: int,
) -> str:
    """Return a CPU initialization/forward/generation hash for one seed."""

    seed_everything(seed)
    model = TinyDecoderLM(model_config).cpu().eval()
    prompt_ids = tokenizer.encode(prompt, add_bos=True, add_eos=False)
    input_ids = torch.tensor([prompt_ids], dtype=torch.long)
    with torch.inference_mode():
        output = model(input_ids)
        generated = model.generate(
            input_ids,
            max_new_tokens=8,
            eos_token_id=tokenizer.eos_token_id,
        )
    digest = hashlib.sha256()
    digest.update(_tensor_bytes(output.logits))
    digest.update(_tensor_bytes(generated))
    return digest.hexdigest()


def gpu_memory_smoke(
    model_config: ModelConfig,
    *,
    seed: int,
    batch_size: int = 2,
) -> dict[str, Any]:
    """Run a full-context forward/backward smoke and report peak allocation."""

    if not torch.cuda.is_available():
        return {
            "available": False,
            "passed": False,
            "peak_allocated_bytes": 0,
            "device": "unavailable",
        }
    seed_everything(seed)
    device = torch.device("cuda")
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats(device)
    model = TinyDecoderLM(model_config).to(device)
    input_ids = torch.randint(
        4,
        model_config.vocab_size,
        (batch_size, model_config.max_sequence_length),
        device=device,
    )
    labels = input_ids.roll(shifts=-1, dims=1)
    output = model(input_ids, labels=labels)
    if output.loss is None:
        raise RuntimeError("GPU smoke did not produce loss")
    output.loss.backward()
    torch.cuda.synchronize(device)
    peak = int(torch.cuda.max_memory_allocated(device))
    finite = bool(torch.isfinite(output.loss)) and all(
        parameter.grad is None or bool(torch.isfinite(parameter.grad).all())
        for parameter in model.parameters()
    )
    device_name = torch.cuda.get_device_name(device)
    del output, labels, input_ids, model
    torch.cuda.empty_cache()
    return {
        "available": True,
        "passed": finite and peak < int(3.5 * 1024**3),
        "peak_allocated_bytes": peak,
        "limit_bytes": int(3.5 * 1024**3),
        "device": device_name,
    }


def model_state_sha256(model: TinyDecoderLM) -> str:
    """Hash ordered parameter names, shapes, dtypes, and raw tensor bytes."""

    digest = hashlib.sha256()
    # State-dict key order is stable, but sort explicitly for manifest portability.
    for name, tensor in sorted(model.state_dict().items()):
        value = tensor.detach().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(tuple(value.shape)).encode("ascii"))
        digest.update(str(value.dtype).encode("ascii"))
        digest.update(_tensor_bytes(value))
    return digest.hexdigest()


def _tensor_bytes(tensor: torch.Tensor) -> bytes:
    """Return exact contiguous CPU bytes without requiring NumPy."""

    byte_values = tensor.detach().cpu().contiguous().view(torch.uint8).flatten().tolist()
    return bytes(byte_values)
