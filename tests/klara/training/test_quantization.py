from __future__ import annotations

import pytest
import torch

from klara.training.config import ModelConfig
from klara.training.model import TinyDecoderLM
from klara.training.quantization import (
    FP4Tensor,
    W4A16Linear,
    dequantize_fp4,
    e2m1_decode,
    e2m1_encode,
    pack_nibbles,
    quantize_fp4,
    quantize_gated_linears,
    unpack_nibbles,
)


def _config() -> ModelConfig:
    return ModelConfig(
        hidden_size=16,
        num_layers=1,
        num_attention_heads=2,
        num_key_value_heads=1,
        intermediate_size=32,
        max_sequence_length=16,
    )


def test_every_e2m1_code_round_trips_bit_exactly() -> None:
    codes = torch.arange(16, dtype=torch.uint8)
    decoded = e2m1_decode(codes)
    restored = e2m1_encode(decoded)

    assert torch.equal(restored, codes)
    assert torch.signbit(decoded[8])


@pytest.mark.parametrize("length", [1, 2, 7, 8])
def test_nibble_pack_unpack_handles_odd_and_even_lengths(length: int) -> None:
    codes = torch.arange(length, dtype=torch.uint8).remainder(16)
    packed, logical_length = pack_nibbles(codes)

    assert logical_length == length
    assert packed.numel() == (length + 1) // 2
    assert torch.equal(unpack_nibbles(packed, logical_length), codes)


def test_block_metadata_validates_and_storage_saves_at_least_65_percent() -> None:
    values = torch.linspace(-1, 1, 257)
    quantized = quantize_fp4(values, block_size=64)

    assert quantized.format_version == "klara.fp4-e2m1-block.v1"
    assert quantized.metadata()["scale_count"] == 5
    assert 1.0 - quantized.storage_bytes / quantized.fp16_baseline_bytes >= 0.65
    assert torch.isfinite(dequantize_fp4(quantized)).all()
    with pytest.raises(ValueError, match="format version"):
        FP4Tensor(
            packed=quantized.packed,
            scales=quantized.scales,
            shape=quantized.shape,
            block_size=quantized.block_size,
            logical_length=quantized.logical_length,
            format_version="unknown",
        )


def test_w4a16_gated_model_is_finite_and_reports_scale_inclusive_storage() -> None:
    torch.manual_seed(9)
    model = TinyDecoderLM(_config()).eval()
    quantized, storage = quantize_gated_linears(model, block_size=16)
    tokens = torch.randint(4, 260, (2, 10))

    with torch.inference_mode():
        output = quantized(tokens)

    assert torch.isfinite(output.logits).all()
    assert storage["tensor_count"] == 3
    assert storage["saving_fraction"] >= 0.65
    assert all(item["scale_dtype"] == "float16" for item in storage["tensors"].values())
    packed_modules = [module for module in quantized.modules() if isinstance(module, W4A16Linear)]
    assert len(packed_modules) == 3
    assert all("weight" not in module.state_dict() for module in packed_modules)
    assert all(module.packed_weight.dtype == torch.uint8 for module in packed_modules)
