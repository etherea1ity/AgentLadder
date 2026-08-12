from __future__ import annotations

import torch

from klara.training.config import ModelConfig
from klara.training.model import TinyDecoderLM


torch.set_num_threads(1)


def _config() -> ModelConfig:
    return ModelConfig(
        hidden_size=32,
        num_layers=2,
        num_attention_heads=4,
        num_key_value_heads=2,
        intermediate_size=64,
        max_sequence_length=16,
    )


def test_model_shapes_loss_and_gradients_are_finite() -> None:
    torch.manual_seed(7)
    model = TinyDecoderLM(_config())
    input_ids = torch.tensor([[1, 10, 11, 12], [1, 12, 13, 2]])

    output = model(input_ids, labels=input_ids)
    assert output.logits.shape == (2, 4, 260)
    assert output.loss is not None and torch.isfinite(output.loss)
    assert output.auxiliary_loss is not None
    assert output.auxiliary_loss.item() == 0.0
    output.loss.backward()
    assert all(
        parameter.grad is None or torch.isfinite(parameter.grad).all()
        for parameter in model.parameters()
    )


def test_future_tokens_cannot_change_prefix_logits() -> None:
    torch.manual_seed(8)
    model = TinyDecoderLM(_config()).eval()
    first = torch.tensor([[1, 20, 21, 22, 23]])
    second = torch.tensor([[1, 20, 21, 90, 91]])

    with torch.inference_mode():
        first_logits = model(first).logits
        second_logits = model(second).logits

    assert torch.allclose(first_logits[:, :3], second_logits[:, :3], atol=1e-6)


def test_masked_padding_token_cannot_change_valid_logits() -> None:
    torch.manual_seed(9)
    model = TinyDecoderLM(_config()).eval()
    first = torch.tensor([[1, 20, 21, 80]])
    second = torch.tensor([[1, 20, 21, 99]])
    mask = torch.tensor([[1, 1, 1, 0]], dtype=torch.bool)

    with torch.inference_mode():
        first_logits = model(first, attention_mask=mask).logits
        second_logits = model(second, attention_mask=mask).logits

    assert torch.allclose(first_logits[:, :3], second_logits[:, :3], atol=1e-6)


def test_left_padding_preserves_rotary_positions_for_visible_tokens() -> None:
    torch.manual_seed(10)
    model = TinyDecoderLM(_config()).eval()
    unpadded = torch.tensor([[1, 20, 21]])
    padded = torch.tensor([[0, 1, 20, 21]])
    padded_mask = torch.tensor([[0, 1, 1, 1]], dtype=torch.bool)

    with torch.inference_mode():
        expected = model(unpadded).logits
        actual = model(padded, attention_mask=padded_mask).logits[:, 1:]

    assert torch.allclose(actual, expected, atol=1e-6)


def test_greedy_generation_is_bounded_and_deterministic() -> None:
    torch.manual_seed(11)
    model = TinyDecoderLM(_config()).eval()
    prompt = torch.tensor([[1, 20, 21]])

    first = model.generate(prompt, max_new_tokens=4)
    second = model.generate(prompt, max_new_tokens=4)

    assert first.shape == (1, 7)
    assert torch.equal(first, second)
