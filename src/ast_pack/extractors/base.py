"""Shared machinery for the per-language Tree-sitter extractors.

An extractor turns one source file into:

* ``Symbol`` records (functions, methods, classes, structs, interfaces,
  traits, enums, type aliases, constants, module-level variables) with exact
  line ranges, outline anchors (where bodies start/end) and the names each
  symbol references;
* ``ImportBinding`` records describing which local names come from which
  module, used later for cross-file resolution;
* the set of comment-only lines (for ``--strip-comments``).

Reference collection is a top-down walk. Each language implements
``visit(node, out)`` which either records references for ``node`` and
returns the children to descend into, or returns ``None`` to descend into all
named children. Local bindings (parameters, assignment targets, loop
variables...) are collected separately and filtered out of bare references.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator

from tree_sitter import Node

from ..models import FileExtraction, ImportBinding, Ref, Symbol

_WS_RE = re.compile(r"\s+")
_CALL_TYPES = frozenset({"call", "call_expression", "new_expression", "macro_invocation"})


def is_call_target(node: Node) -> bool:
    """True when ``node`` (or the member expression it names) is being called."""
    parent = node.parent
    if parent is None:
        return False
    if parent.type in ("member_expression", "attribute", "selector_expression", "field_expression", "scoped_identifier"):
        # ``x.name`` where ``name`` is ``node``: check whether the whole access is called.
        node, parent = parent, parent.parent
        if parent is None:
            return False
    if parent.type in ("generic_function", "await_expression", "non_null_expression"):
        node, parent = parent, parent.parent
        if parent is None:
            return False
    if parent.type not in _CALL_TYPES:
        return False
    fn = parent.child_by_field_name("function") or parent.child_by_field_name("constructor") or parent.child_by_field_name("macro")
    return fn is not None and fn.id == node.id


class BaseExtractor:
    lang: str = ""
    comment_types: frozenset[str] = frozenset({"comment"})

    def __init__(self, path: str, source: bytes, lang: str) -> None:
        self.path = path
        self.src = source
        self.lang = lang
        self.symbols: list[Symbol] = []
        self.imports: list[ImportBinding] = []
        self.always_keep: list[int] = []
        self.package: str | None = None
        self._ids: set[str] = set()
        self._lines = source.split(b"\n")

    # ------------------------------------------------------------------ utils
    def text(self, node: Node | None) -> str:
        if node is None:
            return ""
        return self.src[node.start_byte : node.end_byte].decode("utf-8", "replace")

    @staticmethod
    def start_line(node: Node) -> int:
        return node.start_point.row + 1

    @staticmethod
    def end_line(node: Node) -> int:
        # A node that ends exactly at column 0 ends on the previous line
        # (line comments include their trailing newline in some grammars).
        row, col = node.end_point
        if col == 0 and row > node.start_point.row:
            return row
        return row + 1

    def line_text(self, line: int) -> str:
        if 1 <= line <= len(self._lines):
            return self._lines[line - 1].decode("utf-8", "replace")
        return ""

    def leading_start(self, node: Node, extra_types: Iterable[str] = ()) -> int:
        """First line of the doc comments / attributes glued above ``node``."""
        glue = set(self.comment_types) | set(extra_types)
        start = self.start_line(node)
        prev = node.prev_named_sibling
        while prev is not None and prev.type in glue and self.end_line(prev) >= start - 1:
            # Do not swallow a trailing comment that sits on the previous
            # statement's line (``x = 1  # note``).
            prev_prev = prev.prev_named_sibling
            if (
                prev.type in self.comment_types
                and prev_prev is not None
                and self.end_line(prev_prev) == self.start_line(prev)
            ):
                break
            start = self.start_line(prev)
            prev = prev_prev
        return start

    def signature(self, node: Node, body: Node | None) -> str:
        end = body.start_byte if body is not None else node.end_byte
        raw = self.src[node.start_byte : end].decode("utf-8", "replace")
        if body is None:
            raw = raw.split("\n", 1)[0]
        sig = _WS_RE.sub(" ", raw).strip().rstrip("{").rstrip(":").strip()
        return sig[:240]

    def make_id(self, qualname: str, line: int) -> str:
        base = f"{self.path}::{qualname}"
        if base not in self._ids:
            self._ids.add(base)
            return base
        alt = f"{base}@L{line}"
        self._ids.add(alt)
        return alt

    def add_symbol(
        self,
        node: Node,
        name: str,
        kind: str,
        *,
        qual_prefix: str = "",
        parent: Symbol | None = None,
        body: Node | None = None,
        start_line: int | None = None,
        owner: str | None = None,
        self_names: tuple[str, ...] = (),
        bases: tuple[str, ...] = (),
        exported: bool = True,
        sig_node: Node | None = None,
        decl_node: Node | None = None,
    ) -> Symbol:
        qualname = f"{qual_prefix}.{name}" if qual_prefix else name
        decl = decl_node or node
        start = start_line if start_line is not None else self.start_line(node)
        sym = Symbol(
            id=self.make_id(qualname, self.start_line(decl)),
            name=name,
            qualname=qualname,
            kind=kind,
            lang=self.lang,
            path=self.path,
            start_line=start,
            end_line=self.end_line(node),
            decl_line=self.start_line(decl),
            signature=self.signature(sig_node or decl, body),
            body_start_line=self.start_line(body) if body is not None else None,
            body_end_line=self.end_line(body) if body is not None else None,
            parent=parent.id if parent else None,
            owner=owner,
            self_names=self_names,
            bases=bases,
            exported=exported,
        )
        if parent is not None:
            parent.children.append(sym.id)
        self.symbols.append(sym)
        return sym

    # --------------------------------------------------------- reference walk
    def visit(self, node: Node, out: list[Ref]) -> list[Node] | None:  # pragma: no cover - abstract
        raise NotImplementedError

    def bindings(self, node: Node, out: set[str]) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def type_hints(self, node: Node, out: dict[str, str]) -> None:
        """Record ``local name -> type name`` for typed parameters / declarations."""
        return None

    def collect_refs(
        self, roots: Iterable[Node], exclude: set[int] | None = None
    ) -> tuple[list[Ref], set[str]]:
        refs: list[Ref] = []
        local: set[str] = set()
        self._local_types: dict[str, str] = {}
        exclude = exclude or set()
        stack: list[Node] = [r for r in roots if r is not None]
        stack.reverse()
        while stack:
            node = stack.pop()
            if node.id in exclude:
                continue
            if node.type in self.comment_types:
                continue
            self.bindings(node, local)
            self.type_hints(node, self._local_types)
            children = self.visit(node, refs)
            if children is None:
                children = node.named_children
            for child in reversed(children):
                if child is not None:
                    stack.append(child)
        return refs, local

    @staticmethod
    def finalize_refs(
        refs: list[Ref],
        local: set[str],
        own_name: str,
        self_names: tuple[str, ...] = (),
        types: dict[str, str] | None = None,
    ) -> list[Ref]:
        types = types or {}
        keep_receivers = {"self", "this", "Self", "super", *self_names}
        seen: set[tuple[str, str | None]] = set()
        result: list[Ref] = []
        for ref in refs:
            if ref.receiver is None and (ref.name in local or ref.name == own_name):
                continue
            head, _, rest = (ref.receiver or "").partition(".")
            if ref.receiver is not None and head in local and head not in keep_receivers:
                typ = types.get(head)
                # Receiver rooted at a local variable: typed (``<Type>.field``) or unknown.
                if typ:
                    ref = Ref(ref.name, f"<{typ}>" + (f".{rest}" if rest else ""), ref.line, ref.call)
                else:
                    ref = Ref(ref.name, "?", ref.line, ref.call)
            key = (ref.name, ref.receiver)
            if key in seen:
                if ref.call:
                    for i, prev in enumerate(result):
                        if (prev.name, prev.receiver) == key and not prev.call:
                            result[i] = ref
                continue
            seen.add(key)
            result.append(ref)
        return result

    def set_refs(
        self,
        sym: Symbol,
        roots: Iterable[Node],
        exclude: set[int] | None = None,
        sig_roots: Iterable[Node] = (),
        extra_local: Iterable[str] = (),
    ) -> None:
        refs, local = self.collect_refs(roots, exclude)
        types = self._local_types
        local.update(extra_local)
        sym.refs = self.finalize_refs(refs, local, sym.name, sym.self_names, types)
        if sig_roots:
            sig, sig_local = self.collect_refs(sig_roots)
            sym.sig_refs = sorted(
                {r.name for r in sig if r.receiver is None and r.name not in sig_local}
            )

    # -------------------------------------------------------------- comments
    def comment_only_lines(self, root: Node) -> list[int]:
        lines: list[int] = []
        for node in iter_nodes(root):
            if node.type not in self.comment_types:
                continue
            first = self.start_line(node)
            last = self.end_line(node)
            before = self.line_text(first)[: node.start_point.column]
            after_line = self.line_text(last)
            after = after_line[node.end_point.column :] if node.end_point.row + 1 == last else ""
            if before.strip() or after.strip():
                continue
            lines.extend(range(first, last + 1))
        return lines

    # ------------------------------------------------------------------- run
    def extract(self, root: Node) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def build(self, root: Node, *, mtime_ns: int, size: int, tokens: int) -> FileExtraction:
        self.extract(root)
        return FileExtraction(
            path=self.path,
            lang=self.lang,
            line_count=len(self._lines),
            tokens=tokens,
            mtime_ns=mtime_ns,
            size=size,
            symbols=self.symbols,
            imports=self.imports,
            comment_lines=self.comment_only_lines(root),
            always_keep_lines=sorted(set(self.always_keep)),
            package=self.package,
            parse_errors=count_errors(root),
        )


_TYPE_TOKEN_RE = re.compile(r"[A-Za-z_][\w.]*")
# Wrappers that do not change which methods are callable on the value.
_TRANSPARENT = frozenset(
    {
        "Optional", "Union", "None", "Annotated", "Final", "ClassVar", "Awaitable", "Promise",
        "Readonly", "Partial", "Required", "NonNullable", "Box", "Rc", "Arc", "RefCell", "Cell",
        "Mutex", "RwLock", "Option", "Pin", "mut", "dyn", "impl", "const", "readonly", "null",
        "undefined", "typing", "t", "std", "sync", "rc", "cell", "boxed", "sync.Mutex",
    }
)
# Collections: methods are called on the collection, not on the element type.
_OPAQUE = frozenset(
    {
        "list", "List", "dict", "Dict", "set", "Set", "tuple", "Tuple", "Sequence", "Iterable",
        "Iterator", "Mapping", "Array", "ReadonlyArray", "Map", "Record", "Vec", "HashMap",
        "BTreeMap", "HashSet", "VecDeque", "Result", "map", "chan", "func", "type", "Type",
        "str", "int", "float", "bool", "bytes", "string", "number", "boolean", "any", "unknown",
        "object", "Any", "error", "interface", "u8", "u16", "u32", "u64", "i32", "i64", "usize",
        "isize", "f32", "f64", "String", "Callable", "Function",
    }
)


def main_type(text: str) -> str | None:
    """The user-defined type a declaration's methods dispatch on, if any.

    ``Optional[Gateway]`` -> ``Gateway``; ``*ledger.Ledger`` -> ``ledger.Ledger``;
    ``&mut Arc<Invoice>`` -> ``Invoice``; ``list[Card]`` -> ``None``.
    """
    if text.lstrip().startswith("[]"):
        return None
    for tok in _TYPE_TOKEN_RE.findall(text):
        if tok in _TRANSPARENT:
            continue
        if tok in _OPAQUE or tok.split(".")[-1] in _OPAQUE:
            return None
        return tok
    return None


def iter_nodes(root: Node) -> Iterator[Node]:
    cursor = root.walk()
    reached_root = False
    while not reached_root:
        yield cursor.node
        if cursor.goto_first_child():
            continue
        if cursor.goto_next_sibling():
            continue
        retracing = True
        while retracing:
            if not cursor.goto_parent():
                retracing = False
                reached_root = True
            elif cursor.goto_next_sibling():
                retracing = False


def count_errors(root: Node) -> int:
    if not root.has_error:
        return 0
    return sum(1 for n in iter_nodes(root) if n.type == "ERROR" or n.is_missing)


def identifiers_in(node: Node | None, types: frozenset[str], skip_fields: dict[str, frozenset[str]] | None = None) -> Iterator[Node]:
    """Yield identifier-like nodes inside a binding pattern."""
    if node is None:
        return
    if node.type in types:
        yield node
        return
    for i, child in enumerate(node.children):
        if not child.is_named:
            continue
        if skip_fields:
            fname = node.field_name_for_child(i)
            if fname and fname in skip_fields.get(node.type, frozenset()):
                continue
        yield from identifiers_in(child, types, skip_fields)
