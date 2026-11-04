"""Per-language extractors and the single-file entry point."""

from __future__ import annotations

from ..languages import get_parser
from ..models import FileExtraction
from ..tokens import get_counter
from .base import BaseExtractor
from .go import GoExtractor
from .python import PythonExtractor
from .rust import RustExtractor
from .typescript import TypeScriptExtractor

EXTRACTORS: dict[str, type[BaseExtractor]] = {
    "python": PythonExtractor,
    "typescript": TypeScriptExtractor,
    "tsx": TypeScriptExtractor,
    "javascript": TypeScriptExtractor,
    "rust": RustExtractor,
    "go": GoExtractor,
}

# Bump whenever extraction output changes so stale caches are discarded.
EXTRACTOR_VERSION = 8


def extract_source(
    rel_path: str,
    source: bytes,
    lang: str,
    *,
    mtime_ns: int = 0,
    size: int | None = None,
    tokenizer: str | None = None,
) -> FileExtraction:
    parser = get_parser(lang)
    tree = parser.parse(source)
    counter = get_counter(tokenizer)
    text = source.decode("utf-8", "replace")
    extractor = EXTRACTORS[lang](rel_path, source, lang)
    result = extractor.build(
        tree.root_node,
        mtime_ns=mtime_ns,
        size=len(source) if size is None else size,
        tokens=counter.count(text),
    )
    lines = text.split("\n")
    for sym in result.symbols:
        sym.tokens = counter.count("\n".join(lines[sym.start_line - 1 : sym.end_line]))
    return result


def extract_path(args: tuple[str, str, str, int, int, str | None]) -> FileExtraction | None:
    """Worker entry point: ``(abs_path, rel_path, lang, mtime_ns, size, tokenizer)``."""
    abs_path, rel_path, lang, mtime_ns, size, tokenizer = args
    try:
        with open(abs_path, "rb") as fh:
            source = fh.read()
    except OSError:
        return None
    return extract_source(rel_path, source, lang, mtime_ns=mtime_ns, size=size, tokenizer=tokenizer)


__all__ = ["EXTRACTORS", "EXTRACTOR_VERSION", "extract_path", "extract_source"]
