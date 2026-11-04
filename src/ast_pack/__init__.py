"""ast-pack: Tree-sitter powered surgical context packing for LLMs.

Parse a repository into a cross-file symbol graph, start from an entry point
(symbol name, ``file:line`` or a raw stack trace), walk callers/callees up to a
hop depth, pull in the type definitions and constants they need, and emit a
dense, syntactically valid context bundle with exact file and line headers.

Library usage::

    from ast_pack import RepoIndex, PackOptions, pack

    index = RepoIndex.build(".")
    result = pack(index, PackOptions(targets=["processPayment"], depth=2))
    print(result.bundle)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__version__ = "0.1.0"
__author__ = "Azimxon Vaxobov (Ginckl)"

if TYPE_CHECKING:  # pragma: no cover
    from .engine import PackOptions, PackResult, pack
    from .index import RepoIndex

__all__ = ["PackOptions", "PackResult", "RepoIndex", "pack", "__version__"]


def __getattr__(name: str) -> Any:
    # Lazy imports keep ``ast-pack --version`` and ``--help`` instant.
    if name in ("PackOptions", "PackResult", "pack"):
        from . import engine

        return getattr(engine, name)
    if name == "RepoIndex":
        from .index import RepoIndex

        return RepoIndex
    raise AttributeError(name)
