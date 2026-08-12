from __future__ import annotations

from pathlib import Path

import pytest
import torch

from klara.training.checkpoint import load_checkpoint, save_checkpoint
from klara.training.config import ModelConfig
from klara.training.model import TinyDecoderLM
from klara.training.trainer import model_state_sha256


def _config() -> ModelConfig:
    return ModelConfig(
        hidden_size=16,
        num_layers=1,
        num_attention_heads=2,
        num_key_value_heads=1,
        intermediate_size=32,
        max_sequence_length=8,
    )


def test_checkpoint_round_trip_preserves_exact_model_state(tmp_path: Path) -> None:
    torch.manual_seed(12)
    model = TinyDecoderLM(_config())
    optimizer = torch.optim.AdamW(model.parameters())
    path = tmp_path / "model.pt"

    checkpoint_hash = save_checkpoint(
        path,
        model=model,
        optimizer=optimizer,
        step=7,
        metadata={"seed": 12},
    )
    restored = TinyDecoderLM(_config())
    details = load_checkpoint(
        path,
        model=restored,
        expected_sha256=checkpoint_hash,
    )

    assert not path.with_suffix(".pt.tmp").exists()
    assert details["step"] == 7
    assert details["metadata"] == {"seed": 12}
    assert model_state_sha256(restored) == model_state_sha256(model)


def test_checkpoint_hash_mismatch_is_rejected(tmp_path: Path) -> None:
    model = TinyDecoderLM(_config())
    path = tmp_path / "model.pt"
    save_checkpoint(path, model=model, optimizer=None, step=0, metadata={})

    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        load_checkpoint(path, model=model, expected_sha256="0" * 64)
