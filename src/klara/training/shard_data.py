"""Streaming packed-shard dataset and corpus preprocessing helpers.

The pretraining lane tokenizes text once, packs fixed-length causal windows,
writes numbered shards, and then trains directly from those shards with an
iterable DataLoader.  Keeping shards on disk makes the full 124M-MoE run
memory-bounded and lets the trainer read only the data it needs.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import random
from typing import Iterable, Iterator

import torch
from torch.utils.data import IterableDataset, get_worker_info

from klara.training.tokenizer import ByteTokenizer
from klara.training.bpe_tokenizer import BPETokenizer

PACKED_SHARD_FORMAT = "klara.packed-shard.v1"
IGNORE_INDEX = -100


@dataclass(frozen=True)
class PackedBatch:
    """One batch of full-length packed causal rows with no padding."""

    input_ids: torch.Tensor
    labels: torch.Tensor

    def to(self, device: torch.device) -> "PackedBatch":
        """Move both tensors to one execution device."""

        return PackedBatch(
            input_ids=self.input_ids.to(device),
            labels=self.labels.to(device),
        )


def _iter_corpus_lines(corpus_path: Path) -> Iterator[str]:
    """Yield non-empty stripped lines from one file or every .txt file in a dir."""

    paths: list[Path]
    if corpus_path.is_dir():
        paths = sorted(corpus_path.glob("*.txt"))
    else:
        paths = [corpus_path]
    if not paths:
        raise ValueError(f"corpus path contains no text files: {corpus_path}")
    for path in paths:
        with path.open("r", encoding="utf-8", newline="\n") as handle:
            for line in handle:
                text = line.strip()
                if text:
                    yield text


def _iter_tokens(
    corpus_path: Path,
    tokenizer: ByteTokenizer | BPETokenizer,
) -> Iterator[int]:
    """Tokenize corpus lines sequentially with BOS/EOS boundaries."""

    for text in _iter_corpus_lines(corpus_path):
        yield from tokenizer.encode(text, add_bos=True, add_eos=True)


def _iter_packed_rows(
    token_stream: Iterable[int],
    *,
    sequence_length: int,
) -> Iterator[list[int]]:
    """Pack a token stream into non-overlapping ``sequence_length + 1`` rows."""

    if sequence_length < 2:
        raise ValueError("sequence_length must be at least 2")
    window: list[int] = []
    for token_id in token_stream:
        window.append(token_id)
        if len(window) == sequence_length + 1:
            yield window
            window = []
    # The final partial row is intentionally dropped so every shard row is full.


def _save_shard(
    rows: list[list[int]],
    path: Path,
    *,
    sequence_length: int,
    tokenizer_vocab_size: int,
) -> None:
    """Write one atomic shard file."""

    if not rows:
        return
    payload = {
        "format": PACKED_SHARD_FORMAT,
        "sequence_length": sequence_length,
        "tokenizer_vocab_size": tokenizer_vocab_size,
        "rows": torch.tensor(rows, dtype=torch.long),
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    torch.save(payload, temporary)
    temporary.replace(path)


def write_packed_shards(
    corpus_path: Path,
    tokenizer: ByteTokenizer | BPETokenizer,
    output_dir: Path,
    *,
    sequence_length: int,
    shard_rows: int,
    val_ratio: float = 0.0,
    max_tokens: int | None = None,
) -> dict[str, int | str]:
    """Tokenize corpus, write train/val shards, and return a manifest dict."""

    if shard_rows < 1:
        raise ValueError("shard_rows must be positive")
    if not 0.0 <= val_ratio < 1.0:
        raise ValueError("val_ratio must be in [0, 1)")
    output_dir = Path(output_dir)
    train_dir = output_dir / "train"
    val_dir = output_dir / "val"
    train_dir.mkdir(parents=True, exist_ok=True)
    val_dir.mkdir(parents=True, exist_ok=True)

    train_rows: list[list[int]] = []
    val_rows: list[list[int]] = []
    train_shard_count = 0
    val_shard_count = 0
    row_index = 0
    max_rows: int | None = None
    if max_tokens:
        max_rows = max_tokens // (sequence_length + 1)
    val_every = 0
    if val_ratio > 0:
        val_every = max(1, int(round(1.0 / val_ratio)))

    def flush(rows: list[list[int]], directory: Path, shard_count: int) -> int:
        if not rows:
            return shard_count
        path = directory / f"shard_{shard_count:06d}.pt"
        _save_shard(
            rows,
            path,
            sequence_length=sequence_length,
            tokenizer_vocab_size=tokenizer.vocab_size,
        )
        return shard_count + 1

    for row in _iter_packed_rows(
        _iter_tokens(corpus_path, tokenizer),
        sequence_length=sequence_length,
    ):
        if max_rows is not None and row_index >= max_rows:
            break
        if val_every and row_index % val_every == 0:
            val_rows.append(row)
            if len(val_rows) == shard_rows:
                val_shard_count = flush(val_rows, val_dir, val_shard_count)
                val_rows = []
        else:
            train_rows.append(row)
            if len(train_rows) == shard_rows:
                train_shard_count = flush(train_rows, train_dir, train_shard_count)
                train_rows = []
        row_index += 1

    train_shard_count = flush(train_rows, train_dir, train_shard_count)
    val_shard_count = flush(val_rows, val_dir, val_shard_count)

    manifest = {
        "format": "klara.packed-shards.v1",
        "sequence_length": sequence_length,
        "tokenizer_vocab_size": tokenizer.vocab_size,
        "shard_rows": shard_rows,
        "val_ratio": val_ratio,
        "train_shards": train_shard_count,
        "val_shards": val_shard_count,
        "train_dir": str(train_dir),
        "val_dir": str(val_dir),
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def load_shard_manifest(output_dir: Path) -> dict[str, int | str]:
    """Read a packed-shard manifest written by :func:`write_packed_shards`."""

    path = Path(output_dir) / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


class PackedShardDataset(IterableDataset):
    """Stream packed rows from on-disk shards as fixed causal batches."""

    def __init__(
        self,
        shard_dir: Path,
        *,
        batch_size: int,
        sequence_length: int,
        seed: int,
        shuffle: bool = True,
        repeat: bool = True,
        drop_last: bool = True,
    ) -> None:
        """Create a streaming dataset; use ``repeat=False`` for validation."""

        if batch_size < 1 or sequence_length < 2:
            raise ValueError("batch_size and sequence_length must be positive")
        self.shard_dir = Path(shard_dir)
        self.batch_size = batch_size
        self.sequence_length = sequence_length
        self.seed = seed
        self.shuffle = shuffle
        self.repeat = repeat
        self.drop_last = drop_last

    def _list_shards(self) -> list[Path]:
        """Return shard files in deterministic name order."""

        shards = sorted(self.shard_dir.glob("shard_*.pt"))
        if not shards:
            raise ValueError(f"no packed shards found in {self.shard_dir}")
        return shards

    def __iter__(self) -> Iterator[PackedBatch]:
        """Yield batches indefinitely for training, or once for validation."""

        worker = get_worker_info()
        base_seed = self.seed if worker is None else self.seed + worker.id * 100003
        epoch = 0
        while True:
            shards = self._list_shards()
            if self.shuffle:
                random.Random(base_seed + epoch * 1000003).shuffle(shards)
            for shard_index, shard_path in enumerate(shards):
                payload = torch.load(
                    shard_path,
                    map_location="cpu",
                    weights_only=False,
                )
                rows = payload["rows"]
                if rows.ndim != 2 or rows.shape[1] != self.sequence_length + 1:
                    raise ValueError("packed shard shape does not match sequence_length")
                row_count = rows.shape[0]
                if self.shuffle and row_count > 1:
                    generator = torch.Generator().manual_seed(
                        base_seed + epoch * 1_000_003 + shard_index * 10_007
                    )
                    indices = torch.randperm(row_count, generator=generator).tolist()
                else:
                    indices = list(range(row_count))
                for start in range(0, row_count, self.batch_size):
                    selected = indices[start : start + self.batch_size]
                    if len(selected) < self.batch_size and self.drop_last:
                        continue
                    selected_rows = rows[selected]
                    yield PackedBatch(
                        input_ids=selected_rows[:, :-1],
                        labels=selected_rows[:, 1:],
                    )
            if not self.repeat:
                break
            epoch += 1
