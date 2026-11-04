"""Local HTTP + WebSocket API (and static host for the web UI).

REST (all JSON):

    GET  /api/health                 version, repo root, index generation
    GET  /api/stats                  RepoIndex.stats()
    GET  /api/search?q=&limit=&kind= fuzzy symbol search
    POST /api/pack                   body: PackOptions fields -> PackResult.to_dict()
    GET  /api/file?path=             full file text (to expand pruned segments)
    GET  /api/graph?limit=           repository overview graph (highest-degree symbols)
    POST /api/refresh                force a re-scan

WebSocket ``/ws`` (JSON messages, ``id`` echoes back):

    -> {"type": "pack",   "id": 7, "params": {...PackOptions}}
    <- {"type": "pack_result", "id": 7, "result": {...}}
    -> {"type": "search", "id": 8, "q": "proc", "limit": 12}
    <- {"type": "search_result", "id": 8, "results": [...]}
    -> {"type": "file", "id": 9, "path": "src/x.py"}
    <- {"type": "file_result", "id": 9, "file": {...}}
    <- {"type": "index_updated", "stats": {...}}      (pushed when files change)
    <- {"type": "error", "id": 7, "message": "..."}

``pack`` and ``search`` are latest-wins per connection: while one request is
computing, newer ones replace older queued ones, so typing in the command
bar never builds a backlog.

The server binds to 127.0.0.1 by default and only ever serves files that are
part of the index.
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import webbrowser
from dataclasses import fields
from importlib import resources
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from . import __version__
from .cli import symbol_json
from .engine import PackOptions, pack
from .index import RepoIndex

_PACK_FIELDS = {f.name for f in fields(PackOptions)}
_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
]


def ui_dist_dir() -> Path | None:
    """Built web UI assets shipped inside the package (``ast_pack/web``)."""
    try:
        base = resources.files("ast_pack") / "web"
        path = Path(str(base))
    except (ModuleNotFoundError, TypeError):
        return None
    return path if (path / "index.html").is_file() else None


def pack_options_from(data: dict[str, Any]) -> PackOptions:
    kwargs = {k: v for k, v in data.items() if k in _PACK_FIELDS}
    targets = kwargs.get("targets")
    if isinstance(targets, str):
        kwargs["targets"] = [targets]
    if "target" in data and "targets" not in kwargs:
        kwargs["targets"] = [data["target"]]
    if "max_tokens" in kwargs and kwargs["max_tokens"] in ("", 0):
        kwargs["max_tokens"] = None
    opts = PackOptions(**kwargs)
    opts.depth = int(opts.depth)
    opts.max_fanout = int(opts.max_fanout)
    opts.type_depth = int(opts.type_depth)
    opts.min_confidence = float(opts.min_confidence)
    if opts.max_tokens is not None:
        opts.max_tokens = int(opts.max_tokens)
    return opts


class AppState:
    def __init__(self, index: RepoIndex, watch_interval: float) -> None:
        self.index = index
        self.lock = threading.RLock()
        self.watch_interval = watch_interval
        self.clients: set[WebSocket] = set()

    # All index access goes through these helpers (run in worker threads).
    def pack(self, opts: PackOptions) -> dict:
        with self.lock:
            result = pack(self.index, opts)
            return result.to_dict()

    def search(self, q: str, limit: int, kinds: set[str] | None) -> list[dict]:
        with self.lock:
            return [symbol_json(s, score) for score, s in self.index.search(q, limit=limit, kinds=kinds)]

    def stats(self) -> dict:
        with self.lock:
            return self.index.stats()

    def refresh(self) -> bool:
        with self.lock:
            return self.index.refresh()

    def file(self, path: str) -> dict | None:
        with self.lock:
            fx = self.index.files.get(path)
            if fx is None:
                return None
            lines = self.index.file_lines(path)
            return {
                "path": path,
                "language": fx.lang,
                "lines": len(lines),
                "tokens": fx.tokens,
                "text": "\n".join(lines),
                "symbols": [symbol_json(self.index.symbols[i]) for i in self.index.by_file.get(path, [])],
            }

    def overview(self, limit: int) -> dict:
        with self.lock:
            idx = self.index
            degree: dict[str, int] = {}
            for sid, edges in idx.edges_out.items():
                degree[sid] = degree.get(sid, 0) + len(edges)
                for e in edges:
                    degree[e.target] = degree.get(e.target, 0) + 1
            top = sorted(degree, key=lambda s: (-degree[s], s))[:limit]
            keep = set(top)
            nodes = [{**symbol_json(idx.symbols[s]), "degree": degree[s]} for s in top]
            edges = [
                {"source": e.source, "target": e.target, "kind": e.kind, "confidence": e.confidence}
                for s in top
                for e in idx.edges_out.get(s, [])
                if e.target in keep
            ]
            return {"nodes": nodes, "edges": edges, "total_symbols": len(idx.symbols), "total_edges": idx.edge_count()}


def _json_error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"ok": False, "error": {"message": message}}, status_code=status)


def create_app(index: RepoIndex, watch_interval: float = 1.0) -> Starlette:
    state = AppState(index, watch_interval)

    async def run(fn, *a):
        return await asyncio.to_thread(fn, *a)

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({
            "ok": True,
            "tool": "ast-pack",
            "version": __version__,
            "root": str(state.index.root),
            "generation": state.index.generation,
            "ui": ui_dist_dir() is not None,
        })

    async def stats(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True, **(await run(state.stats))})

    async def search(request: Request) -> JSONResponse:
        q = request.query_params.get("q", "")
        try:
            limit = min(200, max(1, int(request.query_params.get("limit", "20"))))
        except ValueError:
            return _json_error("limit must be an integer")
        kinds = {k for k in request.query_params.get("kind", "").split(",") if k} or None
        results = await run(state.search, q, limit, kinds)
        return JSONResponse({"ok": True, "query": q, "results": results})

    async def pack_route(request: Request) -> JSONResponse:
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("body must be a JSON object")
            opts = pack_options_from(body)
            opts.validate()
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return _json_error(str(exc))
        data = await run(state.pack, opts)
        return JSONResponse(data, status_code=200 if data["ok"] else 404)

    async def file_route(request: Request) -> JSONResponse:
        path = request.query_params.get("path", "")
        data = await run(state.file, path)
        if data is None:
            return _json_error(f"not an indexed file: {path!r}", 404)
        return JSONResponse({"ok": True, **data})

    async def graph_route(request: Request) -> JSONResponse:
        try:
            limit = min(5000, max(1, int(request.query_params.get("limit", "600"))))
        except ValueError:
            return _json_error("limit must be an integer")
        return JSONResponse({"ok": True, **(await run(state.overview, limit))})

    async def refresh_route(request: Request) -> JSONResponse:
        changed = await run(state.refresh)
        stats_data = await run(state.stats)
        if changed:
            await broadcast({"type": "index_updated", "stats": stats_data})
        return JSONResponse({"ok": True, "changed": changed, "stats": stats_data})

    async def broadcast(message: dict) -> None:
        payload = json.dumps(message)
        for ws in list(state.clients):
            try:
                await ws.send_text(payload)
            except Exception:  # noqa: BLE001 - client went away
                state.clients.discard(ws)

    async def ws_route(ws: WebSocket) -> None:
        await ws.accept()
        state.clients.add(ws)
        latest: dict[str, dict] = {}
        wake = asyncio.Event()

        async def send(msg: dict) -> None:
            await ws.send_text(json.dumps(msg))

        async def handle(msg: dict) -> None:
            mtype = msg.get("type")
            mid = msg.get("id")
            try:
                if mtype == "pack":
                    opts = pack_options_from(msg.get("params") or {})
                    opts.validate()
                    await send({"type": "pack_result", "id": mid, "channel": msg.get("channel", "main"),
                                "result": await run(state.pack, opts)})
                elif mtype == "search":
                    limit = min(200, max(1, int(msg.get("limit", 12))))
                    kinds = set(msg.get("kinds") or []) or None
                    await send({"type": "search_result", "id": mid, "q": msg.get("q", ""),
                                "results": await run(state.search, str(msg.get("q", "")), limit, kinds)})
                elif mtype == "file":
                    data = await run(state.file, str(msg.get("path", "")))
                    if data is None:
                        await send({"type": "error", "id": mid, "message": "not an indexed file"})
                    else:
                        await send({"type": "file_result", "id": mid, "file": data})
                elif mtype == "stats":
                    await send({"type": "stats_result", "id": mid, "stats": await run(state.stats)})
                elif mtype == "graph":
                    limit = min(5000, max(1, int(msg.get("limit", 600))))
                    await send({"type": "graph_result", "id": mid, "graph": await run(state.overview, limit)})
                elif mtype == "ping":
                    await send({"type": "pong", "id": mid})
                else:
                    await send({"type": "error", "id": mid, "message": f"unknown message type {mtype!r}"})
            except (ValueError, TypeError) as exc:
                await send({"type": "error", "id": mid, "message": str(exc)})

        async def worker() -> None:
            while True:
                await wake.wait()
                wake.clear()
                # Search first (typing), then the main pack, then prefetches.
                for key in sorted(latest, key=lambda k: (not k.startswith("search"), k != "pack:main")):
                    msg = latest.pop(key, None)
                    if msg is not None:
                        await handle(msg)
                    if wake.is_set() and key != "search:main":
                        break  # newer input arrived: re-prioritise

        task = asyncio.create_task(worker())
        try:
            await send({"type": "hello", "version": __version__, "root": str(state.index.root),
                        "stats": await run(state.stats)})
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    await send({"type": "error", "message": "invalid JSON"})
                    continue
                if not isinstance(msg, dict):
                    continue
                if msg.get("type") in ("pack", "search"):
                    # Latest-wins per (type, channel): "main" for what the user
                    # is looking at, "prefetch" for speculative neighbours.
                    latest[f"{msg['type']}:{msg.get('channel', 'main')}"] = msg
                    wake.set()
                else:
                    await handle(msg)
        except WebSocketDisconnect:
            pass
        finally:
            task.cancel()
            state.clients.discard(ws)

    async def watcher() -> None:
        if state.watch_interval <= 0:
            return
        while True:
            await asyncio.sleep(state.watch_interval)
            try:
                changed = await run(state.refresh)
            except Exception as exc:  # noqa: BLE001 - keep watching
                print(f"ast-pack: refresh failed: {exc}", file=sys.stderr)
                continue
            if changed:
                await broadcast({"type": "index_updated", "stats": await run(state.stats)})

    async def api_page(request: Request) -> Response:
        return HTMLResponse(_api_page(state.index))

    routes = [
        Route("/api/health", health),
        Route("/api/stats", stats),
        Route("/api/search", search),
        Route("/api/pack", pack_route, methods=["POST"]),
        Route("/api/file", file_route),
        Route("/api/graph", graph_route),
        Route("/api/refresh", refresh_route, methods=["POST"]),
        WebSocketRoute("/ws", ws_route),
        Route("/api", api_page),
    ]
    dist = ui_dist_dir()
    if dist is not None:
        routes.append(Mount("/", app=StaticFiles(directory=dist, html=True), name="ui"))
    else:
        routes.append(Route("/", api_page))

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(watcher())
        try:
            yield
        finally:
            task.cancel()

    app = Starlette(
        routes=routes,
        middleware=[Middleware(CORSMiddleware, allow_origins=_ALLOWED_ORIGINS, allow_methods=["*"], allow_headers=["*"])],
        lifespan=lifespan,
    )
    app.state.ast_pack = state
    return app


def _api_page(index: RepoIndex) -> str:
    """Server-rendered page shown when the web UI bundle is not built."""
    import html

    ld = {
        "@context": "https://schema.org",
        "@type": ["SoftwareApplication", "SoftwareSourceCode"],
        "name": "ast-pack",
        "applicationCategory": "DeveloperApplication",
        "operatingSystem": "Linux, macOS, Windows",
        "softwareVersion": __version__,
        "programmingLanguage": ["Python"],
        "runtimePlatform": "Python 3.10+",
        "codeRepository": "https://github.com/ginckl/ast-pack",
        "license": "https://opensource.org/licenses/MIT",
        "description": "Tree-sitter call-graph context packer: turns a symbol, file:line or stack trace into a minimal, syntactically valid LLM prompt.",
    }
    stats = index.stats()
    rows = "".join(
        f"<tr><td>{html.escape(lang)}</td><td>{s['files']:,}</td><td>{s['symbols']:,}</td><td>{s['tokens']:,}</td></tr>"
        for lang, s in stats["languages"].items()
    )
    endpoints = [
        ("GET", "/api/health", "version, root, index generation"),
        ("GET", "/api/stats", "index statistics"),
        ("GET", "/api/search?q=pay", "fuzzy symbol search"),
        ("POST", "/api/pack", '{"targets": ["processPayment"], "depth": 2}'),
        ("GET", "/api/file?path=…", "full source of an indexed file"),
        ("GET", "/api/graph?limit=600", "repository overview graph"),
        ("POST", "/api/refresh", "force re-scan"),
        ("WS", "/ws", "pack / search / file messages, live index_updated pushes"),
    ]
    ep = "".join(f"<tr><td><code>{m}</code></td><td><code>{html.escape(p)}</code></td><td>{html.escape(d)}</td></tr>" for m, p, d in endpoints)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ast-pack API</title>
<script type="application/ld+json">{json.dumps(ld)}</script>
<style>
:root{{--bg:#0b0d12;--fg:#e6e8ee;--mut:#8a91a5;--line:#232838;--acc:#7c8cff}}
@media (prefers-color-scheme: light){{:root{{--bg:#fbfbfd;--fg:#151821;--mut:#5b6275;--line:#e3e5ec;--acc:#4652e0}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 ui-sans-serif,system-ui,-apple-system,sans-serif}}
main{{max-width:880px;margin:0 auto;padding:48px 16px}}
h1{{font-size:28px;margin:0 0 4px}}p{{color:var(--mut)}}code{{font:13px ui-monospace,SFMono-Regular,Menlo,monospace}}
table{{width:100%;border-collapse:collapse;margin:16px 0 32px}}td,th{{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line)}}
th{{color:var(--mut);font-weight:500}}.k{{color:var(--acc)}}
</style></head><body><main>
<h1>ast-pack <span class="k">{__version__}</span></h1>
<p>API server for <code>{html.escape(str(index.root))}</code> · {stats['files']:,} files · {stats['symbols']:,} symbols · {stats['edges']:,} edges · {stats['tokens']:,} tokens ({html.escape(stats['tokenizer'])}).
The web UI bundle is not installed in this build, so this page lists the API it uses.</p>
<table><tr><th>Language</th><th>Files</th><th>Symbols</th><th>Tokens</th></tr>{rows}</table>
<table><tr><th>Method</th><th>Path</th><th>Purpose</th></tr>{ep}</table>
</main></body></html>"""


