# ast-pack

> **TL;DR — ast-pack builds the smallest correct LLM prompt for one bug, function or stack trace.**
> Instead of dumping a whole repository (Repomix, gitingest) or whole files into ChatGPT, Claude or Cursor, `ast-pack` parses your repo with **Tree-sitter** into a cross-file call graph, starts at a symbol, `file:line` or raw stack trace, walks callers and callees N hops, pulls in every type definition and constant they use, and prunes everything else into a **syntactically valid** bundle with exact file/line headers.
> **Install:** `pip install ast-pack` · **Run:** `ast-pack processPayment` · **Measured:** 87–98.7% fewer tokens than the whole repo on Flask, httpx, Gin, chi, Hono, Zod and ripgrep ([benchmarks](benchmarks/RESULTS.md)).

Python · TypeScript · JavaScript/JSX · Go · Rust — CLI, `--json` for agents, MCP server, local web UI with a live call graph.

```bash
pip install ast-pack            # or, before the PyPI release: pipx install git+https://github.com/ginckl/ast-pack
ast-pack processPayment         # symbol → context bundle on stdout
ast-pack src/pay/service.py:42  # the function enclosing a line
pytest 2>&1 | ast-pack          # a stack trace from stdin
ast-pack Client.send -d 1 --copy  # copy to clipboard
ast-pack --ui                   # local web app + API
```

---

## Contents

