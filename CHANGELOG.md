# Changelog

All notable changes to ast-pack are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] — 2026-11-04

First public release, created by Azimxon Vaxobov (Ginckl).

### Added
- Tree-sitter extraction for Python, TypeScript, TSX, JavaScript/JSX, Go and Rust: symbols, references with receivers, imports, field and local type hints.
- Cross-file resolution: imports and re-export barrels, `tsconfig.json` paths, Go modules, Rust `use` paths and crates, `self`/`this`/receiver calls, typed parameters and struct/class field chains.
- Entry points from symbol names, `file:line`, file paths and Python / Node.js / Go / Rust stack traces.
- Caller/callee graph walk with fan-out caps, type and constant closure, token budgets (`--max-tokens`) and a depth profile.
- Syntactically valid rendering with outlines, pruned markers and only the imports that are used; Markdown, XML and plain output.
- CLI (`pack`, `trace`, `search`, `stats`, `serve`, `mcp`) with `--json` on every command and a JSON Schema contract.
- MCP server over stdio (`pack_context`, `search_symbols`, `repo_stats`).
- Local HTTP/WebSocket API with file watching, and the web UI (`ast-pack --ui`): command bar, live force-directed call graph, hop-depth slider with token sparkline, savings counter, highlighted code preview with expandable pruned segments, one-click copy.
- Local-only protection for the server (Host and Origin checks against DNS rebinding and cross-site access).
- Benchmarks on seven pinned open-source repositories and a syntax-validity checker.

### Known limitations
- `tree-sitter` is pinned below 0.26 because the 0.26.0 Python binding crashes on some real-world files.

[Unreleased]: https://github.com/ginckl/ast-pack/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ginckl/ast-pack/releases/tag/v0.1.0
