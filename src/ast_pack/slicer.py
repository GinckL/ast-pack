"""Graph walk: from seed symbols to the set of symbols that belong in a slice.

Two breadth-first walks start at the seeds:

* **callees** – follows outgoing ``call`` edges (what the seed executes),
* **callers** – follows incoming ``call`` edges (who reaches the seed).

They never mix (a caller's other callees are siblings, not context), and each
node's fan-out is capped so a utility called from 500 places cannot flood the
slice; the closest callers (same file, then same directory) win.

Then a **closure** pass pulls in everything the included code needs to be
understood but that is not "behaviour": type definitions (classes, structs,
interfaces, traits, enums, aliases) and constants/globals, recursively up to
``type_depth`` levels. Python/TypeScript classes reached only as types are
rendered as outlines (fields + method signatures); methods pull in the header
of their enclosing class/impl so the code stays syntactically valid.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from .index import RepoIndex, _dirname
from .models import CALLABLE_KINDS, TYPE_KINDS, VALUE_KINDS, Edge, Symbol

ROLE_ORDER = {"seed": 0, "callee": 1, "caller": 2, "type": 3, "value": 4, "container": 5}


@dataclass(slots=True)
class SliceNode:
    id: str
    hop: int
    role: str  # seed | callee | caller | type | value | container
    mode: str  # full | outline | header
    via: str | None = None
    via_kind: str | None = None
    confidence: float = 1.0
    level: int = 0  # closure level for type/value nodes


@dataclass
class SliceGraph:
    nodes: dict[str, SliceNode] = field(default_factory=dict)
    truncated: dict[str, int] = field(default_factory=dict)

    def edges(self, index: RepoIndex) -> list[Edge]:
        out: list[Edge] = []
        for nid in self.nodes:
            for e in index.edges_out.get(nid, []):
                if e.target in self.nodes:
                    out.append(e)
        return out


@dataclass
class WalkOptions:
    depth: int = 2
    direction: str = "both"  # both | callers | callees
    max_fanout: int = 30
    type_depth: int = 2
    include_types: bool = True
    min_confidence: float = 0.5
    include_tests: bool = False


def _rank(index: RepoIndex, origin: Symbol, other: Symbol, conf: float) -> tuple:
    return (
        -conf,
        other.path != origin.path,
        _dirname(other.path) != _dirname(origin.path),
        "test" in other.path.lower(),
        other.path,
        other.start_line,
    )


def call_walk(index: RepoIndex, seeds: list[str], opts: WalkOptions, exclude: set[str] | None = None) -> SliceGraph:
    graph = SliceGraph()
    exclude = exclude or set()
    skip_tests = not opts.include_tests and not any(index.is_test(index.symbols[s]) for s in seeds if s in index.symbols)
    for s in seeds:
        if s in index.symbols:
            graph.nodes[s] = SliceNode(s, 0, "seed", "full")

    def bfs(forward: bool) -> None:
        queue: deque[str] = deque(s for s in seeds if s in index.symbols)
        dist = {s: 0 for s in queue}
        while queue:
            cur = queue.popleft()
            d = dist[cur]
            if d >= opts.depth:
                continue
            origin = index.symbols[cur]
            edges = index.edges_out.get(cur, []) if forward else index.edges_in.get(cur, [])
            cands: list[tuple[Symbol, Edge]] = []
            for e in edges:
                if e.kind != "call" or e.confidence < opts.min_confidence:
                    continue
                other_id = e.target if forward else e.source
                if other_id in exclude:
                    continue
                other = index.symbols.get(other_id)
                if other is None or (skip_tests and index.is_test(other)):
                    continue
                cands.append((other, e))
            cands.sort(key=lambda t: _rank(index, origin, t[0], t[1].confidence))
            if len(cands) > opts.max_fanout:
                graph.truncated[cur] = graph.truncated.get(cur, 0) + len(cands) - opts.max_fanout
                cands = cands[: opts.max_fanout]
            for other, e in cands:
                if other.id in dist:
                    continue
                dist[other.id] = d + 1
                queue.append(other.id)
                if other.id not in graph.nodes:
                    graph.nodes[other.id] = SliceNode(
                        other.id,
                        d + 1,
                        "callee" if forward else "caller",
                        "full",
                        via=cur,
                        via_kind="calls" if forward else "called_by",
                        confidence=e.confidence,
                    )

    if opts.direction in ("both", "callees"):
        bfs(True)
    if opts.direction in ("both", "callers"):
        bfs(False)
    return graph


def closure(index: RepoIndex, graph: SliceGraph, opts: WalkOptions, exclude: set[str] | None = None) -> None:
    """Add type/value dependencies and enclosing containers to ``graph`` in place."""
    exclude = exclude or set()
    skip_tests = not opts.include_tests and not any(n.role == "seed" and index.is_test(index.symbols[n.id]) for n in graph.nodes.values())
    if opts.include_types:
        frontier = [(nid, 0) for nid in list(graph.nodes)]
        while frontier:
            next_frontier: list[tuple[str, int]] = []
            for nid, level in frontier:
                src = graph.nodes[nid]
                sym = index.symbols[nid]
                edges = index.edges_out.get(nid, [])
                if src.mode == "outline" and sym.kind in TYPE_KINDS:
                    # Outlined classes expose member signatures: pull their types.
                    for child_id in sym.children:
                        edges = [*edges, *(
                            e for e in index.edges_out.get(child_id, [])
                            if e.kind == "type" and index.symbols[e.target].name in index.symbols[child_id].sig_refs
                        )]
                for e in edges:
                    if e.kind not in ("type", "value") or e.confidence < opts.min_confidence:
                        continue
                    if e.target in exclude:
                        continue
                    target = index.symbols[e.target]
                    if skip_tests and index.is_test(target):
                        continue
                    existing = graph.nodes.get(e.target)
                    if existing is not None:
                        if existing.role == "container" and target.kind in TYPE_KINDS:
                            existing.role = "type"
                            existing.mode = _type_mode(target)
                            existing.via, existing.via_kind = nid, "uses_type"
                        continue
                    lvl = level + 1
                    if lvl > opts.type_depth:
                        continue
                    if e.kind == "type":
                        node = SliceNode(e.target, src.hop, "type", _type_mode(target), nid, "uses_type", e.confidence, lvl)
                    else:
                        node = SliceNode(e.target, src.hop, "value", "full", nid, "uses_value", e.confidence, lvl)
                    graph.nodes[e.target] = node
                    next_frontier.append((e.target, lvl))
            frontier = next_frontier
    # Enclosing containers (class / impl / trait / namespace headers).
    for nid in list(graph.nodes):
        sym = index.symbols[nid]
        parent_id = sym.parent
        while parent_id:
            parent = index.symbols.get(parent_id)
            if parent is None:
                break
            if parent_id not in graph.nodes:
                graph.nodes[parent_id] = SliceNode(parent_id, graph.nodes[nid].hop, "container", "header", nid, "contains")
            parent_id = parent.parent


def _type_mode(sym: Symbol) -> str:
    if sym.kind == "class" and sym.lang in ("python", "typescript", "tsx", "javascript"):
        return "outline"
    return "full"


def build_slice(index: RepoIndex, seeds: list[str], opts: WalkOptions, exclude: set[str] | None = None) -> SliceGraph:
    graph = call_walk(index, seeds, opts, exclude)
    closure(index, graph, opts, exclude)
    return graph


def drop_order(index: RepoIndex, graph: SliceGraph) -> list[str]:
    """Nodes in the order they should be dropped to meet a token budget."""
    cands = [n for n in graph.nodes.values() if n.role not in ("seed", "container")]
    return [
        n.id
        for n in sorted(
            cands,
            key=lambda n: (
                -n.hop,
                -n.level,
                -ROLE_ORDER.get(n.role, 9),
                n.confidence,
                -index.symbols[n.id].tokens,
            ),
        )
    ]


__all__ = [
    "CALLABLE_KINDS",
    "VALUE_KINDS",
    "SliceGraph",
    "SliceNode",
    "WalkOptions",
    "build_slice",
    "drop_order",
]
