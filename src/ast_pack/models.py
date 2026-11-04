"""Core data structures shared by the extractors, the index and the slicer.

All line numbers are 1-based and inclusive.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Symbol kinds, grouped by how the slicer treats them.
CALLABLE_KINDS = frozenset({"function", "method", "macro"})
TYPE_KINDS = frozenset({"class", "struct", "interface", "trait", "enum", "type", "union"})
VALUE_KINDS = frozenset({"const", "variable", "static"})
# Containers own member symbols (methods). ``impl`` and ``module`` are
# containers that are never pulled in on their own.
CONTAINER_KINDS = frozenset({"class", "interface", "trait", "impl", "module"})
# Pseudo symbols: top-level statements (``if __name__ == "__main__":`` ...).
BLOCK_KIND = "block"


def edge_kind_for(target_kind: str) -> str:
    """Edges are classified by what they point at, not by reference syntax."""
    if target_kind in CALLABLE_KINDS:
        return "call"
    if target_kind in TYPE_KINDS:
        return "type"
    if target_kind in VALUE_KINDS:
        return "value"
    return "ref"


@dataclass(slots=True)
class Ref:
    """A name referenced inside a symbol body.

    ``receiver`` is the text of the object the name was accessed on
    (``self`` in ``self.save()``, ``pkg`` in ``pkg.Func``), or ``None`` for a
    bare identifier. ``receiver == "?"`` means "accessed on a complex
    expression we cannot name" (``a().b()``).
    """

    name: str
    receiver: str | None = None
    line: int = 0
    call: bool = False  # the reference is the callee of a call expression


@dataclass(slots=True)
class ImportBinding:
    """One name bound in a file by an import / use statement.

    ``local`` is the name visible in the file. ``module`` is the raw module
    specifier (``./util``, ``pkg.sub``, ``crate::a::b``, ``github.com/x/y``).
    ``imported`` is the original exported name, or ``None`` when the binding
    is the module / namespace itself (``import x``, ``import * as ns``).
    ``wildcard`` marks ``from x import *`` / ``export * from``.
    """

    local: str
    module: str
    imported: str | None
    start_line: int
    end_line: int
    wildcard: bool = False
    reexport: bool = False
    # Lines that must be kept together with this import for the snippet to
    # stay syntactically valid (e.g. ``import (`` / ``)`` in Go).
    wrapper_lines: tuple[int, ...] = ()


@dataclass(slots=True)
class Symbol:
    id: str
    name: str
    qualname: str
    kind: str
    lang: str
    path: str
    start_line: int  # includes leading doc comments / decorators
    end_line: int
    decl_line: int  # line of the definition keyword itself
    signature: str
    # Outline rendering support: line where the body begins / ends.
    body_start_line: int | None = None
    body_end_line: int | None = None
    # Python: last line of a leading docstring inside the body.
    docstring_end_line: int | None = None
    parent: str | None = None
    owner: str | None = None  # owning type for methods (class / impl / receiver type)
    self_names: tuple[str, ...] = ()
    bases: tuple[str, ...] = ()
    refs: list[Ref] = field(default_factory=list)
    sig_refs: list[str] = field(default_factory=list)
    children: list[str] = field(default_factory=list)
    # Declared field / attribute types of a class or struct (``name -> type``).
    field_types: dict[str, str] = field(default_factory=dict)
    exported: bool = True
    tokens: int = 0

    @property
    def is_container(self) -> bool:
        return self.kind in CONTAINER_KINDS

    @property
    def line_count(self) -> int:
        return self.end_line - self.start_line + 1


@dataclass(slots=True)
class FileExtraction:
    path: str
    lang: str
    line_count: int
    tokens: int
    mtime_ns: int
    size: int
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[ImportBinding] = field(default_factory=list)
    comment_lines: list[int] = field(default_factory=list)
    always_keep_lines: list[int] = field(default_factory=list)  # e.g. Go ``package`` clause
    package: str | None = None
    parse_errors: int = 0


@dataclass(slots=True)
class Edge:
    source: str
    target: str
    kind: str  # call | type | value | ref
    confidence: float = 1.0
    line: int = 0
