"""Check that every rendered file in a bundle parses in its own language.

    python benchmarks/validity.py /path/to/repo --samples 200

Picks random functions/methods/classes/structs, packs each at depth 1, and
re-parses every output file: Python with ``ast.parse``; TypeScript, JavaScript,
Go and Rust with Tree-sitter (a file counts as invalid if it has more error
nodes than the original source file had).
"""

from __future__ import annotations

import argparse
import ast
import random
import sys
import warnings
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--samples", type=int, default=200)
    ap.add_argument("--depth", type=int, default=1)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from ast_pack import PackOptions, RepoIndex, pack
    from ast_pack.extractors.base import count_errors
    from ast_pack.languages import get_parser

    warnings.filterwarnings("ignore", category=SyntaxWarning)
    random.seed(args.seed)
    index = RepoIndex.build(args.repo)
    cands = [s for s in index.symbols.values() if s.kind in ("function", "method", "class", "struct")]
    random.shuffle(cands)
    checked = invalid = 0
    for sym in cands[: args.samples]:
        result = pack(index, PackOptions(targets=[f"{sym.path}::{sym.qualname}"], depth=args.depth, slice_map=False))
        for f in result.files:
            checked += 1
            original_errors = index.files[f.path].parse_errors
            if f.lang == "python":
                try:
                    ast.parse(f.text)
                    ok = True
                except SyntaxError as exc:
                    ok = original_errors > 0
                    detail = str(exc)
            else:
                errors = count_errors(get_parser(f.lang).parse(f.text.encode()).root_node)
                ok = errors <= original_errors
                detail = f"{errors} error nodes (original file: {original_errors})"
            if not ok:
                invalid += 1
                print(f"INVALID {sym.id} -> {f.path}: {detail}", file=sys.stderr)
    print(f"{Path(args.repo).name}: {checked} rendered files checked, {invalid} invalid")
    return 1 if invalid else 0


if __name__ == "__main__":
    raise SystemExit(main())
