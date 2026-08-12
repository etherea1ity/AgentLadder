from __future__ import annotations

import torch

from klara.training.data import IGNORE_INDEX, build_causal_batches
from klara.training.tokenizer import ByteTokenizer


def test_byte_tokenizer_round_trips_multilingual_text() -> None:
    tokenizer = ByteTokenizer()
    text = "Klara 证据 ✓"

    token_ids = tokenizer.encode(text)

    assert tokenizer.vocab_size == 260
    assert token_ids[0] == tokenizer.bos_token_id
    assert token_ids[-1] == tokenizer.eos_token_id
    assert tokenizer.decode(token_ids) == text


def test_causal_batches_have_inputs_next_tokens_and_padding_mask() -> None:
    tokenizer = ByteTokenizer()

    batches = build_causal_batches(
        ["abc"],
        tokenizer,
        sequence_length=8,
        batch_size=2,
    )

    batch = batches[0]
    assert batch.input_ids.shape == (1, 8)
    assert batch.labels.shape == (1, 8)
    assert batch.attention_mask.dtype == torch.bool
    assert batch.labels[0, 0] == tokenizer.byte_offset + ord("a")
    assert batch.labels[0, -1] == IGNORE_INDEX
    assert batch.attention_mask[0].tolist() == [True] * 4 + [False] * 4


def test_causal_batch_export_is_deterministic() -> None:
    tokenizer = ByteTokenizer()

    first = build_causal_batches(
        ["same input", "same input"],
        tokenizer,
        sequence_length=8,
        batch_size=2,
    )
    second = build_causal_batches(
        ["same input", "same input"],
        tokenizer,
        sequence_length=8,
        batch_size=2,
    )

    assert len(first) == len(second)
    assert all(
        torch.equal(left.input_ids, right.input_ids)
        and torch.equal(left.labels, right.labels)
        and torch.equal(left.attention_mask, right.attention_mask)
        for left, right in zip(first, second, strict=True)
    )
