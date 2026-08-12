"""Deterministic causal batches for the tiny language-model experiments."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import torch

from klara.training.tokenizer import ByteTokenizer


IGNORE_INDEX = -100


@dataclass(frozen=True)
class CausalBatch:
    """One padded batch of inputs, next-byte labels, and key visibility."""

    input_ids: torch.Tensor
    labels: torch.Tensor
    attention_mask: torch.Tensor

    def to(self, device: torch.device) -> "CausalBatch":
        """Move all tensors to one execution device."""

        return CausalBatch(
            input_ids=self.input_ids.to(device),
            labels=self.labels.to(device),
            attention_mask=self.attention_mask.to(device),
        )


def read_corpus(path: Path) -> tuple[str, ...]:
    """Read non-empty corpus lines without reordering them."""

    lines = tuple(
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    if not lines:
        raise ValueError("training corpus must contain non-empty text")
    return lines


def build_causal_batches(
    texts: tuple[str, ...] | list[str],
    tokenizer: ByteTokenizer,
    *,
    sequence_length: int,
    batch_size: int,
) -> tuple[CausalBatch, ...]:
    """Pack text into fixed causal blocks and deterministic sequential batches."""

    if sequence_length < 2 or batch_size < 1:
        raise ValueError("sequence_length and batch_size must be positive")
    token_stream: list[int] = []
    # Each line gets explicit boundaries so unrelated examples do not merge silently.
    for text in texts:
        token_stream.extend(tokenizer.encode(text, add_bos=True, add_eos=True))
    if len(token_stream) < 2:
        raise ValueError("training corpus must produce at least two tokens")

    rows: list[tuple[list[int], list[int], list[int]]] = []
    stride = sequence_length
    # One extra token supplies the next-token label for every visible position.
    for start in range(0, len(token_stream) - 1, stride):
        window = token_stream[start : start + sequence_length + 1]
        inputs = window[:-1]
        labels = window[1:]
        if not inputs:
            continue
        visible = [1] * len(inputs)
        pad_count = sequence_length - len(inputs)
        inputs.extend([tokenizer.pad_token_id] * pad_count)
        labels.extend([IGNORE_INDEX] * pad_count)
        visible.extend([0] * pad_count)
        rows.append((inputs, labels, visible))
    if not rows:
        raise ValueError("training corpus produced no causal rows")

    batches: list[CausalBatch] = []
    # Preserve row order; the trainer alone owns seeded epoch permutations.
    for start in range(0, len(rows), batch_size):
        selected = rows[start : start + batch_size]
        batches.append(
            CausalBatch(
                input_ids=torch.tensor(
                    [row[0] for row in selected],
                    dtype=torch.long,
                ),
                labels=torch.tensor(
                    [row[1] for row in selected],
                    dtype=torch.long,
                ),
                attention_mask=torch.tensor(
                    [row[2] for row in selected],
                    dtype=torch.bool,
                ),
            )
        )
    return tuple(batches)
