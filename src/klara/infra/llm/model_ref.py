"""Provider/model reference parsing for Klara LLM routing."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelRef:
    """Provider/model pair encoded as `provider/model`."""

    # Provider id, such as deepseek or qwen.
    provider: str
    # Provider-local model id, such as deepseek-v4-flash.
    model: str

    @classmethod
    def parse(cls, value: str) -> "ModelRef":
        """Parse a configured model reference.

        Args:
            value: Model reference in `provider/model` format.

        Returns:
            Parsed provider/model pair.

        Raises:
            ValueError: If the reference is malformed.
        """

        provider, sep, model = value.partition("/")
        if not sep or not provider.strip() or not model.strip():
            raise ValueError(f"invalid model ref: {value!r}")
        return cls(provider=provider.strip(), model=model.strip())

    def __str__(self) -> str:
        """Return the normalized provider/model reference."""

        return f"{self.provider}/{self.model}"
