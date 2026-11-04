"""Reproducible ast-pack benchmark.

Clones each repository at a pinned commit into a work directory, then packs a
fixed entry point at depth 1 and 2 and prints a Markdown table.

    python benchmarks/bench.py --workdir /tmp/ast-pack-bench > benchmarks/RESULTS.md

"saved vs repo" compares the bundle to the whole indexed repository (what
whole-repo packers emit); "saved vs whole files" compares it to pasting every
file the slice touches in full (what manual copy-paste of the relevant files
costs). Token counts are cl100k_base when tiktoken can load its vocabulary.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPOS = [
    # name, url, commit, language, entry point
    ("flask", "https://github.com/pallets/flask", "49943b5a94413a530761350f04e896f76e8d620e", "Python", "Flask.full_dispatch_request"),
    ("httpx", "https://github.com/encode/httpx", "b5addb64f0161ff6bfe94c124ef76f6a1fba5254", "Python", "Client.send"),
    ("gin", "https://github.com/gin-gonic/gin", "0f09c3a9b4626d9fe9979cf4d0521d6ae32ab646", "Go", "Context.JSON"),
    ("chi", "https://github.com/go-chi/chi", "9f8adb1aabaa8a91180a821111d3f8e668d1c0bf", "Go", "Mux.ServeHTTP"),
    ("hono", "https://github.com/honojs/hono", "8b7f9e97d661dbc8e933cf81dc36fec8d35b9146", "TypeScript", "Hono.fetch"),
    ("zod", "https://github.com/colinhacks/zod", "77e72ec29ed70d87ac0a5a3b0b25b0ce3bc0e6c3", "TypeScript", "ZodString._parse"),
    ("ripgrep", "https://github.com/BurntSushi/ripgrep", "91f5d22ef48bde459d90a8c7dbeab416e97d0f2b", "Rust", "search_path"),
]


def checkout(workdir: Path, name: str, url: str, commit: str) -> Path:
    dest = workdir / name
    if not (dest / ".git").is_dir():
        dest.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q"], cwd=dest, check=True)
        subprocess.run(["git", "remote", "add", "origin", url], cwd=dest, check=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=dest, capture_output=True, text=True)
    if head.returncode != 0 or head.stdout.strip() != commit:
        subprocess.run(["git", "fetch", "-q", "--depth", "1", "origin", commit], cwd=dest, check=True)
        subprocess.run(["git", "checkout", "-q", "--detach", commit], cwd=dest, check=True)
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--workdir", default=".bench", help="where repositories are cloned")
    ap.add_argument("--depths", default="1,2")
    args = ap.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from ast_pack import PackOptions, RepoIndex, pack

    workdir = Path(args.workdir).resolve()
    depths = [int(d) for d in args.depths.split(",")]
    rows = []
    tokenizer = "?"
    for name, url, commit, lang, entry in REPOS:
        root = checkout(workdir, name, url, commit)
        index = RepoIndex.build(root)
        tokenizer = index.counter.name
        st = index.stats()
        index_s = st["timing"]["scan_parse_seconds"] + st["timing"]["resolve_seconds"]
        for d in depths:
            r = pack(index, PackOptions(targets=[entry], depth=d))
            if not r.ok:
                print(f"{name}: {entry} not found: {r.resolution.warnings}", file=sys.stderr)
                continue
            n = sum(1 for x in r.graph.nodes.values() if x.role != "container")
            rows.append(
                f"| {name} @ `{commit[:7]}` | {lang} | `{entry}` | {d} | {n} | {len(r.files)} | "
                f"{r.bundle_tokens:,} | {r.repo_tokens:,} | **{r.saved_pct:.1f}%** | {r.saved_vs_files_pct:.1f}% | "
                f"{index_s:.2f} s / {r.elapsed_ms:.0f} ms |"
            )
    print(f"Tokenizer: `{tokenizer}`\n")
    print("| repo | language | entry point | depth | symbols | files | bundle tokens | repo tokens | saved vs repo | saved vs whole files | index / pack time |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    print("\n".join(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
