"""Deterministic byte-level BPE tokenizer for the Klara MoE pretraining lane.

The tokenizer keeps the same special-token layout as :class:`ByteTokenizer`
(pad=0, bos=1, eos=2, unk=3, first byte=4) so callers can continue using the
existing model configuration conventions.  Byte tokens occupy IDs
``byte_offset .. byte_offset + 255``; learned merge symbols follow them in
merge rank order.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import heapq
import json
from pathlib import Path
from typing import Iterable

BPETOKENIZER_VERSION = "klara.byte-bpe.v1"
_BYTE_TOKEN_COUNT = 256


def _iter_texts(texts: Iterable[str]) -> list[bytes]:
    """Return non-empty UTF-8 byte strings in corpus order."""

    return [text.encode("utf-8") for text in texts if text]


@dataclass(frozen=True)
class _TrainingStats:
    """Small training diagnostic returned for CLI/report output."""

    target_vocab_size: int
    actual_vocab_size: int
    merge_count: int
    corpus_bytes: int
    corpus_lines: int


class BPETokenizer:
    """Byte-level BPE tokenizer with stable vocab/merge files."""

    def __init__(
        self,
        *,
        pad_token_id: int = 0,
        bos_token_id: int = 1,
        eos_token_id: int = 2,
        unknown_token_id: int = 3,
        byte_offset: int = 4,
        merges: tuple[tuple[int, int], ...] = (),
    ) -> None:
        """Create a tokenizer and precompute merge lookup tables."""

        self.pad_token_id = pad_token_id
        self.bos_token_id = bos_token_id
        self.eos_token_id = eos_token_id
        self.unknown_token_id = unknown_token_id
        self.byte_offset = byte_offset
        self.merges = tuple(merges)
        self._special_ids = {
            pad_token_id,
            bos_token_id,
            eos_token_id,
            unknown_token_id,
        }
        self._merge_rank = {
            pair: rank for rank, pair in enumerate(self.merges)
        }
        self._merge_symbol_start = self.byte_offset + _BYTE_TOKEN_COUNT
        self._symbol_to_bytes: dict[int, bytes] = {}
        for value in range(_BYTE_TOKEN_COUNT):
            self._symbol_to_bytes[self.byte_offset + value] = bytes((value,))
        for rank, (left, right) in enumerate(self.merges):
            symbol_id = self._merge_symbol_start + rank
            left_bytes = self._symbol_to_bytes[left]
            right_bytes = self._symbol_to_bytes[right]
            self._symbol_to_bytes[symbol_id] = left_bytes + right_bytes

    @property
    def vocab_size(self) -> int:
        """Return four special tokens plus bytes plus learned merges."""

        return self._merge_symbol_start + len(self.merges)

    @property
    def special_token_ids(self) -> tuple[int, ...]:
        """Return the reserved control token IDs in a stable order."""

        return (
            self.pad_token_id,
            self.bos_token_id,
            self.eos_token_id,
            self.unknown_token_id,
        )

    # ------------------------------------------------------------------
    # Encoding / decoding
    # ------------------------------------------------------------------
    def encode(
        self,
        text: str,
        *,
        add_bos: bool = True,
        add_eos: bool = True,
    ) -> list[int]:
        """Encode text into byte BPE token IDs with optional BOS/EOS."""

        symbols = [
            self.byte_offset + value for value in text.encode("utf-8")
        ]
        symbols = self._merge_symbols(symbols)
        if add_bos:
            symbols.insert(0, self.bos_token_id)
        if add_eos:
            symbols.append(self.eos_token_id)
        return symbols

    def decode(self, token_ids: Iterable[int], *, skip_special: bool = True) -> str:
        """Decode token IDs back to Unicode text."""

        byte_values = bytearray()
        for token_id in token_ids:
            if token_id in self._special_ids:
                if skip_special:
                    continue
                if token_id == self.unknown_token_id:
                    byte_values.extend("�".encode("utf-8"))
                continue
            byte_values.extend(self._token_to_bytes(token_id))
        return byte_values.decode("utf-8", errors="replace")

    def _token_to_bytes(self, token_id: int) -> bytes:
        """Expand one token ID into its byte sequence safely."""

        stack = [token_id]
        out = bytearray()
        while stack:
            symbol = stack.pop()
            if symbol in self._special_ids:
                out.extend("�".encode("utf-8"))
                continue
            value = self._symbol_to_bytes.get(symbol)
            if value is None:
                out.extend("�".encode("utf-8"))
                continue
            out.extend(value)
        return bytes(out)

    def _merge_symbols(self, symbols: list[int]) -> list[int]:
        """Apply learned merges in rank order using a priority queue.

        The queue keeps adjacent pairs keyed by their smallest merge rank.
        Invalidated entries are discarded lazily by re-checking the linked-list
        neighbours and values.
        """

        count = len(symbols)
        if count < 2 or not self._merge_rank:
            return symbols
        previous = list(range(-1, count - 1))
        following = list(range(1, count)) + [-1]
        alive = [True] * count
        values = list(symbols)
        rank_of = self._merge_rank
        inf = len(self.merges) + 1
        queue: list[tuple[int, int, int, int, int]] = []
        for left in range(count - 1):
            right = left + 1
            rank = rank_of.get((values[left], values[right]), inf)
            if rank < inf:
                heapq.heappush(
                    queue,
                    (rank, left, right, values[left], values[right]),
                )

        while queue:
            rank, left, right, left_value, right_value = heapq.heappop(queue)
            if not (
                alive[left]
                and alive[right]
                and following[left] == right
                and values[left] == left_value
                and values[right] == right_value
                and rank_of.get((left_value, right_value), inf) == rank
            ):
                continue
            merged_symbol = self._merge_symbol_start + rank
            previous_node = previous[left]
            following_node = following[right]
            alive[right] = False
            values[left] = merged_symbol
            following[left] = following_node
            if following_node >= 0:
                previous[following_node] = left
            if previous_node >= 0:
                following[previous_node] = left
                pair = (values[previous_node], values[left])
                new_rank = rank_of.get(pair, inf)
                if new_rank < inf:
                    heapq.heappush(
                        queue,
                        (
                            new_rank,
                            previous_node,
                            left,
                            values[previous_node],
                            values[left],
                        ),
                    )
            if following_node >= 0:
                pair = (values[left], values[following_node])
                new_rank = rank_of.get(pair, inf)
                if new_rank < inf:
                    heapq.heappush(
                        queue,
                        (
                            new_rank,
                            left,
                            following_node,
                            values[left],
                            values[following_node],
                        ),
                    )

        result: list[int] = []
        node = 0
        while node >= 0:
            if alive[node]:
                result.append(values[node])
            node = following[node]
        return result

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------
    def train_from_texts(
        self,
        texts: Iterable[str],
        *,
        target_vocab_size: int,
    ) -> _TrainingStats:
        """Train byte-pair merges and replace this tokenizer's merge table.

        The trainer is intentionally self-contained and deterministic.  It is
        suitable for local corpora and smoke tests; for very large corpora the
        corpus-preprocessing CLI can be run once on a machine with enough CPU.
        """

        byte_strings = _iter_texts(texts)
        corpus_lines = len(byte_strings)
        corpus_bytes = sum(len(value) for value in byte_strings)
        if corpus_bytes == 0:
            raise ValueError("cannot train BPE on an empty corpus")
        max_merges = max(0, target_vocab_size - self._merge_symbol_start)
        if max_merges == 0:
            self._set_merges(())
            return _TrainingStats(
                target_vocab_size=target_vocab_size,
                actual_vocab_size=self.vocab_size,
                merge_count=0,
                corpus_bytes=corpus_bytes,
                corpus_lines=corpus_lines,
            )

        sequences = [
            [self.byte_offset + value for value in byte_string]
            for byte_string in byte_strings
            if byte_string
        ]
        pair_counts: Counter[tuple[int, int]] = Counter()
        for sequence in sequences:
            for index in range(len(sequence) - 1):
                pair_counts[(sequence[index], sequence[index + 1])] += 1
        if not pair_counts:
            self._set_merges(())
            return _TrainingStats(
                target_vocab_size=target_vocab_size,
                actual_vocab_size=self.vocab_size,
                merge_count=0,
                corpus_bytes=corpus_bytes,
                corpus_lines=corpus_lines,
            )

        heap = [(-count, pair) for pair, count in pair_counts.items()]
        heapq.heapify(heap)
        merges: list[tuple[int, int]] = []
        while len(merges) < max_merges:
            pair = self._pop_most_frequent(pair_counts, heap)
            if pair is None:
                break
            left, right = pair
            merged_symbol = self._merge_symbol_start + len(merges)
            self._apply_merge(
                sequences,
                pair_counts,
                heap,
                left=left,
                right=right,
                merged_symbol=merged_symbol,
            )
            merges.append(pair)
        self._set_merges(tuple(merges))
        return _TrainingStats(
            target_vocab_size=target_vocab_size,
            actual_vocab_size=self.vocab_size,
            merge_count=len(merges),
            corpus_bytes=corpus_bytes,
            corpus_lines=corpus_lines,
        )

    @staticmethod
    def _pop_most_frequent(
        pair_counts: Counter[tuple[int, int]],
        heap: list[tuple[int, tuple[int, int]]],
    ) -> tuple[int, int] | None:
        """Return the currently most frequent merge pair, with deterministic ties."""

        while heap:
            negative_count, pair = heap[0]
            count = pair_counts.get(pair, 0)
            if count <= 0:
                heapq.heappop(heap)
                continue
            if -negative_count != count:
                heapq.heapreplace(heap, (-count, pair))
                continue
            return pair
        return None

    @staticmethod
    def _apply_merge(
        sequences: list[list[int]],
        pair_counts: Counter[tuple[int, int]],
        heap: list[tuple[int, tuple[int, int]]],
        *,
        left: int,
        right: int,
        merged_symbol: int,
    ) -> None:
        """Apply one merge to every sequence and update pair counts in place."""

        old_pair = (left, right)
        for index, sequence in enumerate(sequences):
            if len(sequence) < 2:
                continue
            new_sequence: list[int] = []
            position = 0
            length = len(sequence)
            changed = False
            while position < length:
                if (
                    position + 1 < length
                    and sequence[position] == left
                    and sequence[position + 1] == right
                ):
                    previous_symbol = (
                        new_sequence[-1] if new_sequence else None
                    )
                    if previous_symbol is not None:
                        BPETokenizer._decrement_pair(
                            pair_counts,
                            heap,
                            (previous_symbol, sequence[position]),
                        )
                        BPETokenizer._increment_pair(
                            pair_counts,
                            heap,
                            (previous_symbol, merged_symbol),
                        )
                    BPETokenizer._decrement_pair(pair_counts, heap, old_pair)
                    next_symbol = (
                        sequence[position + 2]
                        if position + 2 < length
                        else None
                    )
                    if next_symbol is not None:
                        BPETokenizer._decrement_pair(
                            pair_counts,
                            heap,
                            (sequence[position + 1], next_symbol),
                        )
                        BPETokenizer._increment_pair(
                            pair_counts,
                            heap,
                            (merged_symbol, next_symbol),
                        )
                    new_sequence.append(merged_symbol)
                    position += 2
                    changed = True
                else:
                    new_sequence.append(sequence[position])
                    position += 1
            if changed:
                sequences[index] = new_sequence

    @staticmethod
    def _decrement_pair(
        pair_counts: Counter[tuple[int, int]],
        heap: list[tuple[int, tuple[int, int]]],
        pair: tuple[int, int],
    ) -> None:
        """Subtract one occurrence and push the new heap entry."""

        current = pair_counts.get(pair, 0)
        if current <= 0:
            return
        updated = current - 1
        if updated <= 0:
            pair_counts.pop(pair, None)
        else:
            pair_counts[pair] = updated
            heapq.heappush(heap, (-updated, pair))

    @staticmethod
    def _increment_pair(
        pair_counts: Counter[tuple[int, int]],
        heap: list[tuple[int, tuple[int, int]]],
        pair: tuple[int, int],
    ) -> None:
        """Add one occurrence and push the new heap entry."""

        updated = pair_counts.get(pair, 0) + 1
        pair_counts[pair] = updated
        heapq.heappush(heap, (-updated, pair))

    def _set_merges(self, merges: tuple[tuple[int, int], ...]) -> None:
        """Rebuild all cached lookup tables from a fresh merge list."""

        self.merges = tuple(merges)
        self._merge_rank = {
            pair: rank for rank, pair in enumerate(self.merges)
        }
        self._merge_symbol_start = self.byte_offset + _BYTE_TOKEN_COUNT
        self._symbol_to_bytes = {}
        for value in range(_BYTE_TOKEN_COUNT):
            self._symbol_to_bytes[self.byte_offset + value] = bytes((value,))
        for rank, (left, right) in enumerate(self.merges):
            symbol_id = self._merge_symbol_start + rank
            self._symbol_to_bytes[symbol_id] = (
                self._symbol_to_bytes[left] + self._symbol_to_bytes[right]
            )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def save(self, directory: Path) -> None:
        """Write ``vocab.json`` and ``merges.txt`` into ``directory``."""

        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        vocab = {
            "version": BPETOKENIZER_VERSION,
            "vocab_size": self.vocab_size,
            "byte_offset": self.byte_offset,
            "base_byte_vocab_size": _BYTE_TOKEN_COUNT,
            "num_merges": len(self.merges),
            "special_tokens": {
                "pad_token_id": self.pad_token_id,
                "bos_token_id": self.bos_token_id,
                "eos_token_id": self.eos_token_id,
                "unknown_token_id": self.unknown_token_id,
            },
        }
        (directory / "vocab.json").write_text(
            json.dumps(vocab, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        merge_lines = ["#version: 0.2"]
        merge_lines.extend(f"{left} {right}" for left, right in self.merges)
        (directory / "merges.txt").write_text(
            "\n".join(merge_lines) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    @classmethod
    def load(cls, directory: Path) -> "BPETokenizer":
        """Load a tokenizer previously written by :meth:`save`."""

        directory = Path(directory)
        vocab_path = directory / "vocab.json"
        merges_path = directory / "merges.txt"
        vocab = json.loads(vocab_path.read_text(encoding="utf-8"))
        if vocab.get("version") != BPETOKENIZER_VERSION:
            raise ValueError("unsupported BPE vocabulary version")
        specials = vocab.get("special_tokens", {})
        merges = cls._read_merges(merges_path)
        tokenizer = cls(
            pad_token_id=int(specials.get("pad_token_id", 0)),
            bos_token_id=int(specials.get("bos_token_id", 1)),
            eos_token_id=int(specials.get("eos_token_id", 2)),
            unknown_token_id=int(specials.get("unknown_token_id", 3)),
            byte_offset=int(vocab.get("byte_offset", 4)),
            merges=tuple(merges),
        )
        if tokenizer.vocab_size != int(vocab.get("vocab_size", tokenizer.vocab_size)):
            raise ValueError("BPE vocabulary size does not match merge file")
        return tokenizer

    @staticmethod
    def _read_merges(path: Path) -> list[tuple[int, int]]:
        """Parse numeric ``left right`` merge lines."""

        merges: list[tuple[int, int]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            left_text, right_text = line.split()
            merges.append((int(left_text), int(right_text)))
        return merges

    def to_dict(self) -> dict[str, int | str]:
        """Return a compact JSON-compatible manifest."""

        return {
            "version": BPETOKENIZER_VERSION,
            "vocab_size": self.vocab_size,
            "num_merges": len(self.merges),
            "byte_offset": self.byte_offset,
        }


def train_bpe_tokenizer(
    texts: Iterable[str],
    *,
    target_vocab_size: int,
) -> tuple[BPETokenizer, _TrainingStats]:
    """Convenience wrapper that trains and returns a fresh tokenizer."""

    tokenizer = BPETokenizer()
    stats = tokenizer.train_from_texts(texts, target_vocab_size=target_vocab_size)
    return tokenizer, stats
