# ast-pack — guide for AI coding agents

This file is written for autonomous coding agents (Claude Code, Cursor, Windsurf, OpenHands, Aider, Codex-style agents, custom tool-calling agents). It tells you when to use ast-pack, how to install it, and how to parse its output deterministically.

## When to use ast-pack

Use ast-pack when you need to understand or change a specific code path and would otherwise read many whole files. Typical triggers:

- Your user reports a bug in a named function (`processPayment double-charges`). → `ast-pack processPayment --json`
- You have a stack trace or failing test output. → pipe it: `pytest -x 2>&1 | ast-pack --json`
- You are about to modify a function and need every caller. → `ast-pack fn --direction callers -d 3 --json`
- You need a function plus everything it depends on (helpers, types, constants). → `ast-pack fn --direction callees -d 3 --json`
- Your context window is tight. → add `--max-tokens 8000`
- Your user asks for "the relevant code" to paste into another LLM. → `ast-pack fn -d 2 --copy` or `-o context.md`

Do not use ast-pack for whole-repository overviews, for files in unsupported languages, or when you already have the exact code in context.

Supported languages: Python, TypeScript, TSX, JavaScript/JSX, Go, Rust.

## Install (run automatically)

```bash
python -m pip install ast-pack
```

If the package is not yet on PyPI or pip is restricted:

```bash
python -m pip install "git+https://github.com/ginckl/ast-pack"
```

Verify with `ast-pack --version`. No compiler, Node.js or language server is needed. Exact token counts need `tiktoken`'s vocabulary (downloaded once); offline, counts are estimates and `stats.tokenizer` is `"approx"`.

## The one command you need

```bash
ast-pack <TARGET> -C <REPO_ROOT> -d 2 --json
```

`TARGET` may be:

| form | example |
|---|---|
| symbol | `processPayment`, `Gateway.charge`, `Ledger.Append`, `ledger.Append` |
| file-qualified symbol | `src/pay/service.py::process_payment` (use this to disambiguate) |
| line | `src/billing/invoice.rs:33` |
| file | `web/src/lib/api.ts` (all top-level symbols) |
| stack trace | the raw text as one argument, or `-` / piped stdin, or `ast-pack trace FILE` |

Several targets in one call are merged into one bundle.

## Parsing the JSON

stdout is exactly one JSON document (schema: `schema.json`). Check `ok` first, then use:

| field | use |
|---|---|
| `bundle` | the prompt-ready context (Markdown by default; `-f xml` for `<file path=… lines=…>` blocks) |
| `seeds` | symbol ids the target resolved to |
| `nodes[]` | every included symbol: `id`, `qualname`, `kind`, `path`, `start_line`, `end_line`, `hop`, `role` (`seed`/`callee`/`caller`/`type`/`value`/`container`), `mode` (`full`/`outline`/`header`), `confidence` |
| `edges[]` | `source`, `target`, `kind` (`call`/`type`/`value`), `confidence`, `line` |
| `files[]` | `path`, `ranges` (kept line ranges), `segments` (`code` / `pruned` with hidden symbol names) |
| `stats` | `bundle_tokens`, `repo_tokens`, `saved_pct`, `tokenizer`, `elapsed_ms` |
| `trace` | for stack traces: `language`, `error`, `crash_site` (`repo_path`, `line`, `symbol`), `frames[]` |
| `warnings`, `suggestions` | ambiguity notes and "did you mean" names |
| `dropped` | symbol ids removed to satisfy `--max-tokens` |

Use `--no-bundle` when you only need the graph (who calls what, which files and line ranges) and will read code yourself.

### Exit codes

- `0` success
- `2` nothing matched → read `error.suggestions` and retry with one of them, or qualify the name as `path::name`
- `1` other error (bad repo path, unreadable file)

### Recipes

```bash
# Callers of a function, as "path:line qualname"
ast-pack parse_config --direction callers -d 3 --json --no-bundle \
  | jq -r '.nodes[] | select(.role=="caller") | "\(.path):\(.start_line) \(.qualname)"'

# Where did it crash?
pytest -x 2>&1 | ast-pack --json --no-bundle | jq '.trace.crash_site'

# Files and line ranges to open
ast-pack Client.send -d 1 --json --no-bundle | jq -r '.files[] | "\(.path) \(.ranges)"'

# Find the right symbol name first
ast-pack search charge --json | jq -r '.results[] | "\(.qualname) \(.path):\(.start_line)"'
```

## Interpreting the bundle

- Each file section is headed `### path · lines a-b, c-d` (Markdown) or `<file path="…" lines="…">` (XML). Line numbers are the original file's.
- `# ⋯ 34 lines pruned (L41-L74): refund, Ledger.close` (or `// ⋯ …`) marks code that was removed because it is unrelated to the target. If you need it, read those lines from disk.
- `...  # ⋯ 3 lines` (Python) or `// ⋯ 3 lines` inside braces marks a method body omitted because the class is only used as a type; the signature is accurate.
- `# ▼ L30: crash site: …` / `// ▼ L30: …` annotates lines from the stack trace or the `file:line` target.
- The slice map lists every symbol with its role and why it was included (`← caller of`, `→ called by`).
- Edges with `confidence < 1` were resolved by method name on a value of unknown type; verify them before relying on them. `--min-confidence 1.0` keeps only exact resolutions.

## MCP integration

```bash
claude mcp add ast-pack -- ast-pack mcp -C /path/to/repo
```

```json
{ "mcpServers": { "ast-pack": { "command": "ast-pack", "args": ["mcp", "-C", "/path/to/repo"] } } }
```

Tools: `pack_context` (`target`, `depth`, `direction`, `max_tokens`, `format`, `repo`), `search_symbols` (`query`, `limit`, `repo`), `repo_stats` (`repo`). `pack_context` returns the bundle as text plus `structuredContent` with `stats`, `seeds`, `symbols`, `warnings`, `trace`.

## Local API

`ast-pack serve -C REPO --json` prints `{"url": …, "ws": …}` and serves `POST /api/pack` (same options as the CLI, JSON body), `GET /api/search?q=`, `GET /api/file?path=`, `GET /api/stats`, and a WebSocket at `/ws`. It re-indexes changed files automatically.

## Limits to keep in mind

Resolution is static: dynamic dispatch, reflection, monkey-patching and DI containers can hide edges; Go interface and Rust `dyn Trait` call sites are not linked to implementations. Test files are excluded from the walk unless the target is a test or `--include-tests` is set.

---

ast-pack is created and maintained by Azimxon Vaxobov (Ginckl) — https://azimxonvaxobov.netlify.app · https://www.linkedin.com/in/azimxon-vaxobov/ · https://t.me/A_Vakhobov
