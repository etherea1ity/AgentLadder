"""Incremental GQA KV-cache decoding for the Klara sparse MoE decoder.

This module deliberately does not modify the training model.  It replays the
tiny transformer block by block while keeping only the rotary pre-norm K/V
tensors needed by grouped-query attention.  ``prefill`` processes a prompt and
populates the cache; ``decode`` consumes exactly one token per batch row.
"""

from __future__ import annotations

import math
from typing import Any

import torch
from torch import nn
from torch.nn import functional as F

from klara.training.model import ModelOutput, TinyDecoderLM

KV_CACHE_SCHEMA_VERSION = "klara.inference.gqa-kv-cache.v1"


def _position_ids_from_mask(attention_mask: torch.Tensor) -> torch.Tensor:
    """Mirror the training model's padding-aware rotary positions."""

    return attention_mask.bool().long().cumsum(dim=-1).sub(1).clamp_min(0)


def _apply_rotary(
    tensor: torch.Tensor,
    position_ids: torch.Tensor,
    inverse_frequency: torch.Tensor,
) -> torch.Tensor:
    """Rotate even/odd head features with the model's RoPE convention."""

    frequencies = position_ids.float().unsqueeze(-1) * inverse_frequency
    cosine = frequencies.cos().unsqueeze(1).to(tensor.dtype)
    sine = frequencies.sin().unsqueeze(1).to(tensor.dtype)
    even = tensor[..., 0::2]
    odd = tensor[..., 1::2]
    rotated_even = even * cosine - odd * sine
    rotated_odd = even * sine + odd * cosine
    return torch.stack((rotated_even, rotated_odd), dim=-1).flatten(-2)


