"""W4A16 benchmark for the Klara sparse-MoE model.

The implementation reuses :mod:`klara.training.quantization`, so the packed
E2M1 FP4 format and block sizes stay aligned with the training lane.  We
benchmark the dequantized-dense-compute path by comparing full-model logits
before and after replacing every SwiGLU gate/up/down projection.
"""

from __future__ import annotations

from typing import Any

import torch
from torch import nn
from torch.nn import functional as F

from klara.training.quantization import (
    W4A16Linear,
    dequantize_fp4,
    quantize_gated_linears,
)

W4A16_BENCHMARK_SCHEMA = "klara.inference.w4a16-benchmark.v1"


def _tensor_error_metrics(reference: torch.Tensor, candidate: torch.Tensor) -> dict[str, float]:
    """Return scalar error metrics between two tensors."""

    reference = reference.detach().reshape(-1).float()
    candidate = candidate.detach().reshape(-1).float()
    if reference.numel() == 0:
        raise ValueError("cannot compare empty tensors")
    difference = candidate - reference
    absolute = difference.abs()
    denominator = reference.abs().clamp_min(torch.finfo(torch.float32).tiny)
    relative = absolute / denominator
    dot = torch.dot(reference, candidate)
    norm_reference = reference.norm().clamp_min(torch.finfo(torch.float32).tiny)
    norm_candidate = candidate.norm().clamp_min(torch.finfo(torch.float32).tiny)
    cosine = dot / (norm_reference * norm_candidate)
    return {
        "max_abs_error": float(absolute.max().item()),
        "mean_abs_error": float(absolute.mean().item()),
        "max_relative_error": float(relative.max().item()),
        "mean_relative_error": float(relative.mean().item()),
        "rmse": float(difference.square().mean().sqrt().item()),
        "cosine_similarity": float(cosine.clamp(-1.0, 1.0).item()),
    }


def _weight_error_metrics(
    original: nn.Module,
    quantized: nn.Module,
) -> dict[str, Any]:
    """Compare original gated projections with dequantized FP4 weights."""

    tensors: dict[str, dict[str, float]] = {}
    for name, module in original.named_modules():
        if not isinstance(module, nn.Linear) or not name.endswith(
            (".gate", ".up", ".down")
        ):
            continue
        quantized_module = quantized.get_submodule(name)
        if not isinstance(quantized_module, W4A16Linear):
            continue
        reference_weight = module.weight.detach().float().cpu()
        dequantized_weight = dequantize_fp4(
            quantized_module.quantized_tensor(),
            dtype=torch.float32,
        )
        tensors[name] = _tensor_error_metrics(reference_weight, dequantized_weight)

    if not tensors:
        raise ValueError("model contains no quantized gated projections")
    flat_metrics = [values for values in tensors.values()]
    return {
        "tensor_count": len(tensors),
        "max_abs_error": max(item["max_abs_error"] for item in flat_metrics),
        "mean_abs_error": sum(item["mean_abs_error"] for item in flat_metrics)
        / len(flat_metrics),
        "max_relative_error": max(
            item["max_relative_error"] for item in flat_metrics
        ),
        "mean_relative_error": sum(
            item["mean_relative_error"] for item in flat_metrics
        )
        / len(flat_metrics),
        "rmse": max(item["rmse"] for item in flat_metrics),
        "cosine_similarity": min(
            item["cosine_similarity"] for item in flat_metrics
        ),
        "tensors": tensors,
    }


def benchmark_w4a16(
    model: nn.Module,
    input_ids: torch.Tensor,
    *,
    attention_mask: torch.Tensor | None = None,
    block_size: int = 64,
) -> dict[str, Any]:
    """Quantize gated projections and report storage and logit error metrics.

    Parameters
    ----------
    model:
        A ``TinyDecoderLM`` (dense or sparse MoE) with trainable Linear
        gate/up/down projections.  The model is left unchanged.
    input_ids:
        A representative token batch.  If the tensor lives on GPU it will be
        used directly; otherwise the model's current device is used.
    attention_mask:
        Optional boolean padding mask.  Defaults to all-visible.
    block_size:
        FP4 per-block scale size passed to ``quantize_gated_linears``.
    """

    if input_ids.ndim != 2:
        raise ValueError("input_ids must have shape [batch, sequence]")
    if attention_mask is None:
        pad_token_id = getattr(
            getattr(model, "config", None),
            "pad_token_id",
            0,
        )
        attention_mask = input_ids.ne(pad_token_id)
    if attention_mask.shape != input_ids.shape:
        raise ValueError("attention_mask must match input_ids")

    model.eval()
    device = next(model.parameters()).device
    input_ids = input_ids.to(device)
    attention_mask = attention_mask.to(device)

    quantized_model, storage_summary = quantize_gated_linears(
        model,
        block_size=block_size,
    )
    quantized_model.to(device).eval()

    with torch.inference_mode():
        reference_logits = model(
            input_ids,
            attention_mask=attention_mask,
        ).logits.float()
        quantized_logits = quantized_model(
            input_ids,
            attention_mask=attention_mask,
        ).logits.float()

    weight_error = _weight_error_metrics(model, quantized_model)
    logit_error = _tensor_error_metrics(reference_logits, quantized_logits)
    allclose = bool(
        torch.allclose(
            quantized_logits,
            reference_logits,
            atol=1e-2,
            rtol=1e-2,
        )
    )

    storage_bytes = int(storage_summary["fp4_storage_bytes"])
    baseline_bytes = int(storage_summary["fp16_baseline_bytes"])
    saving_bytes = baseline_bytes - storage_bytes
    saving_fraction = (
        saving_bytes / baseline_bytes if baseline_bytes > 0 else 0.0
    )

    return {
        "schema_version": W4A16_BENCHMARK_SCHEMA,
        "block_size": block_size,
        "storage": {
            "format_version": storage_summary["format_version"],
            "tensor_count": int(storage_summary["tensor_count"]),
            "fp16_baseline_bytes": baseline_bytes,
            "fp4_storage_bytes": storage_bytes,
            "saving_bytes": saving_bytes,
            "saving_fraction": saving_fraction,
            "compression_ratio": (
                baseline_bytes / storage_bytes if storage_bytes > 0 else float("inf")
            ),
        },
        "precision": {
            "activation_dtype": str(
                next(model.parameters()).dtype
            ).replace("torch.", ""),
            "compute_mode": "dequantized_fp4_weight_matmul",
            "logits_match_at_1e-2": allclose,
            "logit_error": logit_error,
            "weight_error": weight_error,
        },
    }
