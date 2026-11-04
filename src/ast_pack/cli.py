"""Command-line interface.

    ast-pack processPayment                 # pack a symbol (pack is the default command)
    ast-pack src/pay/service.py:42 -d 3     # pack the symbol enclosing a line
    pytest 2>&1 | ast-pack                  # pack a stack trace from stdin
    ast-pack search pay --json              # fuzzy symbol search
    ast-pack stats --json                   # repository index statistics
    ast-pack --ui                           # local web UI + API (same as `ast-pack serve --open`)
    ast-pack mcp                            # Model Context Protocol server over stdio

Every command accepts ``--json`` and then prints exactly one JSON document on
stdout (schema: ``schema.json``). Exit codes: 0 success, 1 error, 2 nothing
matched / bad usage.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__

COMMANDS = ("pack", "search", "stats", "serve", "mcp", "trace")
EXIT_OK, EXIT_ERROR, EXIT_NO_MATCH = 0, 1, 2


# ------------------------------------------------------------------ helpers
def _stderr_color(code: str, text: str) -> str:
    if not sys.stderr.isatty() or os.environ.get("NO_COLOR"):
        return text
    return f"\033[{code}m{text}\033[0m"


def _emit_json(data: dict) -> None:
    sys.stdout.write(json.dumps(data, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _error(args: argparse.Namespace, message: str, code: int = EXIT_ERROR, **extra) -> int:
    if getattr(args, "json", False):
        _emit_json({"schema_version": "1.0", "tool": "ast-pack", "version": __version__,
                    "command": getattr(args, "command", None), "ok": False,
                    "error": {"message": message, "exit_code": code, **extra}})
    else:
        print(_stderr_color("31", f"ast-pack: {message}"), file=sys.stderr)
        for s in extra.get("suggestions", []) or []:
            print(f"  did you mean: {s}", file=sys.stderr)
    return code


def copy_to_clipboard(text: str) -> bool:
    candidates = [
        ["pbcopy"],
        ["wl-copy"],
        ["xclip", "-selection", "clipboard"],
        ["xsel", "--clipboard", "--input"],
        ["clip.exe"],
        ["clip"],
    ]
    for cmd in candidates:
        if shutil.which(cmd[0]) is None:
            continue
        try:
            subprocess.run(cmd, input=text.encode("utf-8"), check=True, timeout=5)
            return True
        except (OSError, subprocess.SubprocessError):
            continue
    return False


def _index_options(args: argparse.Namespace):
    from .index import IndexOptions
    from .languages import SUPPORTED_LANGUAGES

    langs = None
    if args.lang:
        langs = set()
        for item in args.lang:
            for name in item.split(","):
                name = name.strip().lower()
                if not name:
                    continue
                if name in ("ts",):
                    langs.update({"typescript", "tsx"})
                elif name in ("js",):
                    langs.add("javascript")
                elif name in ("py",):
                    langs.add("python")
                elif name in ("rs",):
                    langs.add("rust")
                elif name in SUPPORTED_LANGUAGES:
                    langs.add(name)
                    if name == "typescript":
                        langs.add("tsx")
                else:
                    raise ValueError(f"unknown language {name!r} (supported: python, typescript, javascript, rust, go)")
    return IndexOptions(
        include=list(args.include or []),
        exclude=list(args.exclude or []),
        languages=langs,
        tokenizer=args.tokenizer,
        use_cache=not args.no_cache,
    )


def _build_index(args: argparse.Namespace):
    from .index import RepoIndex

    root = Path(args.repo).expanduser()
    if not root.is_dir():
        raise FileNotFoundError(f"repository directory not found: {root}")
    return RepoIndex.build(root, _index_options(args))


# ------------------------------------------------------------------ parser
def _global_options(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("repository")
    g.add_argument("-C", "--repo", default=".", metavar="DIR", help="repository root (default: current directory)")
    g.add_argument("--include", action="append", metavar="GLOB", help="only index paths matching this gitignore-style glob (repeatable)")
    g.add_argument("--exclude", action="append", metavar="GLOB", help="skip paths matching this glob (repeatable)")
    g.add_argument("--lang", action="append", metavar="LANGS", help="restrict to languages: python,typescript,javascript,rust,go")
    g.add_argument("--tokenizer", default=None, metavar="NAME",
                   help="cl100k_base (default), o200k_base or approx; falls back to approx if tiktoken is unavailable")
    g.add_argument("--no-cache", action="store_true", help="do not read or write the on-disk parse cache")
    p.add_argument("--json", action="store_true", help="print one machine-readable JSON document on stdout")
    p.add_argument("-q", "--quiet", action="store_true", help="no summary on stderr")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ast-pack",
        description=(
            "Surgical LLM context from a code graph. Give a symbol, file:line or stack trace; "
            "ast-pack walks callers/callees, pulls the types and constants they need, prunes "
            "everything else and prints a dense, syntactically valid bundle."
        ),
        epilog=(
            "Run `ast-pack <command> --help` for command options. `ast-pack --ui` opens the web UI. "
            "Created by Azimxon Vaxobov (Ginckl) · https://azimxonvaxobov.netlify.app"
        ),
    )
    parser.add_argument("--version", action="version", version=f"ast-pack {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    p = sub.add_parser("pack", help="build a context bundle (default command)",
                       description="Build a context bundle from symbols, file:line targets or a stack trace.")
    p.add_argument("targets", nargs="*", metavar="TARGET",
                   help="symbol (processPayment, Class.method, path.py::name), file:line, file path, a stack trace, or '-' for stdin")
    _pack_options(p)
    _global_options(p)

    t = sub.add_parser("trace", help="pack a stack trace read from a file or stdin",
                       description="Read a Python / Node.js / Go / Rust stack trace and pack every in-repo frame.")
    t.add_argument("file", nargs="?", default="-", help="file containing the trace (default: stdin)")
    _pack_options(t)
    _global_options(t)

    s = sub.add_parser("search", help="fuzzy-search symbols in the repository")
    s.add_argument("query", help="name, Class.method, or subsequence (e.g. 'prcPay')")
    s.add_argument("-n", "--limit", type=int, default=20)
    s.add_argument("--kind", action="append", help="filter by kind: function, method, class, struct, interface, ...")
    _global_options(s)

    st = sub.add_parser("stats", help="index statistics: files, symbols, edges, tokens per language")
    _global_options(st)

    sv = sub.add_parser("serve", help="start the local HTTP/WebSocket API and web UI")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=7878)
    sv.add_argument("--open", dest="open_browser", action="store_true", help="open the UI in a browser")
    sv.add_argument("--watch-interval", type=float, default=1.0, metavar="SECONDS",
                    help="poll for file changes every N seconds (0 disables)")
    _global_options(sv)

    m = sub.add_parser("mcp", help="run a Model Context Protocol server on stdio (for AI agents)")
    _global_options(m)
    return parser


def _pack_options(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("slice")
    g.add_argument("-d", "--depth", type=int, default=2, help="call-graph hops to walk (default: 2)")
    g.add_argument("--direction", choices=("both", "callers", "callees"), default="both")
    g.add_argument("-b", "--max-tokens", type=int, default=None, metavar="N",
                   help="token budget; drops the farthest / least certain symbols first")
    g.add_argument("--max-fanout", type=int, default=30, metavar="N", help="max callers/callees followed per symbol (default: 30)")
    g.add_argument("--type-depth", type=int, default=2, metavar="N", help="levels of type/constant definitions to include (default: 2)")
    g.add_argument("--no-types", action="store_true", help="do not pull in type definitions and constants")
    g.add_argument("--include-tests", action="store_true",
                   help="also follow callers/callees/types in test files (skipped by default unless the target is a test)")
    g.add_argument("--min-confidence", type=float, default=0.5, metavar="X",
                   help="ignore call edges resolved with lower confidence (1.0 = only exact resolution)")
    o = p.add_argument_group("output")
    o.add_argument("-f", "--format", choices=("markdown", "xml", "plain"), default="markdown")
    o.add_argument("--strip-comments", action="store_true", help="drop comment-only lines from kept code")
    o.add_argument("--line-numbers", action="store_true", help="prefix kept lines with their original line numbers")
    o.add_argument("--no-imports", action="store_true", help="omit import statements")
    o.add_argument("--no-map", action="store_true", help="omit the slice map table")
    o.add_argument("-p", "--prompt", metavar="TEXT", help="task text placed before the context")
    o.add_argument("-o", "--output", metavar="FILE", help="write the bundle to FILE instead of stdout")
    o.add_argument("--copy", action="store_true", help="also copy the bundle to the clipboard")
    o.add_argument("--depth-profile", action="store_true", help="also compute bundle size for every depth (JSON)")
    o.add_argument("--no-bundle", action="store_true", help="with --json: omit the bundle text and per-file code")


def normalize_argv(argv: list[str]) -> list[str]:
    """Make ``pack`` the default command and map ``--ui`` to ``serve --open``."""
    if not argv:
        return ["pack"]
    if "--ui" in argv:
        rest = [a for a in argv if a != "--ui"]
        if rest and rest[0] == "serve":
            rest = rest[1:]
        return ["serve", "--open", *rest]
    first = argv[0]
    if first in COMMANDS or first in ("-h", "--help", "--version"):
        return argv
    # ``ast-pack -C repo stats``: global options may precede the command.
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok in _VALUE_OPTIONS:
            i += 2
            continue
        if tok.startswith("-"):
            i += 1
            continue
        if tok in COMMANDS:
            return [tok, *argv[:i], *argv[i + 1 :]]
        break
    return ["pack", *argv]


_VALUE_OPTIONS = frozenset({"-C", "--repo", "--include", "--exclude", "--lang", "--tokenizer"})


# ------------------------------------------------------------------ commands
def _pack_from_args(args: argparse.Namespace, targets: list[str]) -> int:
    from .engine import PackOptions, pack

    try:
        index = _build_index(args)
    except (FileNotFoundError, ValueError) as exc:
        return _error(args, str(exc))
    opts = PackOptions(
        targets=targets,
        depth=args.depth,
        direction=args.direction,
        max_tokens=args.max_tokens,
        max_fanout=args.max_fanout,
        type_depth=args.type_depth,
        include_types=not args.no_types,
        min_confidence=args.min_confidence,
        include_tests=args.include_tests,
        format=args.format,
        strip_comments=args.strip_comments,
        line_numbers=args.line_numbers,
        include_imports=not args.no_imports,
        slice_map=not args.no_map,
        prompt=args.prompt,
        depth_profile=args.depth_profile,
    )
    try:
        result = pack(index, opts)
    except ValueError as exc:
        return _error(args, str(exc), EXIT_NO_MATCH)
    if not result.ok:
        return _error(
            args,
            "; ".join(result.resolution.warnings) or "nothing matched",
            EXIT_NO_MATCH,
            suggestions=result.resolution.suggestions,
        )
    copied = None
    if args.copy:
        copied = copy_to_clipboard(result.bundle)
    if args.output:
        Path(args.output).write_text(result.bundle, encoding="utf-8")
    if args.json:
        data = result.to_dict(include_bundle=not args.no_bundle)
        if args.no_bundle:
            for f in data["files"]:
                f.pop("text", None)
                f.pop("segments", None)
        data["output_file"] = args.output
        data["copied_to_clipboard"] = copied
        _emit_json(data)
    elif not args.output:
        sys.stdout.write(result.bundle)
        sys.stdout.flush()
    if not args.quiet and not args.json:
        for w in result.resolution.warnings:
            print(_stderr_color("33", f"warning: {w}"), file=sys.stderr)
        msg = (
            f"✓ {result.summary_line()} · {result.elapsed_ms:.0f} ms"
            + ("" if result.tokenizer_exact else " · token counts approximate (install tiktoken for exact)")
        )
        print(_stderr_color("32", msg), file=sys.stderr)
        if result.dropped:
            print(_stderr_color("33", f"budget: dropped {len(result.dropped)} symbols to fit --max-tokens"), file=sys.stderr)
        if args.output:
            print(f"  wrote {args.output}", file=sys.stderr)
        if copied is not None:
            print("  copied to clipboard" if copied else _stderr_color("33", "  clipboard tool not found (pbcopy/wl-copy/xclip/xsel/clip)"), file=sys.stderr)
    return EXIT_OK


def cmd_pack(args: argparse.Namespace) -> int:
    targets = list(args.targets)
    if targets == ["-"] or (not targets and not sys.stdin.isatty()):
        data = sys.stdin.read()
        if not data.strip():
            return _error(args, "no target given and stdin is empty", EXIT_NO_MATCH)
        targets = [data]
    elif "-" in targets:
        targets = [t if t != "-" else sys.stdin.read() for t in targets]
    if not targets:
        return _error(args, "no target given (symbol, file:line, file, or a stack trace on stdin)", EXIT_NO_MATCH)
    return _pack_from_args(args, targets)


def cmd_trace(args: argparse.Namespace) -> int:
    if args.file == "-":
        text = sys.stdin.read()
    else:
        try:
            text = Path(args.file).read_text("utf-8", "replace")
        except OSError as exc:
            return _error(args, f"cannot read {args.file}: {exc}")
    if not text.strip():
        return _error(args, "empty stack trace", EXIT_NO_MATCH)
    from .entry import looks_like_trace

    if not looks_like_trace(text):
        return _error(args, "input does not look like a Python, Node.js, Go or Rust stack trace", EXIT_NO_MATCH)
    return _pack_from_args(args, [text])


def cmd_search(args: argparse.Namespace) -> int:
    try:
        index = _build_index(args)
    except (FileNotFoundError, ValueError) as exc:
        return _error(args, str(exc))
    kinds = {k for item in (args.kind or []) for k in item.split(",") if k} or None
    hits = index.search(args.query, limit=args.limit, kinds=kinds)
    items = [symbol_json(sym, score) for score, sym in hits]
    if args.json:
        _emit_json({"schema_version": "1.0", "tool": "ast-pack", "version": __version__, "command": "search",
                    "ok": bool(items), "query": args.query, "results": items})
    else:
        if not items:
            print(f"no symbols match {args.query!r}", file=sys.stderr)
        width = max((len(i["qualname"]) for i in items), default=0)
        for i in items:
            print(f"{i['qualname']:<{width}}  {i['kind']:<9}  {i['path']}:{i['start_line']}  {i['signature'][:80]}")
    return EXIT_OK if items else EXIT_NO_MATCH


def symbol_json(sym, score: float | None = None) -> dict:
    data = {
        "id": sym.id,
        "name": sym.name,
        "qualname": sym.qualname,
        "kind": sym.kind,
        "language": sym.lang,
        "path": sym.path,
        "start_line": sym.start_line,
        "end_line": sym.end_line,
        "signature": sym.signature,
        "tokens": sym.tokens,
    }
    if score is not None:
        data["score"] = round(score, 2)
    return data


def cmd_stats(args: argparse.Namespace) -> int:
    try:
        index = _build_index(args)
    except (FileNotFoundError, ValueError) as exc:
        return _error(args, str(exc))
    stats = index.stats()
    if args.json:
        _emit_json({"schema_version": "1.0", "tool": "ast-pack", "version": __version__, "command": "stats", "ok": True, **stats})
        return EXIT_OK
    print(f"{stats['root']}")
    print(f"  files {stats['files']:,} · symbols {stats['symbols']:,} · edges {stats['edges']:,} · "
          f"lines {stats['lines']:,} · tokens {stats['tokens']:,} ({stats['tokenizer']})")
    for lang, s in stats["languages"].items():
        print(f"  {lang:<11} {s['files']:>6,} files {s['symbols']:>8,} symbols {s['tokens']:>10,} tokens")
    t = stats["timing"]
    print(f"  indexed in {t['scan_parse_seconds'] + t['resolve_seconds']:.2f}s "
          f"({t['parsed_files']} parsed, {t['cached_files']} from cache)")
    return EXIT_OK


def cmd_serve(args: argparse.Namespace) -> int:
    try:
        from .server import run_server
    except ImportError as exc:  # pragma: no cover - optional deps missing
        return _error(args, f"server dependencies missing ({exc}); pip install 'ast-pack[server]'")
    try:
        index = _build_index(args)
    except (FileNotFoundError, ValueError) as exc:
        return _error(args, str(exc))
    return run_server(index, host=args.host, port=args.port, open_browser=args.open_browser,
                      watch_interval=args.watch_interval, json_mode=args.json, quiet=args.quiet)


def cmd_mcp(args: argparse.Namespace) -> int:
    from .mcp import serve_stdio

    try:
        options = _index_options(args)
    except ValueError as exc:
        return _error(args, str(exc))
    return serve_stdio(default_root=args.repo, options=options)


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    if not raw and sys.stdin.isatty():
        parser.print_help()
        return EXIT_OK
    argv = normalize_argv(raw)
    args = parser.parse_args(argv)
    handlers = {
        "pack": cmd_pack,
        "trace": cmd_trace,
        "search": cmd_search,
        "stats": cmd_stats,
        "serve": cmd_serve,
        "mcp": cmd_mcp,
    }
    try:
        return handlers[args.command](args)
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        try:
            sys.stdout = open(os.devnull, "w")  # noqa: SIM115
        except OSError:
            pass
        return EXIT_OK
