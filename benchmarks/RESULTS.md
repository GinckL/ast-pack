# ast-pack benchmark results

Measured on 2026-11-04 with ast-pack 0.1.0, Python 3.13, 4 vCPU Linux container.
Reproduce with:

```bash
python benchmarks/bench.py --workdir /tmp/ast-pack-bench
```

Every repository is checked out at the pinned commit shown. Each row packs one
real entry point (`ast-pack <entry> -d <depth>` with default options: callers +
callees, type depth 2, test files excluded).

* **saved vs repo** – bundle tokens compared to the whole indexed repository
  (what whole-repo packers such as Repomix or gitingest emit by default).
* **saved vs whole files** – bundle tokens compared to pasting, in full, every
  file the slice touches (the "copy the relevant files" workaround).
* Bundle tokens include ast-pack's own headers and slice map.

## Token savings

Tokenizer: `cl100k_base`

| repo | language | entry point | depth | symbols | files | bundle tokens | repo tokens | saved vs repo | saved vs whole files | index / pack time |
|---|---|---|---|---|---|---|---|---|---|---|
| flask @ `49943b5` | Python | `Flask.full_dispatch_request` | 1 | 29 | 9 | 10,834 | 134,903 | **92.0%** | 70.9% | 0.24 s / 41 ms |
| flask @ `49943b5` | Python | `Flask.full_dispatch_request` | 2 | 50 | 11 | 16,280 | 134,903 | **87.9%** | 64.8% | 0.24 s / 59 ms |
| httpx @ `b5addb6` | Python | `Client.send` | 1 | 38 | 8 | 7,567 | 133,516 | **94.3%** | 80.2% | 0.54 s / 39 ms |
| httpx @ `b5addb6` | Python | `Client.send` | 2 | 82 | 13 | 17,176 | 133,516 | **87.1%** | 65.1% | 0.54 s / 67 ms |
| gin @ `0f09c3a` | Go | `Context.JSON` | 1 | 33 | 10 | 4,782 | 196,695 | **97.6%** | 86.0% | 0.35 s / 27 ms |
| gin @ `0f09c3a` | Go | `Context.JSON` | 2 | 41 | 10 | 5,592 | 196,695 | **97.2%** | 83.6% | 0.35 s / 27 ms |
| chi @ `9f8adb1` | Go | `Mux.ServeHTTP` | 1 | 11 | 4 | 2,283 | 107,467 | **97.9%** | 82.8% | 0.22 s / 12 ms |
| chi @ `9f8adb1` | Go | `Mux.ServeHTTP` | 2 | 11 | 4 | 2,283 | 107,467 | **97.9%** | 82.8% | 0.22 s / 11 ms |
| hono @ `8b7f9e9` | TypeScript | `Hono.fetch` | 1 | 125 | 27 | 22,127 | 752,557 | **97.1%** | 69.1% | 0.98 s / 135 ms |
| hono @ `8b7f9e9` | TypeScript | `Hono.fetch` | 2 | 142 | 30 | 25,248 | 752,557 | **96.7%** | 65.3% | 0.98 s / 114 ms |
| zod @ `77e72ec` | TypeScript | `ZodString._parse` | 1 | 61 | 5 | 13,086 | 1,003,297 | **98.7%** | 72.3% | 1.42 s / 71 ms |
| zod @ `77e72ec` | TypeScript | `ZodString._parse` | 2 | 70 | 7 | 15,484 | 1,003,297 | **98.5%** | 68.0% | 1.42 s / 64 ms |
| ripgrep @ `91f5d22` | Rust | `search_path` | 1 | 39 | 13 | 18,255 | 460,732 | **96.0%** | 88.9% | 0.72 s / 104 ms |
| ripgrep @ `91f5d22` | Rust | `search_path` | 2 | 56 | 15 | 21,606 | 460,732 | **95.3%** | 88.1% | 0.72 s / 118 ms |

## Syntactic validity

`benchmarks/validity.py` packs 200 random functions / methods / classes /
structs per repository at depth 1 and re-parses every rendered file (Python
with `ast.parse`, the other languages with Tree-sitter error nodes).

| repository | rendered files checked | invalid |
|---|---|---|
| flask | 1040 | 0 |
| httpx | 1008 | 0 |
| gin | 1061 | 0 |
| chi | 686 | 0 |
| hono | 1105 | 0 |
| zod | 1054 | 0 |
| ripgrep | 651 | 0 |

## Indexing cost

| repository | files | symbols | edges | tokens | cold index | peak RSS |
|---|---|---|---|---|---|---|
| flask | 83 | 1,068 | 2,505 | 134,903 | 0.25 s | 64 MB |
| httpx | 60 | 1,253 | 3,449 | 133,516 | 0.75 s | 64 MB |
| gin | 99 | 1,722 | 4,641 | 196,695 | 0.36 s | 66 MB |
| chi | 89 | 557 | 1,362 | 107,467 | 0.24 s | 63 MB |
| hono | 453 | 2,102 | 5,120 | 752,557 | 0.90 s | 68 MB |
| zod | 522 | 5,113 | 19,143 | 1,003,297 | 1.11 s | 77 MB |
| ripgrep | 102 | 3,846 | 9,802 | 460,732 | 0.71 s | 72 MB |

Warm runs reuse the on-disk parse cache (`~/.cache/ast-pack`) and only re-parse
files whose mtime or size changed.

## Token estimator accuracy

When tiktoken's vocabulary cannot be loaded (offline machines), ast-pack falls
back to a built-in estimator and labels output `tokenizer: "approx"`. Against
exact `cl100k_base` on 120 random files per repository:

| repository | exact | estimated | ratio | per-file p10–p90 |
|---|---|---|---|---|
| flask | 134,903 | 136,551 | 1.012 | 0.99–1.05 |
| httpx | 133,516 | 133,411 | 0.999 | 0.96–1.03 |
| gin | 196,695 | 189,194 | 0.962 | 0.92–1.01 |
| hono | 141,237 | 141,880 | 1.005 | 0.94–1.05 |
| zod | 175,592 | 176,899 | 1.007 | 0.91–1.09 |
| ripgrep | 460,732 | 461,311 | 1.001 | 0.97–1.04 |
