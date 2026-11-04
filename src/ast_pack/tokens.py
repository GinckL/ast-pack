"""Token counting.

ast-pack reports token savings, so counting must be fast and deterministic.
When ``tiktoken`` is installed and its BPE file is available (it is downloaded
once and cached by tiktoken), counts are exact for the chosen encoding
(``cl100k_base`` by default, ``o200k_base`` also supported). Otherwise a
calibrated estimator is used and every report says ``tokenizer: "approx"``.

The estimator splits text the way BPE pre-tokenizers do (letter runs, digit
groups, punctuation runs, whitespace runs) and charges each piece by length.
Its weights were fitted against cl100k_base on Python, TypeScript, Go and Rust
sources; on whole files it lands within a few percent of the real count.
"""

from __future__ import annotations

import os
import re
from functools import lru_cache

# Pre-tokenisation close to cl100k's pattern: contractions, optional leading
# space + letters, 1-3 digit groups, optional leading space + punctuation run,
# newline runs, other whitespace.
_PIECE_RE = re.compile(
    r"""'(?:[sdmt]|ll|ve|re)|[^\r\n\w]?[A-Za-z]+|\d{1,3}| ?[^\s\w]+[\r\n]*|\s*[\r\n]+|\s+(?!\S)|\s+|[^\x00-\x7f]""",
    re.UNICODE,
)
_CAMEL_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])")


def _approx_piece(piece: str) -> int:
    first = piece[0]
    if first.isspace():
        # Whitespace runs (indentation) are mostly single tokens; very long
        # runs split roughly every 16 characters.
        return 1 + len(piece) // 17
    if first.isalpha() or (len(piece) > 1 and piece[1].isalpha()):
        word = piece.lstrip(" \t") if not first.isalpha() else piece
        # Identifiers split on camelCase / snake_case boundaries; long parts
        # cost roughly one token per 5.5 characters.
        parts = _CAMEL_RE.findall(word) or [word]
        total = 0
        for part in parts:
            total += 1 + (len(part) - 1) // 6
        return max(1, total if len(parts) > 1 else 1 + (len(word) - 1) // 7)
    if first.isdigit():
        return 1
    # Punctuation runs: common pairs like "()", "):", "->", "=>" merge.
    stripped = piece.strip()
    if not stripped:
        return 1
    return max(1, (len(stripped) + 1) // 2)


def approx_count(text: str) -> int:
    if not text:
        return 0
    return sum(_approx_piece(p) for p in _PIECE_RE.findall(text))


class TokenCounter:
    """Counts tokens with tiktoken when available, else the estimator."""

    def __init__(self, encoding: str | None = None) -> None:
        requested = encoding or os.environ.get("AST_PACK_TOKENIZER") or "cl100k_base"
        self.name = "approx"
        self._enc = None
        if requested != "approx":
            self._enc = _load_tiktoken(requested)
            if self._enc is not None:
                self.name = requested

    @property
    def exact(self) -> bool:
        return self._enc is not None

    def count(self, text: str) -> int:
        if not text:
            return 0
        if self._enc is not None:
            return len(self._enc.encode(text, disallowed_special=()))
        return approx_count(text)


@lru_cache(maxsize=4)
def _load_tiktoken(name: str):
    try:
        import tiktoken  # type: ignore
    except ImportError:
        return None
    try:
        return tiktoken.get_encoding(name)
    except Exception:  # network failure, unknown encoding, corrupt cache
        return None


@lru_cache(maxsize=4)
def get_counter(encoding: str | None = None) -> TokenCounter:
    return TokenCounter(encoding)