def run_server(
    index: RepoIndex,
    *,
    host: str = "127.0.0.1",
    port: int = 7878,
    open_browser: bool = False,
    watch_interval: float = 1.0,
    json_mode: bool = False,
    quiet: bool = False,
) -> int:
    import socket

    import uvicorn

    # Find a free port starting at ``port``.
    chosen = port
    for candidate in range(port, port + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, candidate))
            except OSError:
                continue
            chosen = candidate
            break
    url = f"http://{host}:{chosen}/"
    app = create_app(index, watch_interval)
    st = index.stats()
    if json_mode:
        print(json.dumps({"schema_version": "1.0", "tool": "ast-pack", "version": __version__, "command": "serve",
                          "ok": True, "url": url, "ws": f"ws://{host}:{chosen}/ws", "root": st["root"],
                          "files": st["files"], "symbols": st["symbols"], "ui": ui_dist_dir() is not None}), flush=True)
    elif not quiet:
        print(f"ast-pack {__version__} · {st['files']:,} files · {st['symbols']:,} symbols · {st['edges']:,} edges", file=sys.stderr)
        print(f"  UI/API  {url}", file=sys.stderr)
        print(f"  socket  ws://{host}:{chosen}/ws", file=sys.stderr)
        if ui_dist_dir() is None:
            print("  (web UI bundle not built; serving the API index page)", file=sys.stderr)
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=host, port=chosen, log_level="warning")
    return 0
