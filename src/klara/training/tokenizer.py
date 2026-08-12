"""Deterministic UTF-8 byte tokenizer with a fixed portable vocabulary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class ByteTokenizer:
    """Map UTF-8 bytes to IDs without an external vocabulary dependency."""

    pad_token_id: int = 0
    bos_token_id: int = 1
    eos_token_id: int = 2
    unknown_token_id: int = 3
    byte_offset: int = 4

    @property
    def vocab_size(self) -> int:
        """Return four special tokens plus every possible byte."""

        return self.byte_offset + 256

    def encode(
        self,
        text: str,
        *,
        add_bos: bool = True,
        add_eos: bool = True,
    ) -> list[int]:
        """Encode Unicode text through its deterministic UTF-8 bytes."""

        token_ids = [self.byte_offset + value for value in text.encode("utf-8")]
        if add_bos:
            token_ids.insert(0, self.bos_token_id)
        if add_eos:
            token_ids.append(self.eos_token_id)
        return token_ids

    def decode(self, token_ids: Iterable[int], *, skip_special: bool = True) -> str:
        """Decode token IDs and replace incomplete UTF-8 sequences safely."""

        byte_values = bytearray()
        specials = {
            self.pad_token_id,
            self.bos_token_id,
            self.eos_token_id,
            self.unknown_token_id,
        }
        # Preserve byte order while omitting control tokens from user text.
        for token_id in token_ids:
            if token_id in specials:
                if skip_special:
                    continue
                if token_id == self.unknown_token_id:
                    byte_values.extend("�".encode("utf-8"))
                continue
            byte_value = token_id - self.byte_offset
            if 0 <= byte_value <= 255:
                byte_values.append(byte_value)
            elif not skip_special:
                byte_values.extend("�".encode("utf-8"))
        return byte_values.decode("utf-8", errors="replace")
