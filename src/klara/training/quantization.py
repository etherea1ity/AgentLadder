"""E2M1 FP4 packing and dequantized-compute W4A16 modules."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math
from typing import Any, Iterable

import torch
from torch import nn
from torch.nn import functional as F


FP4_FORMAT_VERSION = "klara.fp4-e2m1-block.v1"
FP4_MAGNITUDES = (0.0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0)


def e2m1_codebook(*, device: torch.device | None = None) -> torch.Tensor:
    """Return all 16 bit-pattern values, including signed zero."""

    magnitudes = torch.tensor(FP4_MAGNITUDES, dtype=torch.float32, device=device)
    return torch.cat((magnitudes, -magnitudes), dim=0)


def e2m1_decode(codes: torch.Tensor) -> torch.Tensor:
    """Decode unsigned four-bit codes to exact E2M1 values."""

    if codes.dtype != torch.uint8 or bool(codes.gt(15).any()):
        raise ValueError("E2M1 codes must be uint8 values in [0, 15]")
    magnitude = torch.tensor(
        FP4_MAGNITUDES,
        dtype=torch.float32,
        device=codes.device,
    )[codes.bitwise_and(0x07).long()]
    negative = codes.bitwise_and(0x08).ne(0)
    return torch.where(negative, -magnitude, magnitude)


def e2m1_encode(values: torch.Tensor) -> torch.Tensor:
    """Round finite floats to nearest E2M1 code while preserving signed zero."""

    if not bool(torch.isfinite(values).all()):
        raise ValueError("E2M1 encoder requires finite values")
    magnitudes = torch.tensor(
        FP4_MAGNITUDES,
        dtype=torch.float32,
        device=values.device,
    )
    absolute = values.float().abs().unsqueeze(-1)
    magnitude_codes = (absolute - magnitudes).abs().argmin(dim=-1).to(torch.uint8)
    sign_codes = torch.signbit(values).to(torch.uint8).mul_(8)
    return magnitude_codes.bitwise_or(sign_codes)


def pack_nibbles(codes: torch.Tensor) -> tuple[torch.Tensor, int]:
    """Pack even/odd-length E2M1 code arrays, low nibble first."""

    flat = codes.detach().cpu().contiguous().flatten()
    if flat.dtype != torch.uint8 or bool(flat.gt(15).any()):
        raise ValueError("packed codes must be uint8 nibbles")
    logical_length = flat.numel()
    if logical_length % 2:
        flat = torch.cat((flat, torch.zeros(1, dtype=torch.uint8)))
    packed = flat[0::2].bitwise_or(flat[1::2].bitwise_left_shift(4))
    return packed, logical_length


def unpack_nibbles(packed: torch.Tensor, logical_length: int) -> torch.Tensor:
    """Unpack low/high nibbles and trim one odd-length padding nibble."""

    flat = packed.detach().cpu().contiguous().flatten()
    if flat.dtype != torch.uint8 or logical_length < 0:
        raise ValueError("packed tensor and logical length are invalid")
    if logical_length > flat.numel() * 2:
        raise ValueError("logical length exceeds packed capacity")
    result = torch.empty(flat.numel() * 2, dtype=torch.uint8)
    result[0::2] = flat.bitwise_and(0x0F)
    result[1::2] = flat.bitwise_right_shift(4).bitwise_and(0x0F)
    return result[:logical_length]


@dataclass(frozen=True)
class FP4Tensor:
    """Packed E2M1 tensor with versioned per-block FP16 scales."""

    packed: torch.Tensor
    scales: torch.Tensor
    shape: tuple[int, ...]
    block_size: int
    logical_length: int
    format_version: str = FP4_FORMAT_VERSION

    def __post_init__(self) -> None:
        """Validate storage, shape, block count, and metadata version."""

        if self.format_version != FP4_FORMAT_VERSION:
            raise ValueError("unsupported FP4 format version")
        if self.packed.dtype != torch.uint8 or self.scales.dtype != torch.float16:
            raise ValueError("FP4 requires uint8 nibbles and FP16 block scales")
        if self.block_size < 2 or self.logical_length != math.prod(self.shape):
            raise ValueError("FP4 shape or block size metadata is invalid")
        if self.packed.numel() != math.ceil(self.logical_length / 2):
            raise ValueError("FP4 packed length does not match logical length")
        if self.scales.numel() != math.ceil(self.logical_length / self.block_size):
            raise ValueError("FP4 scale count does not match block metadata")
        if not bool(torch.isfinite(self.scales).all()) or bool(self.scales.le(0).any()):
            raise ValueError("FP4 block scales must be positive and finite")

    @property
    def storage_bytes(self) -> int:
        """Return packed-code plus scale bytes, excluding JSON metadata."""

        return self.packed.numel() + self.scales.numel() * 2

    @property
    def fp16_baseline_bytes(self) -> int:
        """Return dense FP16 bytes for the same logical tensor."""

        return self.logical_length * 2

    def metadata(self) -> dict[str, Any]:
        """Return the versioned structural manifest."""

        return {
            "format_version": self.format_version,
            "shape": list(self.shape),
            "logical_length": self.logical_length,
            "packed_length": self.packed.numel(),
            "block_size": self.block_size,
            "scale_count": self.scales.numel(),
            "scale_dtype": "float16",
            "code_dtype": "uint4_packed_low_nibble_first",
            "codebook": list(FP4_MAGNITUDES),
        }


def quantize_fp4(tensor: torch.Tensor, *, block_size: int = 64) -> FP4Tensor:
    """Quantize a finite tensor with max-abs block scaling and E2M1 codes."""

    flat = tensor.detach().cpu().float().contiguous().flatten()
    if not flat.numel() or not bool(torch.isfinite(flat).all()):
        raise ValueError("FP4 quantization requires a non-empty finite tensor")
    codes: list[torch.Tensor] = []
    scales: list[torch.Tensor] = []
    for start in range(0, flat.numel(), block_size):
        block = flat[start : start + block_size]
        scale = (block.abs().max() / 6.0).clamp_min(torch.finfo(torch.float16).tiny)
        scales.append(scale.to(torch.float16))
        codes.append(e2m1_encode(block / scale))
    packed, logical_length = pack_nibbles(torch.cat(codes))
    return FP4Tensor(
        packed=packed,
        scales=torch.stack(scales),
        shape=tuple(tensor.shape),
        block_size=block_size,
        logical_length=logical_length,
    )


def dequantize_fp4(
    quantized: FP4Tensor,
    *,
    device: torch.device | None = None,
    dtype: torch.dtype = torch.float32,
) -> torch.Tensor:
    """Decode packed FP4 to a dense compute tensor."""

    codes = unpack_nibbles(quantized.packed, quantized.logical_length)
    decoded = e2m1_decode(codes)
    expanded_scales = quantized.scales.float().repeat_interleave(
        quantized.block_size
    )[: quantized.logical_length]
    result = (decoded * expanded_scales).reshape(quantized.shape)
    return result.to(device=device, dtype=dtype)


class W4A16Linear(nn.Module):
    """Packed FP4 weight with FP16 activation and dequantized matmul compute."""

    def __init__(self, source: nn.Linear, *, block_size: int = 64) -> None:
        super().__init__()
        quantized = quantize_fp4(source.weight, block_size=block_size)
        self.in_features = source.in_features
        self.out_features = source.out_features
        self.block_size = block_size
        self.shape = quantized.shape
        self.logical_length = quantized.logical_length
        self.format_version = quantized.format_version
        self.register_buffer("packed_weight", quantized.packed)
        self.register_buffer("block_scales", quantized.scales)
        if source.bias is None:
            self.register_parameter("bias", None)
        else:
            self.bias = nn.Parameter(source.bias.detach().clone(), requires_grad=False)

    def quantized_tensor(self) -> FP4Tensor:
        """Reconstruct and validate the packed tensor contract."""

        return FP4Tensor(
            packed=self.packed_weight.detach().cpu(),
            scales=self.block_scales.detach().cpu(),
            shape=self.shape,
            block_size=self.block_size,
            logical_length=self.logical_length,
            format_version=self.format_version,
        )

    def forward(self, activations: torch.Tensor) -> torch.Tensor:
        """Dequantize weights to activation dtype and use standard dense GEMM."""

        weight = dequantize_fp4(
            self.quantized_tensor(),
            device=activations.device,
            dtype=activations.dtype,
        )
        bias = self.bias.to(activations.dtype) if self.bias is not None else None
        return F.linear(activations, weight, bias)


class FakeQuantLinear(nn.Linear):
    """Straight-through fake-quant layer for optional quality-recovery QAT."""

    def __init__(self, source: nn.Linear, *, block_size: int = 64) -> None:
        super().__init__(source.in_features, source.out_features, bias=source.bias is not None)
        self.block_size = block_size
        with torch.no_grad():
            self.weight.copy_(source.weight)
            if self.bias is not None and source.bias is not None:
                self.bias.copy_(source.bias)

    def forward(self, activations: torch.Tensor) -> torch.Tensor:
        quantized = quantize_fp4(self.weight, block_size=self.block_size)
        dequantized = dequantize_fp4(
            quantized,
            device=self.weight.device,
            dtype=self.weight.dtype,
        )
        ste_weight = self.weight + (dequantized - self.weight).detach()
        return F.linear(activations, ste_weight, self.bias)


def quantize_gated_linears(
    model: nn.Module,
    *,
    block_size: int = 64,
) -> tuple[nn.Module, dict[str, Any]]:
    """Deep-copy and pack every SwiGLU gate/up/down projection."""

    copied = deepcopy(model).cpu()
    names = _target_linear_names(copied)
    for name in names:
        parent, attribute = _parent_and_attribute(copied, name)
        source = getattr(parent, attribute)
        setattr(parent, attribute, W4A16Linear(source, block_size=block_size))
    return copied, quantized_storage_summary(copied)


def fake_quantize_gated_linears(model: nn.Module, *, block_size: int = 64) -> nn.Module:
    """Deep-copy gated projections into differentiable fake-quant layers."""

    copied = deepcopy(model).cpu()
    for name in _target_linear_names(copied):
        parent, attribute = _parent_and_attribute(copied, name)
        setattr(
            parent,
            attribute,
            FakeQuantLinear(getattr(parent, attribute), block_size=block_size),
        )
    return copied


def materialize_fake_quant_model(
    model: nn.Module,
    *,
    block_size: int = 64,
) -> tuple[nn.Module, dict[str, Any]]:
    """Convert trained fake-quant gated projections to packed W4A16 modules."""

    copied = deepcopy(model).cpu()
    for name in _target_linear_names(copied, accepted=(FakeQuantLinear,)):
        parent, attribute = _parent_and_attribute(copied, name)
        setattr(parent, attribute, W4A16Linear(getattr(parent, attribute), block_size=block_size))
    return copied, quantized_storage_summary(copied)


def quantized_storage_summary(model: nn.Module) -> dict[str, Any]:
    """Aggregate code and scale storage for every packed gated projection."""

    tensors: dict[str, Any] = {}
    fp16_bytes = 0
    fp4_bytes = 0
    for name, module in model.named_modules():
        if not isinstance(module, W4A16Linear):
            continue
        quantized = module.quantized_tensor()
        fp16_bytes += quantized.fp16_baseline_bytes
        fp4_bytes += quantized.storage_bytes
        tensors[name] = {
            **quantized.metadata(),
            "fp16_baseline_bytes": quantized.fp16_baseline_bytes,
            "fp4_storage_bytes": quantized.storage_bytes,
        }
    if not tensors:
        raise ValueError("model contains no packed W4A16 tensors")
    return {
        "format_version": FP4_FORMAT_VERSION,
        "tensor_count": len(tensors),
        "fp16_baseline_bytes": fp16_bytes,
        "fp4_storage_bytes": fp4_bytes,
        "saving_fraction": 1.0 - fp4_bytes / fp16_bytes,
        "tensors": tensors,
    }


def _target_linear_names(
    model: nn.Module,
    *,
    accepted: tuple[type[nn.Module], ...] = (nn.Linear,),
) -> tuple[str, ...]:
    suffixes = (".gate", ".up", ".down")
    return tuple(
        name
        for name, module in model.named_modules()
        if isinstance(module, accepted) and name.endswith(suffixes)
    )


def _parent_and_attribute(model: nn.Module, name: str) -> tuple[nn.Module, str]:
    parts = name.split(".")
    parent = model
    for part in parts[:-1]:
        parent = getattr(parent, part)
    return parent, parts[-1]