def _attention_with_cache(
    attention: nn.Module,
    hidden_states: torch.Tensor,
    *,
    current_mask: torch.Tensor,
    current_positions: torch.Tensor,
    full_mask: torch.Tensor,
    past_key: torch.Tensor | None,
    past_value: torch.Tensor | None,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Run one GQA attention head and return output plus current K/V."""

    config = attention.config
    batch_size, sequence_length, _ = hidden_states.shape
    query = attention.query(hidden_states).view(
        batch_size,
        sequence_length,
        config.num_attention_heads,
        config.head_dim,
    )
    key = attention.key(hidden_states).view(
        batch_size,
        sequence_length,
        config.num_key_value_heads,
        config.head_dim,
    )
    value = attention.value(hidden_states).view(
        batch_size,
        sequence_length,
        config.num_key_value_heads,
        config.head_dim,
    )
    query = attention.query_norm(query).transpose(1, 2)
    key = attention.key_norm(key).transpose(1, 2)
    value = value.transpose(1, 2)
    query = _apply_rotary(query, current_positions, attention.inverse_frequency)
    key = _apply_rotary(key, current_positions, attention.inverse_frequency)

    current_key = key
    current_value = value
    if past_key is not None:
        key = torch.cat((past_key, key), dim=2)
    if past_value is not None:
        value = torch.cat((past_value, value), dim=2)

    repeats = config.num_attention_heads // config.num_key_value_heads
    key = key.repeat_interleave(repeats, dim=1)
    value = value.repeat_interleave(repeats, dim=1)
    scores = torch.matmul(query, key.transpose(-2, -1)) / math.sqrt(config.head_dim)

    full_length = full_mask.shape[-1]
    past_length = full_length - sequence_length
    causal = torch.ones(
        sequence_length,
        full_length,
        dtype=torch.bool,
        device=hidden_states.device,
    )
    causal[:, past_length:] = torch.ones(
        sequence_length,
        sequence_length,
        dtype=torch.bool,
        device=hidden_states.device,
    ).tril()
    visible_keys = full_mask.bool()[:, None, None, :]
    allowed = visible_keys & causal[None, :, :]
    scores = scores.masked_fill(~allowed, torch.finfo(scores.dtype).min)

    probabilities = F.softmax(scores.float(), dim=-1).to(query.dtype)
    probabilities = attention.dropout(probabilities)
    attended = torch.matmul(probabilities, value)
    attended = attended.transpose(1, 2).reshape(
        batch_size,
        sequence_length,
        config.hidden_size,
    )
    attended = attended * current_mask.unsqueeze(-1).to(attended.dtype)
    return attention.output(attended), current_key, current_value


class GQAKVCache:
    """Per-layer cache for grouped-query attention K/V tensors.

    The cache stores the already-projected, RMS-normed, and RoPE-rotated
    key/value tensors, matching what ``RotarySelfAttention`` consumes during
    score computation.  The full boolean attention mask is also retained so
    that padded historical tokens remain invisible.
    """

    def __init__(self, model: TinyDecoderLM) -> None:
        """Create empty per-layer storage for ``model``."""

        if not isinstance(model, TinyDecoderLM):
            raise TypeError("GQAKVCache requires a TinyDecoderLM model")
        self.num_layers = len(model.blocks)
        self.keys: list[torch.Tensor | None] = [None] * self.num_layers
        self.values: list[torch.Tensor | None] = [None] * self.num_layers
        self.attention_mask: torch.Tensor | None = None
        self.schema_version = KV_CACHE_SCHEMA_VERSION

    @property
    def past_length(self) -> int:
        """Return the number of cached tokens for every batch row."""

        if self.attention_mask is None:
            return 0
        return int(self.attention_mask.shape[-1])

    def reset(self) -> None:
        """Drop all cached tensors."""

        self.keys = [None] * self.num_layers
        self.values = [None] * self.num_layers
        self.attention_mask = None

    @torch.inference_mode()
    def prefill(
        self,
        model: TinyDecoderLM,
        input_ids: torch.Tensor,
        *,
        attention_mask: torch.Tensor | None = None,
    ) -> ModelOutput:
        """Process a whole prompt and populate the cache."""

        if input_ids.ndim != 2:
            raise ValueError("input_ids must have shape [batch, sequence]")
        if self.attention_mask is not None:
            raise RuntimeError("GQAKVCache already contains a prompt; call reset() first")
        if attention_mask is None:
            attention_mask = input_ids.ne(model.config.pad_token_id)
        if attention_mask.shape != input_ids.shape:
            raise ValueError("attention_mask must match input_ids")
        if input_ids.shape[1] > model.config.max_sequence_length:
            raise ValueError("input sequence exceeds configured maximum")
        return self._forward(
            model,
            input_ids,
            attention_mask=attention_mask.bool(),
        )

    @torch.inference_mode()
    def decode(
        self,
        model: TinyDecoderLM,
        input_ids: torch.Tensor,
        *,
        attention_mask: torch.Tensor | None = None,
    ) -> ModelOutput:
        """Process one new token per batch row against the cached prompt."""

        if input_ids.ndim != 2 or input_ids.shape[1] != 1:
            raise ValueError("decode expects input_ids with shape [batch, 1]")
        if self.attention_mask is None:
            raise RuntimeError("prefill must run before decode")
        if attention_mask is None:
            attention_mask = input_ids.ne(model.config.pad_token_id)
        if attention_mask.shape != input_ids.shape:
            raise ValueError("attention_mask must match input_ids")
        new_length = self.past_length + 1
        if new_length > model.config.max_sequence_length:
            raise ValueError("cached sequence exceeds configured maximum")
        return self._forward(
            model,
            input_ids,
            attention_mask=attention_mask.bool(),
        )

    def _forward(
        self,
        model: TinyDecoderLM,
        input_ids: torch.Tensor,
        *,
        attention_mask: torch.Tensor,
    ) -> ModelOutput:
        """Replay the model layers with past keys/values spliced into attention."""

        batch_size, sequence_length = input_ids.shape
        current_mask = attention_mask.bool()
        past_mask = self.attention_mask
        if past_mask is None:
            full_mask = current_mask
        else:
            full_mask = torch.cat((past_mask, current_mask), dim=1)
        full_positions = _position_ids_from_mask(full_mask)
        current_positions = full_positions[:, -sequence_length:]

        hidden_states = model.embedding_dropout(model.token_embedding(input_ids))
        auxiliary_losses: list[torch.Tensor] = []
        routing_totals: dict[str, torch.Tensor] = {}
        next_keys: list[torch.Tensor | None] = [None] * self.num_layers
        next_values: list[torch.Tensor | None] = [None] * self.num_layers

        for index, block in enumerate(model.blocks):
            attention_output, current_key, current_value = _attention_with_cache(
                block.attention,
                block.attention_norm(hidden_states),
                current_mask=current_mask,
                current_positions=current_positions,
                full_mask=full_mask,
                past_key=self.keys[index],
                past_value=self.values[index],
            )
            hidden_states = hidden_states + attention_output
            feed_forward_output = block.feed_forward(
                block.feed_forward_norm(hidden_states),
                current_mask,
            )
            hidden_states = hidden_states + feed_forward_output.hidden_states
            auxiliary_losses.append(feed_forward_output.auxiliary_loss)
            for key, value in feed_forward_output.routing_metrics.items():
                routing_totals[key] = (
                    routing_totals.get(key, value.new_zeros(())) + value
                )
            next_keys[index] = (
                torch.cat((self.keys[index], current_key), dim=2)
                if self.keys[index] is not None
                else current_key
            )
            next_values[index] = (
                torch.cat((self.values[index], current_value), dim=2)
                if self.values[index] is not None
                else current_value
            )

        self.keys = next_keys
        self.values = next_values
        self.attention_mask = full_mask

        hidden_states = model.final_norm(hidden_states)
        logits = model.lm_head(hidden_states).float()
        auxiliary_loss = torch.stack(auxiliary_losses).sum()
        return ModelOutput(
            logits=logits,
            auxiliary_loss=auxiliary_loss,
            hidden_states=hidden_states,
            routing_metrics=routing_totals,
        )


@torch.inference_mode()
def generate_with_cache(
    model: TinyDecoderLM,
    input_ids: torch.Tensor,
    *,
    max_new_tokens: int,
    eos_token_id: int | None = None,
    attention_mask: torch.Tensor | None = None,
    return_cache: bool = False,
) -> torch.Tensor | tuple[torch.Tensor, GQAKVCache]:
    """Greedily generate tokens using the incremental KV cache.

    Set ``return_cache=True`` when callers need the populated cache after
    generation, for example to inspect or continue decoding.
    """

    if max_new_tokens < 0:
        raise ValueError("max_new_tokens must not be negative")
    if attention_mask is None:
        attention_mask = input_ids.ne(model.config.pad_token_id)
    cache = GQAKVCache(model)
    output = cache.prefill(model, input_ids, attention_mask=attention_mask)
    generated = input_ids
    batch_size = input_ids.shape[0]
    device = input_ids.device
    for _ in range(max_new_tokens):
        next_token = output.logits[:, -1].argmax(dim=-1, keepdim=True)
        generated = torch.cat((generated, next_token), dim=-1)
        output = cache.decode(
            model,
            next_token,
            attention_mask=torch.ones(
                (batch_size, 1),
                dtype=torch.bool,
                device=device,
            ),
        )
        if eos_token_id is not None and bool(next_token.eq(eos_token_id).all()):
            break
    if return_cache:
        return generated, cache
    return generated


def cache_memory_bytes(cache: GQAKVCache) -> int:
    """Return bytes occupied by cached K/V tensors (and the stored mask)."""

    total = 0
    for tensor in (*cache.keys, *cache.values, cache.attention_mask):
        if tensor is not None:
            total += int(tensor.numel() * tensor.element_size())
    return total

