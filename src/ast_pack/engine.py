"""High-level API: ``pack(index, PackOptions) -> PackResult``.

This is the one function the CLI, the HTTP/WebSocket server and library users
all call. It resolves targets to seed symbols, builds the slice, enforces an
optional token budget, renders the bundle and reports exact token savings.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import __version__
from .entry import Resolution, resolve_targets
from .index import RepoIndex
from .render import BundleHeader, FileRender, RenderOptions, compose_bundle, render_files, slice_map_lines
from .slicer import SliceGraph, WalkOptions, build_slice, drop_order

SCHEMA_VERSION = "1.0"
FORMATS = ("markdown", "xml", "plain")
DIRECTIONS = ("both", "callers", "callees")


@dataclass
class PackOptions:
    targets: list[str] = field(default_factory=list)
    depth: int = 2
    direction: str = "both"
    max_tokens: int | None = None
    max_fanout: int = 30
    type_depth: int = 2
    include_types: bool = True
    min_confidence: float = 0.5
    include_tests: bool = False
    format: str = "markdown"
    strip_comments: bool = False
    line_numbers: bool = False
    include_imports: bool = True
    slice_map: bool = True
    prompt: str | None = None
    depth_profile: bool = False
    profile_max_depth: int = 6

    def validate(self) -> None:
        if self.depth < 0:
            raise ValueError("depth must be >= 0")
        if self.direction not in DIRECTIONS:
            raise ValueError(f"direction must be one of {', '.join(DIRECTIONS)}")
        if self.format not in FORMATS:
            raise ValueError(f"format must be one of {', '.join(FORMATS)}")
        if self.max_tokens is not None and self.max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if not 0.0 <= self.min_confidence <= 1.0:
            raise ValueError("min_confidence must be between 0 and 1")

    def walk_options(self, depth: int | None = None) -> WalkOptions:
        return WalkOptions(
            depth=self.depth if depth is None else depth,
            direction=self.direction,
            max_fanout=self.max_fanout,
            type_depth=self.type_depth,
            include_types=self.include_types,
            min_confidence=self.min_confidence,
            include_tests=self.include_tests,
        )

    def render_options(self) -> RenderOptions:
        return RenderOptions(
            strip_comments=self.strip_comments,
            line_numbers=self.line_numbers,
            include_imports=self.include_imports,
        )


@dataclass
class PackResult:
    options: PackOptions
    resolution: Resolution
    graph: SliceGraph
    files: list[FileRender]
    bundle: str
    bundle_tokens: int
    repo_tokens: int
    touched_file_tokens: int
    tokenizer: str
    tokenizer_exact: bool
    dropped: list[str]
    elapsed_ms: float
    index: RepoIndex
    depth_profile: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.resolution.seeds)

    @property
    def saved_pct(self) -> float:
        if not self.repo_tokens:
            return 0.0
        return round(100.0 * (1 - self.bundle_tokens / self.repo_tokens), 2)

    @property
    def saved_vs_files_pct(self) -> float:
        if not self.touched_file_tokens:
            return 0.0
        return round(100.0 * (1 - self.bundle_tokens / self.touched_file_tokens), 2)

    def summary_line(self) -> str:
        n_sym = sum(1 for n in self.graph.nodes.values() if n.role != "container")

        def saving(total: int, pct: float) -> str:
            # On tiny inputs headers + slice map can outweigh the pruning.
            return f"saved {pct:.1f}%" if pct >= 0 else "smaller than the bundle overhead"

        return (
            f"{n_sym} symbols · {len(self.files)} files · {self.bundle_tokens:,} tokens "
            f"(repo {self.repo_tokens:,} → {saving(self.repo_tokens, self.saved_pct)}; "
            f"whole files {self.touched_file_tokens:,} → {saving(self.touched_file_tokens, self.saved_vs_files_pct)})"
        )

    def nodes_json(self) -> list[dict]:
        idx = self.index
        out = []
        for n in self.graph.nodes.values():
            s = idx.symbols[n.id]
            out.append(
                {
                    "id": s.id,
                    "name": s.name,
                    "qualname": s.qualname,
                    "kind": s.kind,
                    "language": s.lang,
                    "path": s.path,
                    "start_line": s.start_line,
                    "end_line": s.end_line,
                    "signature": s.signature,
                    "tokens": s.tokens,
                    "hop": n.hop,
                    "role": n.role,
                    "mode": n.mode,
                    "via": n.via,
                    "via_kind": n.via_kind,
                    "confidence": n.confidence,
                    "truncated_neighbors": self.graph.truncated.get(n.id, 0),
                }
            )
        return out

    def edges_json(self) -> list[dict]:
        return [
            {"source": e.source, "target": e.target, "kind": e.kind, "confidence": e.confidence, "line": e.line}
            for e in self.graph.edges(self.index)
        ]

    def to_dict(self, include_bundle: bool = True) -> dict:
        r = self.resolution
        data = {
            "schema_version": SCHEMA_VERSION,
            "tool": "ast-pack",
            "version": __version__,
            "command": "pack",
            "ok": self.ok,
            "query": {
                "targets": self.options.targets,
                "kind": r.kind,
                "depth": self.options.depth,
                "direction": self.options.direction,
                "max_tokens": self.options.max_tokens,
                "format": self.options.format,
            },
            "seeds": r.seeds,
            "stats": {
                "symbols": sum(1 for n in self.graph.nodes.values() if n.role != "container"),
                "files": len(self.files),
                "bundle_tokens": self.bundle_tokens,
                "repo_tokens": self.repo_tokens,
                "touched_file_tokens": self.touched_file_tokens,
                "saved_pct": self.saved_pct,
                "saved_vs_files_pct": self.saved_vs_files_pct,
                "tokenizer": self.tokenizer,
                "tokenizer_exact": self.tokenizer_exact,
                "elapsed_ms": round(self.elapsed_ms, 2),
                "index_generation": self.index.generation,
            },
            "nodes": self.nodes_json(),
            "edges": self.edges_json(),
            "files": [f.to_dict() for f in self.files],
            "dropped": self.dropped,
            "warnings": r.warnings,
            "suggestions": r.suggestions,
            "trace": None,
            "depth_profile": self.depth_profile,
        }
        if r.kind in ("trace", "mixed") and r.frames:
            data["trace"] = {
                "language": r.trace_language,
                "error": r.error_message,
                "crash_site": _frame_json(r.crash_site) if r.crash_site else None,
                "frames": [_frame_json(f) for f in r.frames],
            }
        if include_bundle:
            data["bundle"] = self.bundle
        return data


def _frame_json(f) -> dict:
    return {"path": f.path, "line": f.line, "function": f.func, "repo_path": f.repo_path, "symbol": f.symbol_id}


def _title(options: PackOptions, res: Resolution, index: RepoIndex) -> str:
    if res.kind == "trace" and res.crash_site and res.crash_site.symbol_id:
        return f"stack trace → {index.symbols[res.crash_site.symbol_id].qualname}"
    labels = []
    for t in options.targets:
        t = t.strip()
        labels.append("stack trace" if "\n" in t else t)
    return ", ".join(labels) or "(no target)"


def _error_block(res: Resolution) -> list[str]:
    if res.kind not in ("trace", "mixed") or not res.frames:
        return []
    lines = []
    if res.error_message:
        lines.append(res.error_message)
    if res.crash_site and res.crash_site.repo_path:
        lines.append(f"crash site: {res.crash_site.repo_path}:{res.crash_site.line}")
    for f in res.frames:
        if f.repo_path:
            lines.append(f"  at {f.func} ({f.repo_path}:{f.line})" if f.func else f"  at {f.repo_path}:{f.line}")
    return lines


def _render(index: RepoIndex, options: PackOptions, res: Resolution, graph: SliceGraph) -> tuple[list[FileRender], str]:
    counter = index.counter
    files = render_files(index, graph, res.highlight_lines, options.render_options(), counter)
    tmp = PackResult(options, res, graph, files, "", 0, 0, 0, "", False, [], 0.0, index)
    header = BundleHeader(
        title=_title(options, res, index),
        summary="",
        prompt=options.prompt,
        error_block=_error_block(res),
    )
    map_lines = slice_map_lines(index, graph) if options.slice_map else []
    # Two passes: the summary line contains the bundle's own token count.
    touched = sum(f.file_tokens for f in files)
    tmp.repo_tokens = index.total_tokens
    tmp.touched_file_tokens = touched
    tmp.bundle_tokens = counter.count(compose_bundle(options.format, header, map_lines, files))
    # The summary states the bundle's own token count, which depends on the
    # summary text: iterate to a fixed point (converges in 1-2 rounds).
    bundle = ""
    for _ in range(4):
        header.summary = _summary_text(options, tmp)
        bundle = compose_bundle(options.format, header, map_lines, files)
        actual = counter.count(bundle)
        if actual == tmp.bundle_tokens:
            break
        tmp.bundle_tokens = actual
    return files, bundle


def _summary_text(options: PackOptions, r: PackResult) -> str:
    dirn = {"both": "callers + callees", "callers": "callers only", "callees": "callees only"}[options.direction]
    return f"ast-pack · depth {options.depth} ({dirn}) · {r.summary_line()}"


def pack(index: RepoIndex, options: PackOptions) -> PackResult:
    options.validate()
    t0 = time.perf_counter()
    res = resolve_targets(index, options.targets)
    walk = options.walk_options()
    graph = build_slice(index, res.seeds, walk)
    files, bundle = _render(index, options, res, graph)
    counter = index.counter
    tokens = counter.count(bundle)
    dropped: list[str] = []
    if options.max_tokens is not None and tokens > options.max_tokens:
        order = drop_order(index, graph)
        excluded: set[str] = set()
        # Drop in growing batches, re-rendering exactly after each batch.
        pos = 0
        while tokens > options.max_tokens and pos < len(order):
            over = tokens - options.max_tokens
            batch: list[str] = []
            freed = 0
            while pos < len(order) and (freed < over or not batch):
                nid = order[pos]
                pos += 1
                if nid in excluded:
                    continue
                batch.append(nid)
                freed += index.symbols[nid].tokens
            excluded.update(batch)
            graph = build_slice(index, res.seeds, walk, exclude=excluded)
            files, bundle = _render(index, options, res, graph)
            tokens = counter.count(bundle)
            order = [n for n in order if n in graph.nodes] + [n for n in drop_order(index, graph) if n not in order]
            pos = 0
        dropped = sorted(excluded)
        if tokens > options.max_tokens:
            res.warnings.append(
                f"bundle is {tokens:,} tokens; the seeds alone exceed --max-tokens {options.max_tokens:,}"
            )
    result = PackResult(
        options=options,
        resolution=res,
        graph=graph,
        files=files,
        bundle=bundle,
        bundle_tokens=tokens,
        repo_tokens=index.total_tokens,
        touched_file_tokens=sum(f.file_tokens for f in files),
        tokenizer=counter.name,
        tokenizer_exact=counter.exact,
        dropped=dropped,
        elapsed_ms=0.0,
        index=index,
    )
    if options.depth_profile and res.seeds:
        result.depth_profile = depth_profile(index, options, res)
    result.elapsed_ms = (time.perf_counter() - t0) * 1000
    return result


def depth_profile(index: RepoIndex, options: PackOptions, res: Resolution) -> list[dict]:
    """Bundle size at every hop depth (lets UIs preview the depth slider)."""
    out = []
    prev_nodes = -1
    for d in range(0, max(options.profile_max_depth, options.depth) + 1):
        graph = build_slice(index, res.seeds, options.walk_options(d))
        files, bundle = _render(index, options, res, graph)
        n = sum(1 for x in graph.nodes.values() if x.role != "container")
        out.append({"depth": d, "symbols": n, "files": len(files), "tokens": index.counter.count(bundle)})
        if n == prev_nodes and d > options.depth:
            break  # graph saturated
        prev_nodes = n
    return out
