"""Entry-point resolution: symbol names, ``file:line`` targets and stack traces.

A *target* string is classified automatically:

1. **Stack trace** – multi-line text containing Python, Node.js/V8, Go
   (panic / goroutine dumps) or Rust (panic + backtrace) frames. Every frame
   that maps to a file in the repository becomes a seed; the innermost
   in-repo frame is marked as the crash site.
2. **file:line[:col]** – the innermost symbol enclosing that line.
3. **file path** – every top-level symbol in the file.
4. **symbol** – ``name``, ``Class.method``, ``Type::method``, ``pkg.Func`` or
   ``path/to/file.py::name``; exact matches win, then case-insensitive ones.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .index import RepoIndex
from .models import Symbol

# --- frame patterns ---------------------------------------------------------
_PY_FRAME = re.compile(r'^\s*File "(?P<path>[^"]+)", line (?P<line>\d+)(?:, in (?P<func>\S+))?', re.M)
_NODE_FRAME = re.compile(
    r"^\s*at (?:(?:async )?(?P<func>[^\s(]+(?: \[as [^\]]+\])?) \()?(?P<path>(?:file://|webpack:///|webpack-internal:///(?:\([^)]*\)/)?)?[^\s()]+?):(?P<line>\d+):(?P<col>\d+)\)?\s*$",
    re.M,
)
_GO_FRAME = re.compile(r"^(?P<func>[\w./*()\-\[\]]+)\(.*\)\n\s+(?P<path>\S+\.go):(?P<line>\d+)", re.M)
_GO_LOC = re.compile(r"^\s+(?P<path>\S+\.go):(?P<line>\d+)(?: \+0x[0-9a-f]+)?\s*$", re.M)
_RUST_PANIC = re.compile(r"panicked at (?:'[^']*', )?(?P<path>[^\s:]+\.rs):(?P<line>\d+)(?::(?P<col>\d+))?")
_RUST_FRAME = re.compile(r"^\s*\d+:\s+(?P<func>\S+)\s*\n\s+at (?P<path>[^\s:]+\.rs):(?P<line>\d+)(?::\d+)?", re.M)
_GENERIC_LOC = re.compile(r"(?P<path>[\w./\\@~\-]+\.(?:py|pyi|ts|tsx|mts|cts|js|jsx|mjs|cjs|rs|go)):(?P<line>\d+)")
_FILE_LINE = re.compile(r"^(?P<path>.+?):(?P<line>\d+)(?::(?P<col>\d+))?$")
_ERROR_LINE = re.compile(
    r"^(?:(?:[\w.]+(?:Error|Exception|Exit|Interrupt|Warning)|panic|thread '[^']+' panicked at|Error|TypeError|RangeError|ReferenceError|SyntaxError)\b.*)$",
    re.M,
)


@dataclass(slots=True)
class Frame:
    path: str  # path as written in the trace
    line: int
    func: str | None = None
    repo_path: str | None = None
    symbol_id: str | None = None


@dataclass
class Resolution:
    kind: str  # symbol | file_line | file | trace
    seeds: list[str] = field(default_factory=list)
    frames: list[Frame] = field(default_factory=list)
    crash_site: Frame | None = None
    error_message: str | None = None
    trace_language: str | None = None
    highlight_lines: dict[str, dict[int, str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


def looks_like_trace(text: str) -> bool:
    if "\n" not in text.strip():
        return bool(_RUST_PANIC.search(text))
    return bool(
        _PY_FRAME.search(text)
        or _NODE_FRAME.search(text)
        or _GO_LOC.search(text)
        or _RUST_PANIC.search(text)
        or _RUST_FRAME.search(text)
        or len(_GENERIC_LOC.findall(text)) >= 2
    )


def parse_trace(text: str) -> tuple[str, list[Frame], int, str | None]:
    """Return ``(language, frames, crash_index, error_message)``.

    ``crash_index`` points at the innermost frame (where execution stopped).
    """
    text = text.replace("\r\n", "\n")
    frames: list[Frame]
    msg_match = _ERROR_LINE.findall(text)
    message = msg_match[-1].strip() if msg_match else None

    py = [Frame(m["path"], int(m["line"]), m["func"]) for m in _PY_FRAME.finditer(text)]
    if py:
        # Python prints outermost first; the crash site is the last frame.
        return "python", py, len(py) - 1, message

    node = [Frame(m["path"], int(m["line"]), m["func"]) for m in _NODE_FRAME.finditer(text)]
    if node:
        first = text.strip().split("\n", 1)[0]
        return "javascript", node, 0, message or first

    rust_frames = [Frame(m["path"], int(m["line"]), m["func"]) for m in _RUST_FRAME.finditer(text)]
    panic = _RUST_PANIC.search(text)
    if panic or rust_frames:
        frames = []
        if panic:
            frames.append(Frame(panic["path"], int(panic["line"]), None))
            after = text[panic.end() :].lstrip(":").strip().split("\n", 1)[0].strip()
            message = f"panicked: {after}" if after else message
        frames.extend(rust_frames)
        return "rust", frames, 0, message

    go = [Frame(m["path"], int(m["line"]), m["func"]) for m in _GO_FRAME.finditer(text)]
    if not go:
        go = [Frame(m["path"], int(m["line"]), None) for m in _GO_LOC.finditer(text)]
    if go:
        panic_line = next((ln for ln in text.split("\n") if ln.startswith("panic:")), None)
        # Skip runtime frames: the crash site is the first frame outside GOROOT.
        crash = next((i for i, f in enumerate(go) if "/runtime/" not in f.path and not f.path.startswith("runtime/")), 0)
        return "go", go, crash, panic_line or message

    generic = [Frame(m["path"], int(m["line"])) for m in _GENERIC_LOC.finditer(text)]
    return "unknown", generic, len(generic) - 1 if generic else 0, message


def _clean_trace_path(path: str) -> str:
    for prefix in ("file://", "webpack:///", "webpack-internal:///"):
        if path.startswith(prefix):
            path = path[len(prefix) :]
    path = path.replace("\\", "/")
    path = re.sub(r"^\([\w-]+\)/", "", path)  # webpack-internal:///(app-pages-browser)/./src
    while path.startswith("./"):
        path = path[2:]
    return path


def map_path(index: RepoIndex, raw: str) -> str | None:
    """Map a path from a trace (often absolute, from another machine) to a repo file."""
    path = _clean_trace_path(raw)
    if path in index.files:
        return path
    try:
        from pathlib import Path

        p = Path(path)
        if p.is_absolute():
            rel = p.resolve().relative_to(index.root).as_posix()
            if rel in index.files:
                return rel
    except (ValueError, OSError):
        pass
    parts = [p for p in path.split("/") if p and p != "."]
    if not parts or any(seg in ("node_modules", "site-packages", "dist-packages") for seg in parts):
        return None
    best: tuple[int, str] | None = None
    tail = parts[-1]
    for rel in index.files:
        if not (rel == tail or rel.endswith("/" + tail)):
            continue
        rel_parts = rel.split("/")
        n = 0
        while n < min(len(parts), len(rel_parts)) and parts[-1 - n] == rel_parts[-1 - n]:
            n += 1
        if best is None or n > best[0] or (n == best[0] and len(rel) < len(best[1])):
            best = (n, rel)
    if best is None:
        return None
    # A bare file name that matches several repo files is ambiguous.
    if best[0] == 1 and sum(1 for r in index.files if r == tail or r.endswith("/" + tail)) > 1:
        return None
    return best[1]


def _pick_symbol(index: RepoIndex, path: str, line: int) -> Symbol | None:
    hits = [s for s in index.symbols_at(path, line) if s.kind not in ("impl", "module")]
    return hits[0] if hits else None


# --- symbol queries -----------------------------------------------------------
_SPLIT_RE = re.compile(r"::|\.|#|/")


def find_symbols(index: RepoIndex, query: str) -> list[Symbol]:
    q = query.strip().strip("`'\"").rstrip("()")
    if not q:
        return []
    # ``path/to/file.py::name``
    if "::" in q:
        head, _, tail = q.rpartition("::")
        if head in index.files:
            return [index.symbols[i] for i in index.by_file[head] if index.symbols[i].qualname == tail or index.symbols[i].name == tail]
    exact = [s for s in index.symbols.values() if s.qualname == q and s.kind not in ("block", "impl")]
    if exact:
        return exact
    parts = [p for p in _SPLIT_RE.split(q) if p]
    if not parts:
        return []
    name = parts[-1]
    qualifiers = parts[:-1]
    cands = [index.symbols[i] for i in index.by_name.get(name, [])]
    if qualifiers:
        def matches(s: Symbol) -> bool:
            hay = [*s.qualname.split(".")[:-1], *(s.owner or "").split("."), *s.path.replace(".", "/").split("/")]
            if s.lang == "go":
                pkg = index.files[s.path].package
                if pkg:
                    hay.append(pkg)
            return all(qp in hay for qp in qualifiers)

        filtered = [s for s in cands if matches(s)]
        if filtered:
            return filtered
    if cands and not qualifiers:
        return cands
    lower = name.lower()
    ci = [s for s in index.symbols.values() if s.name.lower() == lower and s.kind not in ("block", "impl")]
    return ci


def resolve_targets(index: RepoIndex, targets: list[str], max_ambiguous: int = 8) -> Resolution:
    res = Resolution(kind="symbol")
    kinds: list[str] = []
    for raw in targets:
        target = raw.strip()
        if not target:
            continue
        if looks_like_trace(target):
            kinds.append("trace")
            _resolve_trace(index, target, res)
            continue
        m = _FILE_LINE.match(target)
        if m and "\n" not in target:
            path = map_path(index, m["path"])
            if path is not None:
                kinds.append("file_line")
                line = int(m["line"])
                sym = _pick_symbol(index, path, line)
                if sym is not None:
                    res.seeds.append(sym.id)
                    res.highlight_lines.setdefault(path, {})[line] = "target line"
                else:
                    res.warnings.append(f"{path}:{line} is not inside any symbol; using nearest definitions in the file")
                    near = sorted(
                        (index.symbols[i] for i in index.by_file[path] if index.symbols[i].parent is None),
                        key=lambda s: min(abs(s.start_line - line), abs(s.end_line - line)),
                    )[:2]
                    res.seeds.extend(s.id for s in near)
                continue
        path = map_path(index, target) if ("/" in target or "." in target) else None
        if path is not None and path in index.files and (target.endswith(path.rsplit("/", 1)[-1])):
            kinds.append("file")
            res.seeds.extend(i for i in index.by_file[path] if index.symbols[i].parent is None and index.symbols[i].kind != "impl")
            continue
        kinds.append("symbol")
        found = find_symbols(index, target)
        if not found:
            res.warnings.append(f"no symbol matches {target!r}")
            res.suggestions.extend(f"{s.qualname} ({s.path}:{s.decl_line})" for _, s in index.search(target, limit=5))
            continue
        if len(found) > max_ambiguous:
            res.warnings.append(
                f"{target!r} matches {len(found)} symbols; using the first {max_ambiguous}. Qualify it as path::name or Type.name"
            )
            found = sorted(found, key=lambda s: ("test" in s.path.lower(), s.path, s.start_line))[:max_ambiguous]
        elif len(found) > 1:
            res.warnings.append(f"{target!r} is ambiguous ({len(found)} matches); seeding all of them")
        res.seeds.extend(s.id for s in found)
    if kinds:
        res.kind = kinds[0] if len(set(kinds)) == 1 else "mixed"
    seen: set[str] = set()
    res.seeds = [s for s in res.seeds if not (s in seen or seen.add(s))]
    return res


def _resolve_trace(index: RepoIndex, text: str, res: Resolution) -> None:
    lang, frames, crash_idx, message = parse_trace(text)
    res.trace_language = lang
    res.error_message = message
    mapped = 0
    for i, frame in enumerate(frames):
        frame.repo_path = map_path(index, frame.path)
        if frame.repo_path is None:
            continue
        mapped += 1
        sym = _pick_symbol(index, frame.repo_path, frame.line)
        if sym is not None:
            frame.symbol_id = sym.id
            res.seeds.append(sym.id)
        label = "crash site" if i == crash_idx else f"trace frame #{i + 1}"
        res.highlight_lines.setdefault(frame.repo_path, {}).setdefault(frame.line, label)
    res.frames.extend(frames)
    in_repo = [f for f in frames if f.repo_path]
    if in_repo:
        # Innermost in-repo frame: the crash frame if it is in the repo, else the
        # in-repo frame closest to it.
        ordered = sorted(range(len(frames)), key=lambda i: abs(i - crash_idx))
        for i in ordered:
            if frames[i].repo_path:
                res.crash_site = frames[i]
                res.highlight_lines[frames[i].repo_path][frames[i].line] = "crash site" + (
                    f": {message}" if message else ""
                )
                break
    if not mapped:
        res.warnings.append(f"none of the {len(frames)} {lang} trace frames map to files in this repository")
