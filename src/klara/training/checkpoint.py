"""Atomic, hash-verified checkpoints for tiny training experiments."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import torch

from klara.training.config import ModelConfig
from klara.training.model import TinyDecoderLM


CHECKPOINT_FORMAT = "klara.tiny-lm.checkpoint.v1"


def file_sha256(path: Path) -> str:
    """Hash a file in bounded chunks."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        # Avoid loading future larger checkpoints into memory only to hash them.
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def save_checkpoint(
    path: Path,
    *,
    model: TinyDecoderLM,
    optimizer: torch.optim.Optimizer | None,
    step: int,
    metadata: dict[str, Any],
) -> str:
    """Atomically save model/training state and return the file SHA-256."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    payload = {
        "format": CHECKPOINT_FORMAT,
        "model_config": model.config.to_dict(),
        "model_state": {
            key: value.detach().cpu() for key, value in model.state_dict().items()
        },
        "optimizer_state": optimizer.state_dict() if optimizer is not None else None,
        "step": step,
        "metadata": metadata,
    }
    torch.save(payload, temporary_path)
    temporary_path.replace(path)
    return file_sha256(path)


def load_checkpoint(
    path: Path,
    *,
    model: TinyDecoderLM,
    optimizer: torch.optim.Optimizer | None = None,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Verify, load, and strictly restore one checkpoint."""

    actual_hash = file_sha256(path)
    if expected_sha256 is not None and actual_hash != expected_sha256:
        raise ValueError("checkpoint SHA-256 mismatch")
    payload = torch.load(path, map_location="cpu", weights_only=False)
    if not isinstance(payload, dict) or payload.get("format") != CHECKPOINT_FORMAT:
        raise ValueError("unsupported checkpoint format")
    saved_config = ModelConfig.from_dict(dict(payload.get("model_config", {})))
    if saved_config != model.config:
        raise ValueError("checkpoint model config does not match target model")
    model.load_state_dict(payload["model_state"], strict=True)
    if optimizer is not None and payload.get("optimizer_state") is not None:
        optimizer.load_state_dict(payload["optimizer_state"])
    return {
        "sha256": actual_hash,
        "step": int(payload.get("step", 0)),
        "metadata": dict(payload.get("metadata", {})),
    }
