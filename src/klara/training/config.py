"""Validated model and bounded-training configuration contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ModelConfig:
    """Architecture for the repository-native dense decoder language model."""

    vocab_size: int = 260
    hidden_size: int = 128
    num_layers: int = 4
    num_attention_heads: int = 4
    num_key_value_heads: int = 2
    intermediate_size: int = 384
    max_sequence_length: int = 128
    dropout: float = 0.0
    rms_norm_epsilon: float = 1e-6
    rope_theta: float = 10_000.0
    pad_token_id: int = 0
    bos_token_id: int = 1
    eos_token_id: int = 2
    tie_word_embeddings: bool = True

    def __post_init__(self) -> None:
        """Reject shapes that cannot form grouped rotary attention."""

        if self.vocab_size < 8:
            raise ValueError("vocab_size must be at least 8")
        if self.hidden_size < 16 or self.hidden_size % self.num_attention_heads:
            raise ValueError("hidden_size must be divisible by attention heads")
        if self.num_attention_heads % self.num_key_value_heads:
            raise ValueError("attention heads must be divisible by key/value heads")
        if (self.hidden_size // self.num_attention_heads) % 2:
            raise ValueError("attention head dimension must be even for RoPE")
        if self.num_layers < 1 or self.intermediate_size < self.hidden_size:
            raise ValueError("model depth and intermediate size must be positive")
        if self.max_sequence_length < 2:
            raise ValueError("max_sequence_length must be at least 2")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("dropout must be in [0, 1)")

    @property
    def head_dim(self) -> int:
        """Return the per-head hidden dimension."""

        return self.hidden_size // self.num_attention_heads

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible architecture manifest."""

        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ModelConfig":
        """Create a validated architecture from a TOML/JSON mapping."""

        return cls(**raw)


@dataclass(frozen=True)
class TrainConfig:
    """Small deterministic optimization budget suitable for local hardware."""

    seed: int = 20260811
    steps: int = 100
    batch_size: int = 4
    learning_rate: float = 0.002
    weight_decay: float = 0.01
    gradient_clip: float = 1.0
    precision: str = "fp32"
    device: str = "auto"
    loader_workers: int = 0

    def __post_init__(self) -> None:
        """Keep the mandatory run finite and portable on Windows."""

        if self.steps < 1 or self.batch_size < 1:
            raise ValueError("training steps and batch size must be positive")
        if self.learning_rate <= 0 or self.gradient_clip <= 0:
            raise ValueError("learning rate and gradient clip must be positive")
        if self.precision not in {"fp32", "fp16"}:
            raise ValueError("precision must be fp32 or fp16")
        if self.device not in {"auto", "cpu", "cuda"}:
            raise ValueError("device must be auto, cpu, or cuda")
        if self.loader_workers != 0:
            raise ValueError("the reproducible Windows loader uses zero workers")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible optimization manifest."""

        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "TrainConfig":
        """Create a validated optimization config from a mapping."""

        return cls(**raw)
