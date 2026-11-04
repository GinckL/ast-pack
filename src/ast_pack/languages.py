"""Tree-sitter grammar registry and file-extension mapping."""

from __future__ import annotations

from functools import lru_cache

from tree_sitter import Language, Parser

EXTENSIONS: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".ts": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".jsx": "javascript",
    ".rs": "rust",
    ".go": "go",
}

# Display / fence names.
FENCE = {
    "python": "python",
    "typescript": "typescript",
    "tsx": "tsx",
    "javascript": "javascript",
    "rust": "rust",
    "go": "go",
}

# Languages that share one symbol namespace family for resolution.
FAMILY = {
    "python": "python",
    "typescript": "js",
    "tsx": "js",
    "javascript": "js",
    "rust": "rust",
    "go": "go",
}

LINE_COMMENT = {
    "python": "#",
    "typescript": "//",
    "tsx": "//",
    "javascript": "//",
    "rust": "//",
    "go": "//",
}


def language_for_path(path: str) -> str | None:
    dot = path.rfind(".")
    if dot == -1:
        return None
    if path.endswith(".d.ts"):
        return "typescript"
    return EXTENSIONS.get(path[dot:].lower())


@lru_cache(maxsize=None)
def get_language(lang: str) -> Language:
    if lang == "python":
        import tree_sitter_python as mod

        return Language(mod.language())
    if lang == "typescript":
        import tree_sitter_typescript as mod

        return Language(mod.language_typescript())
    if lang == "tsx":
        import tree_sitter_typescript as mod

        return Language(mod.language_tsx())
    if lang == "javascript":
        # The TSX grammar is a superset of JavaScript + JSX and handles
        # Flow-free modern JS (including JSX in .js files) robustly.
        import tree_sitter_typescript as mod

        return Language(mod.language_tsx())
    if lang == "rust":
        import tree_sitter_rust as mod

        return Language(mod.language())
    if lang == "go":
        import tree_sitter_go as mod

        return Language(mod.language())
    raise ValueError(f"unsupported language: {lang}")


def get_parser(lang: str) -> Parser:
    # Parsers are cheap; a fresh one per call keeps this safe across threads
    # and worker processes.
    return Parser(get_language(lang))


SUPPORTED_LANGUAGES = ("python", "typescript", "tsx", "javascript", "rust", "go")