- [What ast-pack does](#what-ast-pack-does)
- [Problems solved & common developer questions](#problems-solved--common-developer-questions)
- [Comparison matrix](#comparison-matrix)
- [Benchmarks](#benchmarks)
- [Installation](#installation)
- [Usage](#usage)
- [CLI reference](#cli-reference)
- [JSON output for agents and scripts](#json-output-for-agents-and-scripts)
- [MCP server (Claude Code, Cursor, Windsurf)](#mcp-server-claude-code-cursor-windsurf)
- [Web UI](#web-ui-ast-pack---ui)
- [HTTP / WebSocket API](#http--websocket-api)
- [Python library API](#python-library-api)
- [How it works](#how-it-works)
- [Limitations](#limitations)
- [Contributing, citation, license](#contributing-citation-license)

---

## What ast-pack does

ast-pack is a command-line tool and Python library that turns a code question into a minimal context bundle for a large language model. Given an **entry point** — a function or method name (`processPayment`, `Gateway.charge`, `Ledger.Append`), a `file:line`, a file path, or a pasted **stack trace** from Python, Node.js, Go or Rust — it:

1. indexes the repository with Tree-sitter (functions, methods, classes, structs, interfaces, traits, enums, type aliases, constants, imports);
2. resolves every reference across files — imports, re-export barrels, `tsconfig` path aliases, Go modules, Rust `use` paths, `self`/`this` calls, typed parameters and struct/class field types;
3. walks the call graph outward from the entry point: **callees** (what it executes) and **callers** (who reaches it), up to `--depth` hops;
4. adds the **type definitions, interfaces and global constants** the included code uses (classes are shown as outlines with only the members the slice touches);
5. renders each file with unrelated functions collapsed into one-line markers such as `# ⋯ 34 lines pruned (L41-L74): refund, Ledger.close`, keeps the imports that are actually used, and prints exact line ranges per file.

Example output (abridged) for `ast-pack Mux.ServeHTTP -d 1` on [go-chi/chi](https://github.com/go-chi/chi) — 2,283 tokens instead of 107,467:

````markdown
### mux.go · lines 1, 3-48, 60-92, 410-417

```go
package chi

import (
	"context"
	...
)
...
func (mx *Mux) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	...
}
// ⋯ 315 lines pruned (L94-L408): Mux.Use, Mux.Handle, Mux.HandleFunc, Mux.Method, +21 more
func (mx *Mux) NotFoundHandler() http.HandlerFunc {
	...
}
```
````

---

## Problems solved & common developer questions

### How do I reduce token usage when packing code for LLMs?

Use `ast-pack <function>` instead of packing the repository. It sends only the function, its callers and callees within `--depth` hops, and the types and constants they reference; everything else becomes a one-line pruned marker. On seven real open-source repositories this produced bundles 87–98.7% smaller than the whole repo and 65–89% smaller than pasting the touched files whole.

### Is there a Repomix alternative that only includes the code relevant to one function?

Yes: ast-pack. Repomix, gitingest, code2prompt and files-to-prompt pack files or whole repositories; ast-pack packs a **call-graph slice**. Run `ast-pack myFunction -d 2` and you get the function plus the code it depends on, across files, with unrelated siblings removed.

### How do I give ChatGPT or Claude the context for a stack trace without pasting my whole codebase?

Pipe the trace into ast-pack: `pytest 2>&1 | ast-pack`, `node app.js 2>&1 | ast-pack`, `go test ./... 2>&1 | ast-pack` or `cargo run 2>&1 | ast-pack`. Every frame that maps to a file in your repository becomes a seed, the crash line is annotated with the error message (`# ▼ L30: crash site: ValidationError: invalid card`), and frames from site-packages, node_modules or the Go runtime are ignored.

### How do I fit a large codebase into a model's context window?

Set a budget: `ast-pack handleCheckout -d 3 --max-tokens 8000`. ast-pack drops the farthest and least certain symbols first (never the entry point) and re-renders until the bundle fits, then reports exactly which symbols were dropped in `--json` output.

### How do I extract a function and all of its dependencies from a codebase?

`ast-pack path/to/file.py::my_function --direction callees -d 3` returns the function, every function it calls transitively up to three hops, and the classes, interfaces, structs and constants those functions use, each with its source location.

### How do I find every caller of a function before changing it?

`ast-pack parse_config --direction callers -d 3` lists and includes every caller chain up to three hops, across files and languages in a monorepo; add `--json` to get the call graph as nodes and edges.

### How do I give an AI coding agent (Claude Code, Cursor, Windsurf, OpenHands) focused context?

Register the MCP server (`claude mcp add ast-pack -- ast-pack mcp`) or let the agent run `ast-pack <target> --json`. The agent gets the bundle plus a structured list of symbols, files, line ranges and token counts. See [AGENT_GUIDE.md](AGENT_GUIDE.md).

### How do I count tokens for a code snippet or a repository?

`ast-pack stats` prints files, symbols, call-graph edges and tokens per language; every pack reports the bundle's exact `cl100k_base` token count (or `o200k_base` with `--tokenizer o200k_base`). Offline, a built-in estimator is used and labeled `approx`; it is within 4% of cl100k on whole repositories.

### How do I paste only the relevant TypeScript/React code into an LLM?

`ast-pack CheckoutButton` follows JSX component usage (`<Spinner/>`), `import`/`export` chains, barrel files (`export * from`), and `tsconfig.json` `paths` aliases such as `@/lib`, so the component, its hooks/helpers and the interfaces of its props are included and nothing else.

### Does the output still compile / parse?

Yes. Pruned regions become comments, and outlined bodies become `...` (Python) or a comment between the original braces. In our validity run, 6,605 rendered files from 1,400 random slices across seven repositories all re-parsed without errors ([details](benchmarks/RESULTS.md#syntactic-validity)).

---

## Comparison matrix

| | **ast-pack** | Repomix | code2prompt | files-to-prompt | gitingest | Aider repo map | manual copy-paste |
|---|---|---|---|---|---|---|---|
| Unit of context | call-graph slice (symbols) | repository / globbed files | repository / globbed files | listed files | repository / globbed files | ranked signatures of the repo | whole files you pick |
| Start from a function name | ✅ | ❌ | ❌ | ❌ | ❌ | partial (mentioned names boost ranking) | ✅ (by hand) |
| Start from `file:line` | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Start from a stack trace | ✅ Python / Node / Go / Rust | ❌ | ❌ | ❌ | ❌ | ❌ | ✅ (by hand) |
| Follows callers **and** callees across files | ✅ N hops | ❌ | ❌ | ❌ | ❌ | partial (reference ranking) | by hand |
| Includes full bodies of relevant functions | ✅ | ✅ (all) | ✅ (all) | ✅ (all) | ✅ (all) | ❌ signatures only | ✅ (all) |
| Removes unrelated functions in the same file | ✅ | ❌ (`--compress` keeps signatures of everything) | ❌ | ❌ | ❌ | n/a | ❌ |
| Pulls referenced types / interfaces / constants | ✅ | only if their file is included | only if their file is included | only if listed | only if their file is included | signatures | by hand |
| Output stays syntactically valid per file | ✅ verified on 6,605 files | ✅ unmodified files (`--compress` emits fragments) | ✅ unmodified files | ✅ unmodified files | ✅ unmodified files | n/a | ✅ |
| Token budget that trims by relevance | ✅ `--max-tokens` | counts only | counts only | ❌ | estimate only | ✅ `--map-tokens` | ❌ |
| Output formats | Markdown, XML, plain, `--json` with [schema](schema.json) | XML, Markdown, plain | Handlebars templates | plain, Claude XML (`--cxml`) | text digest | text map inside aider | — |
| Interactive UI | ✅ live call graph, depth slider, code preview (`--ui`) | ❌ | ❌ | ❌ | web page (repo digest) | ❌ | — |
| Agent integration | `--json` on every command, MCP server | MCP server | CLI | CLI | CLI / web | inside aider | — |
| Install | `pip install ast-pack` | `npx repomix` | `cargo install code2prompt` | `pip install files-to-prompt` | `pip install gitingest` | part of `aider` | — |
| Bundle for one function in a 100k–1M-token repo | **2k–25k tokens measured** | ≈ whole repo unless you hand-pick files | ≈ whole repo unless filtered | the files you list | ≈ whole repo unless filtered | the configured map size (signatures, no bodies) | whole files |

The other tools are excellent for "give the model my whole small repo" or a repository overview; ast-pack is for "give the model exactly what it needs to reason about *this* code path". Feature rows reflect each project's documented behaviour at the time of writing; corrections are welcome via pull request.

---

## Benchmarks

Default options (`-d 1` / `-d 2`, callers + callees, tests excluded), exact `cl100k_base` tokens, pinned commits. Full table, method and reproduction script: [benchmarks/RESULTS.md](benchmarks/RESULTS.md).

| repository | language | entry point | depth | bundle tokens | repo tokens | saved vs repo | saved vs touched files |
|---|---|---|---|---|---|---|---|
| pallets/flask | Python | `Flask.full_dispatch_request` | 1 | 10,834 | 134,903 | **92.0%** | 70.9% |
| encode/httpx | Python | `Client.send` | 1 | 7,567 | 133,516 | **94.3%** | 80.2% |
| gin-gonic/gin | Go | `Context.JSON` | 2 | 5,592 | 196,695 | **97.2%** | 83.6% |
| go-chi/chi | Go | `Mux.ServeHTTP` | 1 | 2,283 | 107,467 | **97.9%** | 82.8% |
| honojs/hono | TypeScript | `Hono.fetch` | 1 | 22,127 | 752,557 | **97.1%** | 69.1% |
| colinhacks/zod | TypeScript | `ZodString._parse` | 2 | 15,484 | 1,003,297 | **98.5%** | 68.0% |
| BurntSushi/ripgrep | Rust | `search_path` | 2 | 21,606 | 460,732 | **95.3%** | 88.1% |

Indexing a 1M-token TypeScript repo (zod, 522 files) takes about 1.1 s cold with ~77 MB peak memory; a pack takes 10–150 ms. Re-runs use an mtime-keyed parse cache.

---

## Installation

```bash
pip install ast-pack
```

Before the first PyPI release, install from GitHub:

```bash
pipx install git+https://github.com/ginckl/ast-pack
```

Requirements: Python 3.10+. Tree-sitter grammars for Python, TypeScript/TSX, JavaScript, Go and Rust are installed as wheels — no compiler, no Node.js, no language servers. `tiktoken` provides exact token counts; it downloads its vocabulary once and ast-pack falls back to an estimator when offline.

---

## Usage

### Pack a function, method or type

```bash
ast-pack processPayment                       # bare name
ast-pack Gateway.charge                       # Class.method / Type.method
ast-pack ledger.Append                        # Go package.Func or Type.Method
ast-pack src/payments/service.py::process     # disambiguate by file
ast-pack processPayment refundPayment         # several seeds in one bundle
```

### Pack from a line or a file

```bash
ast-pack src/billing/invoice.rs:33            # innermost symbol enclosing line 33
ast-pack web/src/lib/api.ts                   # every top-level symbol of the file
```

### Pack from a stack trace

```bash
pytest -x 2>&1 | ast-pack -d 1
ast-pack trace crash.log
pbpaste | ast-pack --copy
```

Supported formats: Python tracebacks, Node.js/V8 (`at fn (file:line:col)`, including `file://` and `webpack-internal://` paths), Go panics/goroutine dumps, Rust `panicked at` messages and `RUST_BACKTRACE` frames. Absolute paths from CI or another machine are matched to repository files by longest path suffix.

### Control the slice

```bash
ast-pack handler -d 3                         # more hops
ast-pack handler --direction callees          # only what it calls
ast-pack handler --direction callers          # only who calls it
ast-pack handler --max-tokens 6000            # fit a budget
ast-pack handler --min-confidence 1.0         # only exactly-resolved calls
ast-pack handler --include-tests              # also follow test files
ast-pack handler --type-depth 0 --no-types    # behaviour only, no type definitions
```

### Shape the output

```bash
ast-pack handler -f xml                       # <file path=... lines=...> blocks (good for Claude)
ast-pack handler -f plain                     # ==> path <== headers
ast-pack handler --line-numbers               # prefix kept lines with original numbers
ast-pack handler --strip-comments             # drop comment-only lines
ast-pack handler -p "Why does this double-charge?"   # put the task before the context
ast-pack handler -o context.md --copy         # write a file and copy to clipboard
```

---

## CLI reference

```text
ast-pack [pack] TARGET... [options]     build a bundle (default command)
ast-pack trace [FILE|-] [options]       pack a stack trace from a file or stdin
ast-pack search QUERY [-n N] [--kind K] fuzzy symbol search
ast-pack stats                          files / symbols / edges / tokens per language
ast-pack serve [--host H] [--port P] [--open] [--watch-interval S]
ast-pack --ui                           same as `serve --open`
ast-pack mcp                            Model Context Protocol server on stdio
```

| option | default | meaning |
|---|---|---|
| `-C, --repo DIR` | `.` | repository root |
| `-d, --depth N` | `2` | call-graph hops |
| `--direction` | `both` | `both`, `callers`, `callees` |
| `-b, --max-tokens N` | none | token budget |
| `--max-fanout N` | `30` | max callers/callees followed per symbol (closest first) |
| `--type-depth N` | `2` | levels of type/constant definitions |
| `--no-types` | off | skip type/constant closure |
| `--min-confidence X` | `0.5` | drop call edges resolved below this confidence |
| `--include-tests` | off | follow test files (auto-on when the target is a test) |
| `-f, --format` | `markdown` | `markdown`, `xml`, `plain` |
| `--line-numbers`, `--strip-comments`, `--no-imports`, `--no-map` | off | output shaping |
| `-p, --prompt TEXT` | none | task text before the context |
| `-o, --output FILE`, `--copy` | stdout | destination |
| `--json` | off | one JSON document on stdout ([schema.json](schema.json)) |
| `--no-bundle` | off | with `--json`: omit code, keep graph + stats |
| `--depth-profile` | off | bundle size at every depth 0..6 |
| `--include GLOB`, `--exclude GLOB`, `--lang LANGS` | all | limit what is indexed |
| `--tokenizer NAME` | `cl100k_base` | `cl100k_base`, `o200k_base`, `approx` |
| `--no-cache` | off | skip the on-disk parse cache |

Exit codes: `0` success, `1` error, `2` nothing matched (JSON error includes `suggestions`).

---

## JSON output for agents and scripts

Every command accepts `--json` and prints exactly one JSON document described by [schema.json](schema.json):

```bash
cd chi && ast-pack Mux.ServeHTTP -d 1 --json | jq '.stats'
```

```json
{
  "symbols": 11, "files": 4, "bundle_tokens": 2283, "repo_tokens": 107467,
  "touched_file_tokens": 13258, "saved_pct": 97.88, "saved_vs_files_pct": 82.78,
  "tokenizer": "cl100k_base", "tokenizer_exact": true, "elapsed_ms": 17.76, "index_generation": 1
}
```

On very small repositories the slice map and headers can cost more than they save versus whole files; `--no-map` removes the map.

A pack result contains `seeds`, `nodes` (symbol, kind, path, line range, hop, role `seed|callee|caller|type|value|container`, mode `full|outline|header`, confidence), `edges` (`call|type|value`), `files` (line ranges and `code`/`pruned` segments), `bundle`, `dropped`, `warnings`, `suggestions`, and `trace` (language, error message, crash site, frames).

---

## MCP server (Claude Code, Cursor, Windsurf)

```bash
claude mcp add ast-pack -- ast-pack mcp -C /path/to/repo
```

Generic MCP client configuration:

```json
{ "mcpServers": { "ast-pack": { "command": "ast-pack", "args": ["mcp", "-C", "/path/to/repo"] } } }
```

Tools: `pack_context(target, depth?, direction?, max_tokens?, format?, repo?)`, `search_symbols(query, limit?, repo?)`, `repo_stats(repo?)`. The index is kept in memory and refreshed incrementally on every call.

---

## Web UI (`ast-pack --ui`)

`ast-pack --ui` starts the local server on `127.0.0.1:7878` and opens the web app in your browser. Nothing leaves your machine; the page talks to the local server over a WebSocket.

- **Command bar** (`Ctrl/⌘ K`): fuzzy symbol search as you type, `↑ ↓ ⇥ ↵` navigation, recent queries, "did you mean" suggestions when nothing matches. Pasting a stack trace packs it immediately, and every in-repo frame becomes an entry point.
- **Live call graph**: a force-directed canvas. The entry point sits in the centre, callers pull to the left, callees to the right, and types and constants settle below. Nodes pop in with spring physics, staggered by hop. Call edges animate source → target. The crash site of a trace gets a red pulse. Hover a node to see its neighbourhood, click it to jump to its code, double-click it to re-root the slice there. Drag to pan, scroll to zoom, `F` to fit.
- **Hop depth slider** (`[` / `]`, `0`–`6`): a sparkline above the track shows the bundle size at every depth. Neighbouring depths are prefetched, so moving the slider typically updates the graph and counter in under 50 ms. Measured on Hono: 16–27 ms.
- **Savings counter**: rolling-digit "Saved 96.6%" with a progress ring and `753k → 25.3k tokens`.
- **Code preview**: the bundle file by file, syntax-highlighted by Shiki in a Web Worker, with original line numbers. Pruned regions are expandable pills ("14 lines pruned · notFoundHandler, errorHandler · −109 tok") that load the hidden lines on demand. Trace frames get a clickable crash panel. Hovering code highlights the symbol in the graph, and hovering the graph highlights the code.
- **Copy optimized prompt** (`C` or `Ctrl/⌘ ⇧ C`) in Markdown, XML or plain. You can attach an optional task prompt, and the options popover covers the token budget, type definitions, test files, exact edges and comment stripping.
- Light and dark themes (`T`), `\` toggles the code pane, and `?` lists every shortcut.

The page is a React + TypeScript app in `ui/` (Tailwind CSS, Framer Motion, Lucide icons, d3-force, Shiki). Its production build is committed to `src/ast_pack/web/`, so `pip install` ships it with no Node.js needed. To work on it:

```bash
ast-pack serve -C /path/to/repo        # API on :7878
cd ui && npm install && npm run dev    # Vite on :5173, proxies /api and /ws to :7878
npm run build                          # writes src/ast_pack/web/
node e2e/smoke.mjs                     # end-to-end test against a real server in Chromium
```

## HTTP / WebSocket API

`ast-pack serve` watches the repository and re-indexes changed files. Connected pages receive an `index_updated` push and re-pack automatically.

| endpoint | purpose |
|---|---|
| `GET /api/health` | version, root, index generation, whether the UI bundle is present |
| `GET /api/stats` | index statistics |
| `GET /api/search?q=` | fuzzy symbol search |
| `POST /api/pack` | body: pack options (`targets`, `depth`, `direction`, `max_tokens`, `format`, `depth_profile`, ...) |
| `GET /api/file?path=` | full source of an indexed file (to expand pruned segments) |
| `GET /api/graph?limit=` | repository overview graph |
| `POST /api/refresh` | force re-scan |
| `GET /api` | human-readable API index (with Schema.org JSON-LD) |
| `WS /ws` | `pack` / `search` / `file` / `graph` messages; `pack` is latest-wins per `channel` (`main`, `prefetch`, `profile`) |

## Python library API

```python
from ast_pack import RepoIndex, PackOptions, pack

index = RepoIndex.build("path/to/repo")
result = pack(index, PackOptions(targets=["processPayment"], depth=2, max_tokens=8000))
print(result.bundle)
print(result.bundle_tokens, result.saved_pct)
for node in result.to_dict()["nodes"]:
    print(node["role"], node["qualname"], node["path"], node["start_line"])
index.refresh()  # re-parse only changed files
```

---

## How it works

```text
scanner ──► extractors (Tree-sitter, per language) ──► RepoIndex ──► slicer ──► renderer ──► bundle
  git ls-files        symbols · refs · imports            name resolution     BFS callers/   line plan:
  .gitignore          field types · local types           call/type/value     callees +      full / outline /
  size & vendor       comment lines                       edges + reverse     type closure   header + pruned
  filters             (parallel, cached by mtime)         index               + budget       markers
```

- **Extraction** (`src/ast_pack/extractors/`): one Tree-sitter walker per language records symbols with exact ranges (doc comments, decorators and attributes included), outline anchors (where bodies start), imports, and every referenced name with its receiver (`self.repo.save` → `save` on `self.repo`). Parameters, locals and loop variables are filtered; typed parameters and struct/class fields record their types.
- **Resolution** (`src/ast_pack/index.py`): bare names resolve through the file, its imports (following re-export chains), and language scope (Go package directories, Rust crates). Member calls resolve through `self`/`this`/receivers, declared field types, typed locals, module aliases and base classes/traits. Calls on values of unknown type are matched by name only when at most three methods share it and the name is not ubiquitous (`get`, `close`, …), with confidence < 1.
- **Slicing** (`src/ast_pack/slicer.py`): two breadth-first walks (callees and callers) that never mix, a per-node fan-out cap that prefers nearby code, then a closure over type and value edges.
- **Rendering** (`src/ast_pack/render.py`): a per-file line plan; Python classes that lose every statement get `...`; markers that would cost more tokens than the code they hide are replaced by the code.

---

## Limitations

- Resolution is static and name-based, not a type checker: dynamic dispatch, monkey-patching, reflection, dependency injection containers and calls through untyped values can be missed or (with confidence < 1) over-included. Use `--min-confidence 1.0` for exact edges only.
- Callers reached only through interfaces/traits (Go interface satisfaction, Rust `dyn Trait`) are not linked to their implementations.
- Macros (Rust) and decorators that generate code are treated as references, not expanded.
- Supported languages: Python, TypeScript, TSX, JavaScript/JSX, Go, Rust. Other files are ignored.
- `tree-sitter` 0.26.0's Python binding crashes on some real-world files, so the dependency is pinned below 0.26 until that is fixed upstream.

---

## Contributing, citation, license

- Tests: `pip install -e ".[dev]" && pytest`
- Benchmarks: `python benchmarks/bench.py` · validity: `python benchmarks/validity.py <repo>`
- Machine-readable docs: [llms.txt](llms.txt), [llms-full.txt](llms-full.txt), [AGENT_GUIDE.md](AGENT_GUIDE.md), [schema.json](schema.json)
- Cite: see [CITATION.cff](CITATION.cff)
- License: [MIT](LICENSE)
