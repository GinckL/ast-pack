"""Rendering: turn a slice into per-file code views and the final bundle.

For each file the renderer builds a line plan:

* ``full`` symbols keep every line (including leading doc comments and
  decorators/attributes);
* ``outline`` symbols keep signatures; bodies become ``...`` (Python) or a
  ``// … N lines`` stub between the braces; docstrings and fields stay;
* ``header`` containers keep the class/impl/trait opening lines, fields and
  the closing brace so kept members stay syntactically valid;
* imports are kept only when they bind a name the kept code uses.

Everything else collapses into *pruned* segments rendered as a single
comment line such as ``# ⋯ 34 lines pruned (L41-L74): refund, Ledger.close``.
Because markers are comments and stubs are valid bodies, the output of each
file parses in its own language.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .index import RepoIndex
from .languages import FENCE, LINE_COMMENT
from .models import CONTAINER_KINDS, Symbol
from .slicer import ROLE_ORDER, SliceGraph, SliceNode
from .tokens import TokenCounter


@dataclass
class Segment:
    kind: str  # code | pruned
    start: int
    end: int
    text: str
    symbols: list[str] = field(default_factory=list)
    tokens: int = 0

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "symbols": self.symbols,
            "tokens": self.tokens,
        }


@dataclass
class FileRender:
    path: str
    lang: str
    segments: list[Segment]
    symbols: list[str]
    file_tokens: int
    file_lines: int
    kept_tokens: int = 0
    text: str = ""

    @property
    def ranges(self) -> list[tuple[int, int]]:
        return [(s.start, s.end) for s in self.segments if s.kind == "code"]

    def ranges_label(self) -> str:
        return ", ".join(f"{a}-{b}" if a != b else str(a) for a, b in self.ranges)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "language": self.lang,
            "ranges": [list(r) for r in self.ranges],
            "symbols": self.symbols,
            "file_tokens": self.file_tokens,
            "file_lines": self.file_lines,
            "kept_tokens": self.kept_tokens,
            "segments": [s.to_dict() for s in self.segments],
            "text": self.text,
        }


@dataclass
class RenderOptions:
    strip_comments: bool = False
    line_numbers: bool = False
    include_imports: bool = True


# Docstrings longer than this are dropped from outlines and class headers.
MAX_DOCSTRING_LINES = 6
_ALWAYS_OUTLINED = frozenset({"__init__", "constructor", "new", "__call__", "__new__"})


def _indent_of(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


class _FilePlan:
    def __init__(self, index: RepoIndex, path: str) -> None:
        self.index = index
        self.path = path
        self.fx = index.files[path]
        self.lines = index.file_lines(path)
        self.keep: set[int] = set()
        # Lines represented by a stub (outlined bodies): hidden without a marker.
        self.silent: set[int] = set()
        # Symbols rendered in full; outlines must not stub them.
        self.full_ids: set[str] = set()
        # Member names referenced anywhere in the slice; outlines list only these.
        self.used_members: set[str] | None = None
        self.headers: list[Symbol] = []
        self.stubs_after: dict[int, list[str]] = {}
        self.notes_before: dict[int, list[str]] = {}
        self.brace = self.fx.lang != "python"
        self.comment = LINE_COMMENT[self.fx.lang]

    def line(self, n: int) -> str:
        return self.lines[n - 1] if 1 <= n <= len(self.lines) else ""

    def keep_range(self, a: int, b: int) -> None:
        self.keep.update(range(max(1, a), min(len(self.lines), b) + 1))

    # -- modes --------------------------------------------------------------
    def full(self, sym: Symbol) -> None:
        self.keep_range(sym.start_line, sym.end_line)

    def header(self, sym: Symbol) -> None:
        body_start = sym.body_start_line
        if body_start is None:
            self.full(sym)
            return
        self.headers.append(sym)
        if self.brace:
            self.keep_range(sym.start_line, body_start)
            self.keep_range(sym.end_line, sym.end_line)
        else:
            head_end = body_start - 1 if body_start > sym.decl_line else sym.decl_line
            self.keep_range(sym.start_line, head_end)
            if sym.docstring_end_line and sym.docstring_end_line - body_start < MAX_DOCSTRING_LINES:
                self.keep_range(body_start, sym.docstring_end_line)
        # Non-member statements of the body (fields, class attributes, consts).
        covered: set[int] = set()
        if sym.docstring_end_line:
            covered.update(range(body_start, sym.docstring_end_line + 1))
        for cid in sym.children:
            child = self.index.symbols.get(cid)
            if child is not None:
                covered.update(range(child.start_line, child.end_line + 1))
        lo = body_start + (1 if self.brace else 0)
        hi = (sym.body_end_line or sym.end_line) - (1 if self.brace else 0)
        for n in range(lo, hi + 1):
            if n not in covered and self.line(n).strip():
                self.keep.add(n)

    def signature_stub(self, sym: Symbol) -> None:
        if sym.id in self.full_ids:
            self.full(sym)
            return
        bs, be = sym.body_start_line, sym.body_end_line
        if bs is None or be is None:
            self.full(sym)
            return
        if self.brace:
            if be <= bs + 1:
                self.full(sym)
                return
            self.keep_range(sym.start_line, bs)
            hidden = be - bs - 1
            indent = _indent_of(self.line(bs + 1)) or (_indent_of(self.line(bs)) + "    ")
            self.stubs_after.setdefault(bs, []).append(f"{indent}{self.comment} ⋯ {hidden} line{'s' if hidden != 1 else ''}")
            self.silent.update(range(bs + 1, be))
            self.keep_range(be, be)
        else:
            if bs <= sym.decl_line:
                self.full(sym)  # one-line def
                return
            self.keep_range(sym.start_line, bs - 1)
            last = bs - 1
            if sym.docstring_end_line and sym.docstring_end_line - bs < MAX_DOCSTRING_LINES:
                self.keep_range(bs, sym.docstring_end_line)
                last = sym.docstring_end_line
                if sym.docstring_end_line >= be:
                    return
            indent = _indent_of(self.line(bs))
            hidden = be - last
            self.stubs_after.setdefault(last, []).append(f"{indent}...  # ⋯ {hidden} line{'s' if hidden != 1 else ''}")
            self.silent.update(range(last + 1, be + 1))

    def outline(self, sym: Symbol) -> None:
        if sym.kind in CONTAINER_KINDS:
            self.header(sym)
            for cid in sym.children:
                child = self.index.symbols.get(cid)
                if child is None:
                    continue
                if (
                    child.kind in ("method", "function")
                    and self.used_members is not None
                    and child.id not in self.full_ids
                    and child.name not in self.used_members
                    and child.name not in _ALWAYS_OUTLINED
                ):
                    continue
                if child.kind in CONTAINER_KINDS:
                    self.outline(child)
                elif child.kind in ("method", "function"):
                    self.signature_stub(child)
                elif child.kind != "block":
                    self.full(child)
        elif sym.kind in ("method", "function"):
            self.signature_stub(sym)
        else:
            self.full(sym)

    def ensure_python_bodies(self) -> None:
        """A Python class whose body lost every statement needs ``...``."""
        if self.brace:
            return
        comments = set(self.fx.comment_lines)
        for sym in reversed(self.headers):
            bs = sym.body_start_line
            be = sym.body_end_line or sym.end_line
            if bs is None or bs <= sym.decl_line:
                continue
            if any(n in self.keep and n not in comments and self.line(n).strip() for n in range(bs, be + 1)):
                continue
            last = max((n for n in range(sym.start_line, be + 1) if n in self.keep), default=bs - 1)
            if any(self.stubs_after.get(n) for n in range(last, be + 1)):
                continue
            indent = _indent_of(self.line(bs)) or (_indent_of(self.line(sym.decl_line)) + "    ")
            self.stubs_after.setdefault(last, []).append(f"{indent}...")
            self.silent.update(n for n in range(last + 1, be + 1) if not self.line(n).strip())

    # -- output -------------------------------------------------------------
    def pruned_names(self, a: int, b: int) -> list[str]:
        names: list[str] = []
        for sid in self.index.by_file.get(self.path, []):
            s = self.index.symbols[sid]
            if a <= s.decl_line <= b and s.kind not in ("block",):
                label = s.qualname if s.kind != "impl" else s.name
                if label not in names:
                    names.append(label)
        return names

    def build(self, opts: RenderOptions, counter: TokenCounter) -> tuple[list[Segment], str]:
        comment_lines = set(self.fx.comment_lines) if opts.strip_comments else set()
        n_lines = len(self.lines)
        # Drop a trailing empty line produced by the final newline.
        if n_lines and self.lines[-1] == "":
            n_lines -= 1
        segments: list[Segment] = []
        width = len(str(n_lines))
        i = 1
        while i <= n_lines:
            if i in self.keep:
                j = i
                while j + 1 <= n_lines and (j + 1) in self.keep:
                    j += 1
                out: list[str] = []
                for n in range(i, j + 1):
                    for note in self.notes_before.get(n, []):
                        out.append(self._num(None, width, opts) + note)
                    if n in comment_lines and n not in self.notes_before:
                        pass
                    else:
                        out.append(self._num(n, width, opts) + self.line(n))
                    for stub in self.stubs_after.get(n, []):
                        out.append(self._num(None, width, opts) + stub)
                text = "\n".join(out)
                segments.append(Segment("code", i, j, text, tokens=counter.count(text)))
                i = j + 1
            else:
                j = i
                while j + 1 <= n_lines and (j + 1) not in self.keep:
                    j += 1
                visible = [n for n in range(i, j + 1) if n not in self.silent and self.line(n).strip()]
                chunk = self.lines[i - 1 : j]
                if visible and not (set(range(i, j + 1)) & self.silent) and self._cheap(i, j, counter):
                    # The marker would cost as much as the code: keep the code.
                    text = "\n".join(self._num(n, width, opts) + self.line(n) for n in range(i, j + 1) if n not in comment_lines)
                    if segments and segments[-1].kind == "code" and segments[-1].end == i - 1:
                        prev = segments[-1]
                        prev.text += "\n" + text
                        prev.end = j
                        prev.tokens = counter.count(prev.text)
                    else:
                        segments.append(Segment("code", i, j, text, tokens=counter.count(text)))
                    i = j + 1
                    continue
                if visible:
                    i0, j0 = visible[0], visible[-1]
                    chunk = self.lines[i0 - 1 : j0]
                    names = self.pruned_names(i0, j0)
                    shown = ", ".join(names[:4]) + (f", +{len(names) - 4} more" if len(names) > 4 else "")
                    nonblank = [ln for ln in chunk if ln.strip()]
                    indent = min((_indent_of(ln) for ln in nonblank), key=len) if nonblank else ""
                    count = j0 - i0 + 1
                    label = f"{count} lines pruned (L{i0}-L{j0})" if count > 1 else f"1 line pruned (L{i0})"
                    marker = f"{indent}{self.comment} ⋯ {label}" + (f": {shown}" if shown else "")
                    hidden_tokens = counter.count("\n".join(chunk))
                    segments.append(Segment("pruned", i0, j0, self._num(None, width, opts) + marker, names, hidden_tokens))
                elif segments and segments[-1].kind == "code" and j < n_lines and any(
                    n not in self.silent and not self.line(n).strip() for n in range(i, j + 1)
                ):
                    segments[-1].text += "\n"
                i = j + 1
        merged: list[Segment] = []
        for seg in segments:
            prev = merged[-1] if merged else None
            if prev is not None and prev.kind == "code" and seg.kind == "code" and seg.start == prev.end + 1:
                prev.text = prev.text + "\n" + seg.text
                prev.end = seg.end
                prev.tokens = counter.count(prev.text)
            else:
                merged.append(seg)
        text = "\n".join(s.text for s in merged)
        return merged, text

    def _cheap(self, i: int, j: int, counter: TokenCounter) -> bool:
        if j - i > 2:
            return False
        if any(self.index.symbols[s].decl_line in range(i, j + 1) for s in self.index.by_file.get(self.path, [])):
            return False  # never silently re-include a pruned definition
        original = counter.count("\n".join(self.lines[i - 1 : j]))
        return original <= 12

    @staticmethod
    def _num(n: int | None, width: int, opts: RenderOptions) -> str:
        if not opts.line_numbers:
            return ""
        return (str(n).rjust(width) if n is not None else " " * width) + " │ "


def plan_file(
    index: RepoIndex,
    path: str,
    nodes: list[SliceNode],
    highlights: dict[int, str] | None,
    opts: RenderOptions,
    used_members: set[str] | None = None,
) -> _FilePlan:
    plan = _FilePlan(index, path)
    plan.full_ids = {n.id for n in nodes if n.mode == "full"}
    plan.used_members = used_members
    used_names: set[str] = set()
    for node in sorted(nodes, key=lambda n: {"full": 0, "outline": 1, "header": 2}.get(n.mode, 3)):
        sym = index.symbols[node.id]
        if node.mode == "full":
            plan.full(sym)
        elif node.mode == "outline":
            plan.outline(sym)
        elif node.mode == "header":
            plan.header(sym)
        refs = sym.refs
        if node.mode == "header" or (node.mode == "outline" and sym.kind in CONTAINER_KINDS):
            refs = [*sym.refs]
            for cid in sym.children:
                child = index.symbols.get(cid)
                if child is not None and node.mode == "outline":
                    used_names.update(child.sig_refs)
        for r in refs:
            if r.receiver is None:
                used_names.add(r.name)
            elif r.receiver not in ("?",):
                used_names.add(r.receiver)
                used_names.add(r.receiver.split(".", 1)[0])
        if sym.owner:
            used_names.add(sym.owner)
    plan.ensure_python_bodies()
    if opts.include_imports and plan.keep:
        for b in plan.fx.imports:
            if b.start_line <= 0:
                continue
            if b.local in used_names or (b.wildcard and plan.fx.lang in ("go",)):
                plan.keep_range(b.start_line, b.end_line)
                for w in b.wrapper_lines:
                    plan.keep_range(w, w)
        for n in plan.fx.always_keep_lines:
            plan.keep_range(n, n)
    if highlights:
        for line, label in sorted(highlights.items()):
            if line in plan.keep:
                indent = _indent_of(plan.line(line))
                plan.notes_before.setdefault(line, []).append(f"{indent}{plan.comment} ▼ L{line}: {label}")
    return plan


def render_files(
    index: RepoIndex,
    graph: SliceGraph,
    highlights: dict[str, dict[int, str]],
    opts: RenderOptions,
    counter: TokenCounter,
) -> list[FileRender]:
    by_file: dict[str, list[SliceNode]] = {}
    for node in graph.nodes.values():
        sym = index.symbols[node.id]
        by_file.setdefault(sym.path, []).append(node)

    def file_rank(item: tuple[str, list[SliceNode]]) -> tuple:
        path, nodes = item
        best = min(nodes, key=lambda n: (n.hop, ROLE_ORDER.get(n.role, 9)))
        return (best.hop, ROLE_ORDER.get(best.role, 9), path)

    # Members accessed anywhere in the slice (``x.charge()``, ``self.url``):
    # outlined classes show only these, plus constructors.
    used_members: set[str] = set()
    for node in graph.nodes.values():
        if node.mode == "full":
            for r in index.symbols[node.id].refs:
                if r.receiver is not None:
                    used_members.add(r.name)
    renders: list[FileRender] = []
    for path, nodes in sorted(by_file.items(), key=file_rank):
        plan = plan_file(index, path, nodes, highlights.get(path), opts, used_members)
        segments, text = plan.build(opts, counter)
        fx = index.files[path]
        ordered = sorted(nodes, key=lambda n: index.symbols[n.id].start_line)
        renders.append(
            FileRender(
                path=path,
                lang=fx.lang,
                segments=segments,
                symbols=[n.id for n in ordered],
                file_tokens=fx.tokens,
                file_lines=fx.line_count,
                kept_tokens=counter.count(text),
                text=text,
            )
        )
    return renders


# ---------------------------------------------------------------- bundle text
def _node_label(index: RepoIndex, node: SliceNode) -> tuple[str, str, str, str]:
    sym = index.symbols[node.id]
    role = node.role if node.role not in ("callee", "caller") else f"{node.role} {node.hop}"
    name = sym.qualname + (" (outline)" if node.mode == "outline" else "")
    loc = f"{sym.path}:{sym.start_line}-{sym.end_line}"
    via = ""
    if node.via and node.via in index.symbols:
        arrow = {"calls": "←", "called_by": "→", "uses_type": "←", "uses_value": "←", "contains": "⊃"}.get(node.via_kind or "", "←")
        via = f"{arrow} {index.symbols[node.via].qualname}"
    return role, name, loc, via


def slice_map_lines(index: RepoIndex, graph: SliceGraph) -> list[str]:
    nodes = [n for n in graph.nodes.values() if n.role != "container"]
    nodes.sort(key=lambda n: (ROLE_ORDER.get(n.role, 9) if n.role in ("seed",) else 1, n.hop, ROLE_ORDER.get(n.role, 9), index.symbols[n.id].path, index.symbols[n.id].start_line))
    rows = [_node_label(index, n) for n in nodes]
    if not rows:
        return []
    w0 = max(len(r[0]) for r in rows)
    w1 = min(max(len(r[1]) for r in rows), 48)
    w2 = min(max(len(r[2]) for r in rows), 56)
    return [f"{r[0]:<{w0}}  {r[1]:<{w1}}  {r[2]:<{w2}}  {r[3]}".rstrip() for r in rows]


@dataclass
class BundleHeader:
    title: str
    summary: str
    prompt: str | None = None
    error_block: list[str] = field(default_factory=list)


def compose_bundle(
    fmt: str,
    header: BundleHeader,
    map_lines: list[str],
    files: list[FileRender],
) -> str:
    out: list[str] = []
    if fmt == "xml":
        if header.prompt:
            out += ["<task>", header.prompt.strip(), "</task>", ""]
        out.append(f"<context tool=\"ast-pack\" title=\"{_xml_attr(header.title)}\">")
        out.append(f"<summary>{_xml_text(header.summary)}</summary>")
        if header.error_block:
            out += ["<error>", *(_xml_text(x) for x in header.error_block), "</error>"]
        if map_lines:
            out += ["<slice_map>", *(_xml_text(x) for x in map_lines), "</slice_map>"]
        for f in files:
            out.append(f"<file path=\"{_xml_attr(f.path)}\" language=\"{f.lang}\" lines=\"{f.ranges_label()}\">")
            out.append(f.text)
            out.append("</file>")
        out.append("</context>")
        return "\n".join(out) + "\n"
    if fmt == "plain":
        if header.prompt:
            out += [header.prompt.strip(), ""]
        out += [header.title, header.summary, ""]
        if header.error_block:
            out += [*header.error_block, ""]
        if map_lines:
            out += ["Slice map:", *map_lines, ""]
        for f in files:
            out += [f"==> {f.path} (lines {f.ranges_label()}) <==", f.text, ""]
        return "\n".join(out).rstrip("\n") + "\n"
    # markdown
    if header.prompt:
        out += ["## Task", "", header.prompt.strip(), ""]
    out += [f"## Context: {header.title}", "", header.summary, ""]
    if header.error_block:
        out += ["### Error", "", "```text", *header.error_block, "```", ""]
    if map_lines:
        out += ["### Slice map", "", "```text", *map_lines, "```", ""]
    for f in files:
        fence = "````" if "```" in f.text else "```"
        out += [f"### {f.path} · lines {f.ranges_label()}", "", f"{fence}{FENCE.get(f.lang, '')}", f.text, fence, ""]
    return "\n".join(out).rstrip("\n") + "\n"


def _xml_attr(s: str) -> str:
    return s.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


def _xml_text(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
