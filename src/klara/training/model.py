"""Small decoder-only Transformer implemented directly with PyTorch."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import math

import torch
from torch import nn
from torch.nn import functional as F

from klara.training.config import ModelConfig


@dataclass(frozen=True)
class FeedForwardOutput:
    """Shared dense/MoE block output used by later sparse experiments."""

    hidden_states: torch.Tensor
    auxiliary_loss: torch.Tensor
    routing_metrics: dict[str, torch.Tensor] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelOutput:
    """Language-model logits, losses, and optional routing observations."""

    logits: torch.Tensor
    loss: torch.Tensor | None = None
    language_model_loss: torch.Tensor | None = None
    auxiliary_loss: torch.Tensor | None = None
    hidden_states: torch.Tensor | None = None
    routing_metrics: dict[str, torch.Tensor] = field(default_factory=dict)


class RMSNorm(nn.Module):
    """Root-mean-square normalization without mean centering."""

    def __init__(self, size: int, epsilon: float) -> None:
        """Create one learned scale vector."""

        super().__init__()
        self.epsilon = epsilon
        self.weight = nn.Parameter(torch.ones(size))

    def forward(self, hidden_states: torch.Tensor) -> torch.Tensor:
        """Normalize in FP32 and restore the input dtype."""

        normalized = hidden_states.float()
        normalized = normalized * torch.rsqrt(
            normalized.square().mean(dim=-1, keepdim=True) + self.epsilon
        )
        return (normalized * self.weight.float()).to(hidden_states.dtype)


class RotarySelfAttention(nn.Module):
    """Causal grouped-query attention with padding-aware rotary positions."""

    def __init__(self, config: ModelConfig) -> None:
        """Create query, grouped key/value, and output projections."""

        super().__init__()
        self.config = config
        self.query = nn.Linear(
            config.hidden_size,
            config.num_attention_heads * config.head_dim,
            bias=False,
        )
        self.key = nn.Linear(
            config.hidden_size,
            config.num_key_value_heads * config.head_dim,
            bias=False,
        )
        self.value = nn.Linear(
            config.hidden_size,
            config.num_key_value_heads * config.head_dim,
            bias=False,
        )
        self.output = nn.Linear(config.hidden_size, config.hidden_size, bias=False)
        self.query_norm = RMSNorm(config.head_dim, config.rms_norm_epsilon)
        self.key_norm = RMSNorm(config.head_dim, config.rms_norm_epsilon)
        self.dropout = nn.Dropout(config.dropout)
        inverse_frequency = 1.0 / (
            config.rope_theta
            ** (torch.arange(0, config.head_dim, 2, dtype=torch.float32) / config.head_dim)
        )
        self.register_buffer("inverse_frequency", inverse_frequency, persistent=False)

    def forward(
        self,
        hidden_states: torch.Tensor,
        *,
        attention_mask: torch.Tensor,
        position_ids: torch.Tensor,
    ) -> torch.Tensor:
        """Attend only to visible keys at the current or earlier position."""

        batch_size, sequence_length, _ = hidden_states.shape
        query = self.query(hidden_states).view(
            batch_size,
            sequence_length,
            self.config.num_attention_heads,
            self.config.head_dim,
        )
        key = self.key(hidden_states).view(
            batch_size,
            sequence_length,
            self.config.num_key_value_heads,
            self.config.head_dim,
        )
        value = self.value(hidden_states).view(
            batch_size,
            sequence_length,
            self.config.num_key_value_heads,
            self.config.head_dim,
        )
        query = self.query_norm(query).transpose(1, 2)
        key = self.key_norm(key).transpose(1, 2)
        value = value.transpose(1, 2)
        query = _apply_rotary(query, position_ids, self.inverse_frequency)
        key = _apply_rotary(key, position_ids, self.inverse_frequency)

        repeats = self.config.num_attention_heads // self.config.num_key_value_heads
        key = key.repeat_interleave(repeats, dim=1)
        value = value.repeat_interleave(repeats, dim=1)
        scores = torch.matmul(query, key.transpose(-2, -1)) / math.sqrt(
            self.config.head_dim
        )
        causal = torch.ones(
            sequence_length,
            sequence_length,
            dtype=torch.bool,
            device=hidden_states.device,
        ).tril()
        visible_keys = attention_mask[:, None, None, :].bool()
        allowed = causal[None, None, :, :] & visible_keys
        scores = scores.masked_fill(~allowed, torch.finfo(scores.dtype).min)
        probabilities = F.softmax(scores.float(), dim=-1).to(query.dtype)
        probabilities = self.dropout(probabilities)
        attended = torch.matmul(probabilities, value)
        attended = attended.transpose(1, 2).reshape(
            batch_size,
            sequence_length,
            self.config.hidden_size,
        )
        attended = attended * attention_mask.unsqueeze(-1).to(attended.dtype)
        return self.output(attended)


class DenseFeedForward(nn.Module):
    """SwiGLU-style dense feed-forward block."""

    def __init__(self, config: ModelConfig) -> None:
        """Create gated expansion and down projection."""

        super().__init__()
        self.gate = nn.Linear(config.hidden_size, config.intermediate_size, bias=False)
        self.up = nn.Linear(config.hidden_size, config.intermediate_size, bias=False)
        self.down = nn.Linear(config.intermediate_size, config.hidden_size, bias=False)

    def forward(
        self,
        hidden_states: torch.Tensor,
        token_mask: torch.Tensor,
    ) -> FeedForwardOutput:
        """Apply the dense gated MLP and return a zero auxiliary loss."""

        output = self.down(F.silu(self.gate(hidden_states)) * self.up(hidden_states))
        output = output * token_mask.unsqueeze(-1).to(output.dtype)
        return FeedForwardOutput(
            hidden_states=output,
            auxiliary_loss=hidden_states.new_zeros(()),
        )


FeedForwardFactory = Callable[[ModelConfig, int], nn.Module]


class DecoderBlock(nn.Module):
    """Pre-normalized attention and replaceable dense/sparse feed-forward block."""

    def __init__(
        self,
        config: ModelConfig,
        layer_index: int,
        feed_forward_factory: FeedForwardFactory | None = None,
    ) -> None:
        """Create a block while keeping the later MoE insertion point explicit."""

        super().__init__()
        self.attention_norm = RMSNorm(config.hidden_size, config.rms_norm_epsilon)
        self.attention = RotarySelfAttention(config)
        self.feed_forward_norm = RMSNorm(config.hidden_size, config.rms_norm_epsilon)
        self.feed_forward = (
            feed_forward_factory(config, layer_index)
            if feed_forward_factory is not None
            else DenseFeedForward(config)
        )

    def forward(
        self,
        hidden_states: torch.Tensor,
        *,
        attention_mask: torch.Tensor,
        position_ids: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, dict[str, torch.Tensor]]:
        """Apply residual attention and the configured token mixer."""

        hidden_states = hidden_states + self.attention(
            self.attention_norm(hidden_states),
            attention_mask=attention_mask,
            position_ids=position_ids,
        )
        feed_forward_output = self.feed_forward(
            self.feed_forward_norm(hidden_states),
            attention_mask,
        )
        hidden_states = hidden_states + feed_forward_output.hidden_states
        return (
            hidden_states,
            feed_forward_output.auxiliary_loss,
            feed_forward_output.routing_metrics,
        )


class TinyDecoderLM(nn.Module):
    """A small decoder-only byte language model owned by the training layer."""

    def __init__(
        self,
        config: ModelConfig,
        *,
        feed_forward_factory: FeedForwardFactory | None = None,
    ) -> None:
        """Build embeddings, decoder blocks, final norm, and tied LM head."""

        super().__init__()
        self.config = config
        self.token_embedding = nn.Embedding(
            config.vocab_size,
            config.hidden_size,
            padding_idx=config.pad_token_id,
        )
        self.embedding_dropout = nn.Dropout(config.dropout)
        self.blocks = nn.ModuleList(
            DecoderBlock(config, index, feed_forward_factory)
            for index in range(config.num_layers)
        )
        self.final_norm = RMSNorm(config.hidden_size, config.rms_norm_epsilon)
        self.lm_head = nn.Linear(config.hidden_size, config.vocab_size, bias=False)
        self.apply(self._initialize_weights)
        if config.tie_word_embeddings:
            self.lm_head.weight = self.token_embedding.weight

    @staticmethod
    def _initialize_weights(module: nn.Module) -> None:
        """Use a small normal initialization and exact zero padding row."""

        if isinstance(module, (nn.Linear, nn.Embedding)):
            nn.init.normal_(module.weight, mean=0.0, std=0.02)
            if isinstance(module, nn.Embedding) and module.padding_idx is not None:
                with torch.no_grad():
                    module.weight[module.padding_idx].zero_()

    def forward(
        self,
        input_ids: torch.Tensor,
        *,
        attention_mask: torch.Tensor | None = None,
        labels: torch.Tensor | None = None,
    ) -> ModelOutput:
        """Compute causal logits and optional next-token cross entropy."""

        if input_ids.ndim != 2:
            raise ValueError("input_ids must have shape [batch, sequence]")
        batch_size, sequence_length = input_ids.shape
        if sequence_length > self.config.max_sequence_length:
            raise ValueError("input sequence exceeds configured maximum")
        if attention_mask is None:
            attention_mask = input_ids.ne(self.config.pad_token_id)
        if attention_mask.shape != (batch_size, sequence_length):
            raise ValueError("attention_mask must match input_ids")
        attention_mask = attention_mask.bool()
        position_ids = attention_mask.long().cumsum(dim=-1).sub(1).clamp_min(0)
        hidden_states = self.embedding_dropout(self.token_embedding(input_ids))
        auxiliary_losses: list[torch.Tensor] = []
        routing_totals: dict[str, torch.Tensor] = {}
        # Every block shares the same visibility and derived rotary positions.
        for block in self.blocks:
            hidden_states, auxiliary_loss, routing_metrics = block(
                hidden_states,
                attention_mask=attention_mask,
                position_ids=position_ids,
            )
            auxiliary_losses.append(auxiliary_loss)
            for key, value in routing_metrics.items():
                routing_totals[key] = routing_totals.get(key, value.new_zeros(())) + value
        hidden_states = self.final_norm(hidden_states)
        logits = self.lm_head(hidden_states).float()
        auxiliary_loss = torch.stack(auxiliary_losses).sum()
        language_model_loss = None
        total_loss = None
        if labels is not None:
            if labels.shape != input_ids.shape:
                raise ValueError("labels must match input_ids")
            language_model_loss = F.cross_entropy(
                logits.reshape(-1, logits.shape[-1]),
                labels.reshape(-1),
                ignore_index=-100,
            )
            total_loss = language_model_loss + auxiliary_loss
        return ModelOutput(
            logits=logits,
            loss=total_loss,
            language_model_loss=language_model_loss,
            auxiliary_loss=auxiliary_loss,
            hidden_states=hidden_states,
            routing_metrics=routing_totals,
        )

    @torch.inference_mode()
    def generate(
        self,
        input_ids: torch.Tensor,
        *,
        max_new_tokens: int,
        eos_token_id: int | None = None,
    ) -> torch.Tensor:
        """Greedily extend tokens without an external generation library."""

        if max_new_tokens < 0:
            raise ValueError("max_new_tokens must not be negative")
        generated = input_ids
        # Recompute the tiny context each step to keep the reference path simple.
        for _ in range(max_new_tokens):
            context = generated[:, -self.config.max_sequence_length :]
            output = self(context, attention_mask=context.ne(self.config.pad_token_id))
            next_token = output.logits[:, -1].argmax(dim=-1, keepdim=True)
            generated = torch.cat((generated, next_token), dim=-1)
            if eos_token_id is not None and bool(next_token.eq(eos_token_id).all()):
                break
        return generated


def _apply_rotary(
    tensor: torch.Tensor,
    position_ids: torch.Tensor,
    inverse_frequency: torch.Tensor,
) -> torch.Tensor:
    """Rotate even/odd head features at padding-aware token positions."""

    frequencies = position_ids.float().unsqueeze(-1) * inverse_frequency
    cosine = frequencies.cos().unsqueeze(1).to(tensor.dtype)
    sine = frequencies.sin().unsqueeze(1).to(tensor.dtype)
    even = tensor[..., 0::2]
    odd = tensor[..., 1::2]
    rotated_even = even * cosine - odd * sine
    rotated_odd = even * sine + odd * cosine
    return torch.stack((rotated_even, rotated_odd), dim=-1).flatten(-2)
