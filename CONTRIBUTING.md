# Contributing to ast-pack

Thanks for helping. ast-pack is created and maintained by
[Azimxon Vaxobov (Ginckl)](https://azimxonvaxobov.netlify.app); issues and pull
requests are welcome.

## Set up

```bash
git clone https://github.com/ginckl/ast-pack
cd ast-pack
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

Web UI (only needed if you change `ui/`):

```bash
cd ui
npm ci
npm run dev        # http://localhost:5173, proxies to `ast-pack serve` on :7878
npm run build      # writes ../src/ast_pack/web (commit the result)
node e2e/smoke.mjs # end-to-end test in Chromium against a real server
```

## Project layout

| path | what lives there |
|---|---|
| `src/ast_pack/extractors/` | one Tree-sitter extractor per language |
| `src/ast_pack/index.py` | symbol table, cross-file resolution, graph edges |
| `src/ast_pack/slicer.py` | caller/callee walk, type closure |
| `src/ast_pack/render.py` | line plans, outlines, pruned markers |
| `src/ast_pack/engine.py` | `pack()` — the API everything else calls |
| `src/ast_pack/cli.py`, `server.py`, `mcp.py` | CLI, HTTP/WebSocket server, MCP server |
| `ui/` | React web UI |
| `tests/fixtures/polyglot/` | small Python/TS/Go/Rust repo used by the tests |
| `benchmarks/` | token-savings benchmark and syntax-validity checker |

## Rules of thumb

- **Rendered output must stay syntactically valid.** `tests/test_pack.py` re-parses every file of every slice of the fixture; run `python benchmarks/validity.py <some-real-repo>` for larger changes.
- **Bump `EXTRACTOR_VERSION`** (`src/ast_pack/extractors/__init__.py`) whenever extraction output changes, so stale parse caches are discarded.
- **`--json` is a contract.** Extend `schema.json` in the same change; `tests/test_interfaces.py` validates real output against it.
- **Measure, don't guess.** Changes that affect slice size should include before/after numbers from `python benchmarks/bench.py`.
- Adding a language: write an extractor (see `extractors/go.py` for a compact example), register it in `languages.py` and `extractors/__init__.py`, add fixture files and tests.

## Pull requests

Keep PRs focused, include tests, and describe how you verified the change. CI runs the Python suite on Linux and macOS (Python 3.10–3.13) and the UI build plus the browser end-to-end test.
