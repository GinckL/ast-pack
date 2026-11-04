"""Repository file discovery.

Inside a git work tree the file list comes from ``git ls-files`` (tracked plus
untracked-but-not-ignored files), which honours every ``.gitignore`` exactly.
Outside git, the tree is walked and the root ``.gitignore`` is applied with
``pathspec``. Vendored, generated and dependency directories are always
skipped, as are minified bundles and very large files.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .languages import language_for_path

DEFAULT_EXCLUDED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        "bower_components",
        "__pycache__",
        ".venv",
        "venv",
        "env",
        ".tox",
        ".nox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "site-packages",
        "dist",
        "build",
        "out",
        "target",
        ".next",
        ".nuxt",
        ".svelte-kit",
        ".turbo",
        ".cache",
        "coverage",
        ".idea",
        ".vscode",
    }
)
DEFAULT_MAX_FILE_BYTES = 1_000_000


@dataclass(slots=True, frozen=True)
class SourceFile:
    abs_path: str
    rel_path: str
    lang: str
    mtime_ns: int
    size: int


def _is_minified(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return ".min." in name or name.endswith(".bundle.js") or name.endswith(".chunk.js")


def _excluded(rel: str, excluded_dirs: frozenset[str]) -> bool:
    parts = rel.split("/")
    return any(p in excluded_dirs for p in parts[:-1])


def _git_files(root: Path) -> list[str] | None:
    try:
        top = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if top.returncode != 0:
            return None
        proc = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", "."],
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return [p for p in proc.stdout.decode("utf-8", "replace").split("\0") if p]


def _walk_files(root: Path, excluded_dirs: frozenset[str]) -> list[str]:
    spec = None
    gitignore = root / ".gitignore"
    if gitignore.is_file():
        try:
            import pathspec

            spec = pathspec.PathSpec.from_lines("gitwildmatch", gitignore.read_text("utf-8", "replace").splitlines())
        except ImportError:
            spec = None
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        rel_dir = "" if rel_dir == "." else rel_dir.replace(os.sep, "/")
        keep_dirs = []
        for d in dirnames:
            if d in excluded_dirs or d.startswith("."):
                continue
            rel = f"{rel_dir}/{d}" if rel_dir else d
            if spec is not None and spec.match_file(rel + "/"):
                continue
            keep_dirs.append(d)
        dirnames[:] = keep_dirs
        for f in filenames:
            rel = f"{rel_dir}/{f}" if rel_dir else f
            if spec is not None and spec.match_file(rel):
                continue
            out.append(rel)
    return out


def scan(
    root: str | os.PathLike[str],
    *,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    languages: set[str] | None = None,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    excluded_dirs: frozenset[str] = DEFAULT_EXCLUDED_DIRS,
) -> list[SourceFile]:
    """Return every supported source file under ``root``, sorted by path."""
    root_path = Path(root).resolve()
    rels = _git_files(root_path)
    if rels is None:
        rels = _walk_files(root_path, excluded_dirs)
    inc_spec = exc_spec = None
    if include or exclude:
        import pathspec

        if include:
            inc_spec = pathspec.PathSpec.from_lines("gitwildmatch", include)
        if exclude:
            exc_spec = pathspec.PathSpec.from_lines("gitwildmatch", exclude)
    files: list[SourceFile] = []
    for rel in rels:
        rel = rel.replace(os.sep, "/")
        lang = language_for_path(rel)
        if lang is None:
            continue
        if languages and lang not in languages:
            continue
        if _excluded(rel, excluded_dirs) or _is_minified(rel):
            continue
        if inc_spec is not None and not inc_spec.match_file(rel):
            continue
        if exc_spec is not None and exc_spec.match_file(rel):
            continue
        abs_path = root_path / rel
        try:
            st = abs_path.stat()
        except OSError:
            continue
        if not abs_path.is_file() or st.st_size > max_file_bytes:
            continue
        files.append(SourceFile(str(abs_path), rel, lang, st.st_mtime_ns, st.st_size))
    files.sort(key=lambda f: f.rel_path)
    return files
