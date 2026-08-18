"""Correctness tests for the GQA KV-cache inference path.

The training ``generate`` recomputes the full context on every step; these
tests prove that the incremental cache path reproduces the same logits and
greedy token sequence on a random sparse-MoE model.
"""

from __future__ import annotations

import torch

from klara.inference.kv_cache import GQAKVCache, generate_with_cache
from klara.training.config import ModelConfig
from klara.training.moe import MoEConfig, build_moe_model


def _small_moe_model() -> tuple[object, ModelConfig]:
    config = ModelConfig(
        vocab_size=32,
        hidden_size=32,
        num_layers=2,
        num_attention_heads=4,
        num_key_value_heads=2,
        intermediate_size=48,
        max_sequence_length=64,
        dropout=0.0,
        tie_word_embeddings=True,
    )
    torch.manual_seed(20260816)
    model = build_moe_model(config, MoEConfig()).eval()
    return model, config


def test_prefill_logits_match_full_forward() -> None:
    model, config = _small_moe_model()
    input_ids = torch.randint(
        config.pad_token_id + 1,
        config.vocab_size,
        (2, 8),
    )
    attention_mask = torch.ones_like(input_ids, dtype=torch.bool)

    with torch.inference_mode():
        reference = model(input_ids, attention_mask=attention_mask).logits
        cache = GQAKVCache(model)
        cached = cache.prefill(model, input_ids, attention_mask=attention_mask).logits

    assert cached.shape == reference.shape
    assert torch.allclose(cached, reference, atol=1e-5, rtol=1e-5)


def test_incremental_decode_logits_match_full_forward() -> None:
    model, config = _small_moe_model()
    input_ids = torch.randint(
        config.pad_token_id + 1,
        config.vocab_size,
        (2, 5),
    )
    attention_mask = torch.ones_like(input_ids, dtype=torch.bool)
    cache = GQAKVCache(model)
    generated = input_ids

    with torch.inference_mode():
        cached_logits = cache.prefill(
            model,
            input_ids,
            attention_mask=attention_mask,
        ).logits
        for _ in range(6):
            next_token = cached_logits[:, -1].argmax(dim=-1, keepdim=True)
            generated = torch.cat((generated, next_token), dim=-1)
            reference = model(generated).logits[:, -1]
            decoded = cache.decode(
                model,
                next_token,
                attention_mask=torch.ones(
                    (input_ids.shape[0], 1),
                    dtype=torch.bool,
                    device=input_ids.device,
                ),
            )
            cached_logits = decoded.logits
            assert cached_logits.shape == (input_ids.shape[0], 1, config.vocab_size)
            assert torch.allclose(
                cached_logits[:, -1],
                reference,
                atol=1e-5,
                rtol=1e-5,
            )


def test_cached_generate_matches_reference_generate() -> None:
    model, config = _small_moe_model()
    input_ids = torch.randint(
        config.pad_token_id + 1,
        config.vocab_size,
        (2, 4),
    )

    with torch.inference_mode():
        reference_tokens = model.generate(input_ids, max_new_tokens=8)
        cached_tokens = generate_with_cache(model, input_ids, max_new_tokens=8)

    assert cached_tokens.shape == reference_tokens.shape
    assert torch.equal(cached_tokens, reference_tokens)
