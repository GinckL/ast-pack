"""Model Context Protocol server (JSON-RPC 2.0 over stdio, newline-delimited).

Register it with an MCP client, e.g. Claude Code::

    claude mcp add ast-pack -- ast-pack mcp -C /path/to/repo

Tools:

* ``pack_context`` – build a context bundle for a symbol, ``file:line`` or a
  pasted stack trace (returns the bundle as text plus structured stats);
* ``search_symbols`` – fuzzy symbol search;
* ``repo_stats`` – index statistics.

Each tool takes an optional ``repo`` argument; indexes are cached per root and
refreshed incrementally (only changed files are re-parsed) on every call.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .index import IndexOptions, RepoIndex

PROTOCOL_VERSION = "2025-06-18"

TOOLS = [
    {
        "name": "pack_context",
        "title": "Pack surgical code context",
        "description": (
            "Build a minimal, syntactically valid code context for an LLM from a symbol name "
            "(e.g. processPayment, Class.method, path/file.py::name), a file:line, or a raw stack "
            "trace (Python, Node.js, Go, Rust). Walks the call graph (callers and callees) up to "
            "`depth` hops, includes the type definitions and constants the code uses, and prunes "
            "everything else. Use this instead of reading whole files."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "symbol, file:line, file path, or stack trace text"},
                "depth": {"type": "integer", "minimum": 0, "maximum": 10, "default": 2},
                "direction": {"type": "string", "enum": ["both", "callers", "callees"], "default": "both"},
                "max_tokens": {"type": "integer", "minimum": 1, "description": "token budget"},
                "format": {"type": "string", "enum": ["markdown", "xml", "plain"], "default": "markdown"},
                "repo": {"type": "string", "description": "repository root (default: server's root)"},
            },
            "required": ["target"],
        },
    },
    {
        "name": "search_symbols",
        "title": "Search code symbols",
        "description": "Fuzzy-search functions, methods, classes, structs, interfaces, traits, enums and constants by name.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
                "repo": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "repo_stats",
        "title": "Repository index statistics",
        "description": "Files, symbols, call-graph edges and token totals per language for the repository.",
        "inputSchema": {"type": "object", "properties": {"repo": {"type": "string"}}},
    },
]


class McpServer:
    def __init__(self, default_root: str, options: IndexOptions | None = None) -> None:
        self.default_root = str(Path(default_root).expanduser().resolve())
        self.options = options or IndexOptions()
        self.indexes: dict[str, RepoIndex] = {}

    def index_for(self, repo: str | None) -> RepoIndex:
        root = str(Path(repo).expanduser().resolve()) if repo else self.default_root
        if not Path(root).is_dir():
            raise ValueError(f"repository directory not found: {root}")
        idx = self.indexes.get(root)
        if idx is None:
            idx = RepoIndex.build(root, self.options)
            self.indexes[root] = idx
        else:
            idx.refresh()
        return idx

    # ------------------------------------------------------------- tools
    def call_tool(self, name: str, args: dict[str, Any]) -> dict:
        if name == "pack_context":
            from .engine import PackOptions, pack

            target = args.get("target")
            if not isinstance(target, str) or not target.strip():
                return _tool_error("`target` is required")
            opts = PackOptions(
                targets=[target],
                depth=int(args.get("depth", 2)),
                direction=str(args.get("direction", "both")),
                max_tokens=int(args["max_tokens"]) if args.get("max_tokens") else None,
                format=str(args.get("format", "markdown")),
            )
            try:
                opts.validate()
                result = pack(self.index_for(args.get("repo")), opts)
            except ValueError as exc:
                return _tool_error(str(exc))
            if not result.ok:
                msg = "; ".join(result.resolution.warnings) or "nothing matched"
                if result.resolution.suggestions:
                    msg += "\nDid you mean: " + ", ".join(result.resolution.suggestions)
                return _tool_error(msg)
            data = result.to_dict(include_bundle=False)
            structured = {
                "stats": data["stats"],
                "seeds": data["seeds"],
                "symbols": [
                    {k: n[k] for k in ("id", "kind", "path", "start_line", "end_line", "hop", "role", "mode")}
                    for n in data["nodes"]
                ],
                "warnings": data["warnings"],
                "trace": data["trace"],
            }
            return {
                "content": [{"type": "text", "text": result.bundle}],
                "structuredContent": structured,
                "isError": False,
            }
        if name == "search_symbols":
            from .cli import symbol_json

            query = args.get("query")
            if not isinstance(query, str) or not query.strip():
                return _tool_error("`query` is required")
            try:
                idx = self.index_for(args.get("repo"))
            except ValueError as exc:
                return _tool_error(str(exc))
            hits = [symbol_json(s, score) for score, s in idx.search(query, limit=int(args.get("limit", 20)))]
            text = "\n".join(f"{h['qualname']}  {h['kind']}  {h['path']}:{h['start_line']}  {h['signature']}" for h in hits)
            return {"content": [{"type": "text", "text": text or "no matches"}], "structuredContent": {"results": hits}, "isError": False}
        if name == "repo_stats":
            try:
                stats = self.index_for(args.get("repo")).stats()
            except ValueError as exc:
                return _tool_error(str(exc))
            return {"content": [{"type": "text", "text": json.dumps(stats, indent=2)}], "structuredContent": stats, "isError": False}
        return _tool_error(f"unknown tool {name!r}")

    # ---------------------------------------------------------- protocol
    def handle(self, msg: dict) -> dict | None:
        method = msg.get("method")
        mid = msg.get("id")
        params = msg.get("params") or {}
        if mid is None:
            return None  # notification (e.g. notifications/initialized)
        if method == "initialize":
            client_version = params.get("protocolVersion")
            return _result(mid, {
                "protocolVersion": client_version if isinstance(client_version, str) else PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "ast-pack", "title": "ast-pack", "version": __version__},
                "instructions": (
                    "Use pack_context to get the exact code slice relevant to a function, a file:line, "
                    "or a stack trace instead of reading whole files."
                ),
            })
        if method == "ping":
            return _result(mid, {})
        if method == "tools/list":
            return _result(mid, {"tools": TOOLS})
        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                return _error(mid, -32602, "arguments must be an object")
            try:
                return _result(mid, self.call_tool(str(name), arguments))
            except Exception as exc:  # noqa: BLE001 - report, keep serving
                return _result(mid, _tool_error(f"{type(exc).__name__}: {exc}"))
        return _error(mid, -32601, f"method not found: {method}")


def _result(mid: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _error(mid: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def _tool_error(message: str) -> dict:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def serve_stdio(default_root: str = ".", options: IndexOptions | None = None) -> int:
    server = McpServer(default_root, options)
    stdin = sys.stdin
    stdout = sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            stdout.write(json.dumps(_error(None, -32700, "parse error")) + "\n")
            stdout.flush()
            continue
        batch = msg if isinstance(msg, list) else [msg]
        responses = [r for r in (server.handle(m) for m in batch if isinstance(m, dict)) if r is not None]
        if not responses:
            continue
        out = responses if isinstance(msg, list) else responses[0]
        stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
        stdout.flush()
    return 0
