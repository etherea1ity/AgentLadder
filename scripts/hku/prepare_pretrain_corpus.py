#!/usr/bin/env python3
"""Build a line-delimited pretraining corpus from HuggingFaceFW/fineweb-edu.

Intended for Linux (HKU gateway/compute nodes):

    python scripts/hku/prepare_pretrain_corpus.py --config config/corpus.toml

The script streams the dataset through ``datasets``, keeps only the text field,
normalizes each document to one bounded-width line, and stops once
the token count estimated by ``tokenizers`` reaches the configured target.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "corpus.toml"

# Config keys that are deliberately optional and their defaults.
_DEFAULT_DATASET_NAME = "HuggingFaceFW/fineweb-edu"
_DEFAULT_SPLIT = "train"
_DEFAULT_TEXT_COLUMN = "text"
_DEFAULT_OUTPUT_PATH = "/userhome/cs2/u3665453/AgentLadder/data/pretrain/klara_corpus.txt"
_DEFAULT_TARGET_TOKENS = 2_500_000_000
_DEFAULT_MAX_CHARS_PER_LINE = 2000
_DEFAULT_TOKENIZER_NAME = "bert-base-uncased"
_DEFAULT_FALLBACK_MULTIPLIER = 1.3


@dataclass
class CorpusConfig:
    """Configurable values used by the streaming corpus writer."""

    dataset_name: str
    split: str
    text_column: str
    output_path: Path
    target_tokens: int
    max_chars_per_line: int
    tokenizer_name: str
    fallback_tokenizer: str
    fallback_token_multiplier: float
    log_every_samples: int
    max_samples: int | None = None
    cache_dir: Path | None = None

    @classmethod
    def from_toml(cls, path: Path) -> "CorpusConfig":
        with path.open("rb") as handle:
            raw = tomllib.load(handle)

        corpus = raw.get("corpus", {})
        if not isinstance(corpus, dict):
            raise ValueError("config/corpus.toml must contain a [corpus] table")

        output_path = Path(
            corpus.get("output_path", _DEFAULT_OUTPUT_PATH)
        ).expanduser()

        cache_dir = None
        if corpus.get("cache_dir"):
            cache_dir = Path(str(corpus["cache_dir"])).expanduser()

        return cls(
            dataset_name=str(corpus.get("dataset_name", _DEFAULT_DATASET_NAME)),
            split=str(corpus.get("split", _DEFAULT_SPLIT)),
            text_column=str(corpus.get("text_column", _DEFAULT_TEXT_COLUMN)),
            output_path=output_path,
            target_tokens=int(corpus.get("target_tokens", _DEFAULT_TARGET_TOKENS)),
            max_chars_per_line=int(
                corpus.get("max_chars_per_line", _DEFAULT_MAX_CHARS_PER_LINE)
            ),
            tokenizer_name=str(
                corpus.get("tokenizer_name", _DEFAULT_TOKENIZER_NAME)
            ),
            fallback_tokenizer=str(corpus.get("fallback_tokenizer", "whitespace")),
            fallback_token_multiplier=float(
                corpus.get(
                    "fallback_token_multiplier", _DEFAULT_FALLBACK_MULTIPLIER
                )
            ),
            log_every_samples=int(corpus.get("log_every_samples", 10000)),
            max_samples=None,
            cache_dir=cache_dir,
        )

    def effective_cache_dir(self) -> str | None:
        """Return the datasets cache dir, honoring HF_HOME/HF_DATASETS_CACHE."""
        if self.cache_dir is not None:
            return str(self.cache_dir)

        datasets_cache = os.environ.get("HF_DATASETS_CACHE")
        if datasets_cache:
            return datasets_cache

        hf_home = os.environ.get("HF_HOME")
        if hf_home:
            # datasets stores its cache under $HF_HOME/datasets when only
            # HF_HOME is set; this makes that behavior explicit for streaming.
            return str(Path(hf_home).expanduser() / "datasets")

        return None


def log(message: str) -> None:
    print(f"[prepare_pretrain_corpus] {message}", flush=True)


class TokenEstimator:
    """Rough token counter based on the ``tokenizers`` library.

    The preferred HF tokenizer is loaded once and used for every line.  If it
    cannot be loaded, the estimator falls back to whitespace pre-tokenization
    and applies a conservative multiplier so ``target_tokens`` remains a
    useful stopping criterion even in the fallback path.
    """

    def __init__(
        self,
        tokenizer_name: str,
        fallback_tokenizer: str,
        fallback_token_multiplier: float,
    ) -> None:
        self.fallback_token_multiplier = max(float(fallback_token_multiplier), 0.0)
        self._tokenizer = None
        self._pre_tokenizer = None

        if tokenizer_name:
            try:
                from tokenizers import Tokenizer

                self._tokenizer = Tokenizer.from_pretrained(tokenizer_name)
                log(f"loaded token estimator from HF tokenizer: {tokenizer_name}")
                return
            except Exception as exc:  # noqa: BLE001 - fallback is intentional
                log(
                    "failed to load tokenizer "
                    f"{tokenizer_name!r}; using fallback ({exc})"
                )

        try:
            from tokenizers.pre_tokenizers import Whitespace

            self._pre_tokenizer = Whitespace()
            log(
                "using whitespace fallback with multiplier "
                f"{self.fallback_token_multiplier:.3f}"
            )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "tokenizers is required for coarse token estimation"
            ) from exc

        if fallback_tokenizer and fallback_tokenizer.lower() != "whitespace":
            log(
                f"configured fallback_tokenizer={fallback_tokenizer!r} is not "
                "supported by this script; using whitespace instead"
            )

    def count(self, text: str) -> int:
        """Return an integer token estimate for one line of text."""
        if not text:
            return 0

        if self._tokenizer is not None:
            try:
                encoding = self._tokenizer.encode(text, add_special_tokens=False)
                return len(encoding)
            except Exception as exc:  # noqa: BLE001
                log(f"tokenizer encode failed, falling back for this run ({exc})")
                self._tokenizer = None
                from tokenizers.pre_tokenizers import Whitespace

                self._pre_tokenizer = Whitespace()

        if self._pre_tokenizer is None:
            from tokenizers.pre_tokenizers import Whitespace

            self._pre_tokenizer = Whitespace()

        pretokens = self._pre_tokenizer.pre_tokenize_str(text)
        count = len(pretokens)
        if self.fallback_token_multiplier > 0.0:
            count = int(round(count * self.fallback_token_multiplier))
        return max(count, 1)


def clean_text(text: object) -> str:
    """Normalize one dataset row into a single-space-separated string."""
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    # Remove newline-like characters so each output record stays on one line,
    # then collapse any remaining whitespace runs.
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return " ".join(text.split())


def split_into_lines(text: str, max_chars_per_line: int) -> list[str]:
    """Return one bounded-width line for one normalized document.

    The corpus contract is one document per line.  Newlines were already
    removed by :func:`clean_text`; if a document is longer than
    ``max_chars_per_line`` it is truncated to that width so downstream
    line-based loaders never see an over-long row.
    """
    if not text:
        return []
    if max_chars_per_line <= 0:
        raise ValueError("max_chars_per_line must be positive")
    return [text[:max_chars_per_line]]

def open_streaming_dataset(config: CorpusConfig):
    """Open ``config.dataset_name`` as an iterable HF streaming dataset."""
    try:
        from datasets import load_dataset
    except ImportError as exc:
        raise SystemExit(
            "The Python package 'datasets' is required. "
            "Install it with: pip install datasets"
        ) from exc

    cache_dir = config.effective_cache_dir()
    cache_label = cache_dir or "(default)"
    log(
        f"loading dataset={config.dataset_name} split={config.split} "
        f"streaming=True cache_dir={cache_label}"
    )
    log(
        "HF_HOME="
        + repr(os.environ.get("HF_HOME"))
        + " HF_DATASETS_CACHE="
        + repr(os.environ.get("HF_DATASETS_CACHE"))
    )
    return load_dataset(
        config.dataset_name,
        split=config.split,
        streaming=True,
        cache_dir=cache_dir,
    )


def run(config: CorpusConfig) -> None:
    """Stream dataset rows and write the bounded-width corpus until target."""
    if config.target_tokens <= 0:
        raise ValueError("target_tokens must be positive")
    if config.max_chars_per_line <= 0:
        raise ValueError("max_chars_per_line must be positive")

    output_path = config.output_path.expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    estimator = TokenEstimator(
        tokenizer_name=config.tokenizer_name,
        fallback_tokenizer=config.fallback_tokenizer,
        fallback_token_multiplier=config.fallback_token_multiplier,
    )

    dataset = open_streaming_dataset(config)

    started_at = time.time()
    sample_count = 0
    line_count = 0
    bytes_written = 0
    token_count = 0
    target_reached = False

    log(f"writing corpus to {output_path}")
    log(
        "stopping at target_tokens="
        f"{config.target_tokens:,} max_chars_per_line={config.max_chars_per_line}"
    )
    if config.max_samples is not None:
        log(f"sample limit override is active: max_samples={config.max_samples}")

    with output_path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in dataset:
            if config.max_samples is not None and sample_count >= config.max_samples:
                break

            sample_count += 1
            text = clean_text(row.get(config.text_column, ""))
            lines = split_into_lines(text, config.max_chars_per_line)

            for line in lines:
                if config.max_samples is None and token_count >= config.target_tokens:
                    target_reached = True
                    break

                estimated = estimator.count(line)
                if estimated <= 0:
                    continue

                record = line + "\n"
                handle.write(record)
                bytes_written += len(record.encode("utf-8"))
                line_count += 1
                token_count += estimated

                if config.max_samples is None and token_count >= config.target_tokens:
                    target_reached = True
                    break

            if target_reached:
                break

            if sample_count % config.log_every_samples == 0:
                elapsed = time.time() - started_at
                log(
                    f"progress samples={sample_count} lines={line_count} "
                    f"tokens={token_count:,} bytes={bytes_written:,} "
                    f"elapsed={elapsed:.1f}s"
                )

    elapsed = time.time() - started_at
    print("downloaded_samples:", sample_count)
    print("lines_written:", line_count)
    print("bytes_written:", bytes_written)
    print("estimated_tokens:", token_count)
    print("output_file:", output_path)
    print(f"elapsed_seconds: {elapsed:.1f}")
    if target_reached:
        log("target token threshold reached")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stream fineweb-edu and write a bounded-width text corpus."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Path to config/corpus.toml (default: repo config/corpus.toml).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Override the output path from the config file.",
    )
    parser.add_argument(
        "--target-tokens",
        type=int,
        default=None,
        help="Override target_tokens from the config file.",
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=None,
        help="Stop after at most N dataset samples (used by dry-run).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = CorpusConfig.from_toml(args.config)

    if args.output is not None:
        config.output_path = args.output.expanduser()
    if args.target_tokens is not None:
        config.target_tokens = args.target_tokens
    if args.max_samples is not None:
        config.max_samples = args.max_samples

    run(config)
    return 0


if __name__ == "__main__":
    sys.exit(main())