"""Repository index: parsed files, symbol table and the cross-file graph.

``RepoIndex.build(root)`` scans the repository, extracts every supported file
with Tree-sitter (in parallel for large repos, reusing an on-disk cache keyed
by mtime/size), then resolves every reference to concrete symbols:

* bare names resolve through the file's own definitions, its imports
  (following re-export chains and barrel files), then language scope rules
  (Go: same package directory, Rust: same crate);
* ``self.x`` / ``this.x`` / ``Self::x`` / Go receivers resolve to methods of
  the owning type, then its base classes / implemented traits;
* ``module.x`` / ``pkg.X`` / ``ns.x`` resolve through module bindings to the
  target file(s);
* calls on values of unknown type (``obj.save()``) resolve only when at most
  three methods in the repo share that name, with reduced confidence.

The result is a directed graph of ``call`` / ``type`` / ``value`` edges with
a reverse index for caller lookups.
"""

from __future__ import annotations

import hashlib
import json
import os
import pickle
import re
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from . import __version__
from .extractors import EXTRACTOR_VERSION, extract_path
from .languages import FAMILY
from .models import (
    BLOCK_KIND,
    CALLABLE_KINDS,
    TYPE_KINDS,
    VALUE_KINDS,
    Edge,
    FileExtraction,
    ImportBinding,
    Symbol,
    edge_kind_for,
)
from .scanner import DEFAULT_MAX_FILE_BYTES, SourceFile, scan
from .tokens import get_counter

_JS_EXTS = (".ts", ".tsx", ".d.ts", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")
_UNKNOWN_RECEIVER_LIMIT = 3
# Method names so common (stdlib / framework interfaces) that matching them by
# name alone on a receiver of unknown type is noise, not signal.
_UBIQUITOUS_METHODS = frozenset(
    """get set put add remove delete del update close open read write run start stop call apply bind
    map filter reduce find push pop append extend insert len size count keys values items value string
    error next reset clear copy clone send emit on off once then catch finally tostring valueof json text
    format parse init load save flush wait lock unlock done handle serve listen join split replace strip
    trim lower upper encode decode contains has is_empty isempty empty length iter into from as_ref
    as_str to_string unwrap expect ok err some none default new create build dispatch execute process
    log debug info warn warning fatal print println printf sprintf errorf fprintf with context cancel
    subscribe unsubscribe use match test exec compile render mount""".split()
)
_NOT_REFERENCEABLE = frozenset({BLOCK_KIND, "impl"})


@dataclass
class IndexOptions:
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    languages: set[str] | None = None
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    tokenizer: str | None = None
    use_cache: bool = True
    workers: int | None = None


def _cache_dir() -> Path:
    base = os.environ.get("AST_PACK_CACHE_DIR") or os.environ.get("XDG_CACHE_HOME")
    if base:
        return Path(base) / ("" if os.environ.get("AST_PACK_CACHE_DIR") else "ast-pack")
    return Path.home() / ".cache" / "ast-pack"


def _strip_json_comments(text: str) -> str:
    out: list[str] = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j == -1 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j == -1 else j + 2
        else:
            out.append(ch)
            i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def _norm(path: str) -> str:
    parts: list[str] = []
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    return "/".join(parts)


_TEST_DIRS = frozenset({"test", "tests", "__tests__", "__test__", "spec", "specs", "testdata", "testing", "e2e", "__mocks__", "fixtures"})
_TEST_FILE_RE = re.compile(
    r"(^test_.*\.pyi?$|.*_test\.(py|go|rs)$|^conftest\.py$|.*\.(test|spec)\.[cm]?[jt]sx?$|.*\.(test|spec)-d\.ts$)"
)


def is_test_path(path: str) -> bool:
    parts = path.split("/")
    if any(p in _TEST_DIRS for p in parts[:-1]):
        return True
    return bool(_TEST_FILE_RE.match(parts[-1]))


def _dirname(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


class RepoIndex:
    """In-memory symbol graph of a repository."""

    def __init__(self, root: str | os.PathLike[str], options: IndexOptions | None = None) -> None:
        self.root = Path(root).resolve()
        self.options = options or IndexOptions()
        self.counter = get_counter(self.options.tokenizer)
        self.files: dict[str, FileExtraction] = {}
        self.symbols: dict[str, Symbol] = {}
        self.edges_out: dict[str, list[Edge]] = {}
        self.edges_in: dict[str, list[Edge]] = {}
        self.generation = 0
        self.build_seconds = 0.0
        self.resolve_seconds = 0.0
        self.parsed_files = 0
        self.cached_files = 0
        self._text_cache: dict[str, tuple[int, list[str]]] = {}

    # ================================================================ build
    @classmethod
    def build(cls, root: str | os.PathLike[str] = ".", options: IndexOptions | None = None) -> "RepoIndex":
        index = cls(root, options)
        index.refresh(force=True)
        return index

    def _cache_path(self) -> Path:
        key = hashlib.sha1(f"{self.root}|{self.counter.name}".encode()).hexdigest()[:16]
        return _cache_dir() / f"index-{key}.pickle"

    def _load_cache(self) -> dict[str, FileExtraction]:
        if not self.options.use_cache:
            return {}
        path = self._cache_path()
        try:
            with open(path, "rb") as fh:
                data = pickle.load(fh)
        except (OSError, pickle.UnpicklingError, EOFError, AttributeError, ImportError, TypeError, ValueError):
            return {}
        if not isinstance(data, dict) or data.get("version") != (__version__, EXTRACTOR_VERSION):
            return {}
        files = data.get("files")
        return files if isinstance(files, dict) else {}

    def _save_cache(self) -> None:
        if not self.options.use_cache:
            return
        path = self._cache_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(f".tmp{os.getpid()}")
            with open(tmp, "wb") as fh:
                pickle.dump({"version": (__version__, EXTRACTOR_VERSION), "files": self.files}, fh, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp, path)
        except OSError:
            pass

    def scan(self) -> list[SourceFile]:
        o = self.options
        return scan(self.root, include=o.include, exclude=o.exclude, languages=o.languages, max_file_bytes=o.max_file_bytes)

    def refresh(self, force: bool = False) -> bool:
        """Re-scan the repository; re-parse changed files. Returns True if anything changed."""
        t0 = time.perf_counter()
        sources = self.scan()
        previous = self.files if self.files else (self._load_cache() if force else {})
        fresh: dict[str, FileExtraction] = {}
        todo: list[SourceFile] = []
        for sf in sources:
            old = previous.get(sf.rel_path)
            if old is not None and old.mtime_ns == sf.mtime_ns and old.size == sf.size and old.lang == sf.lang:
                fresh[sf.rel_path] = old
            else:
                todo.append(sf)
        changed = bool(todo) or set(fresh) != set(self.files) or force
        if not changed:
            return False
        self.cached_files = len(fresh)
        self.parsed_files = len(todo)
        for result in self._extract_many(todo):
            if result is not None:
                fresh[result.path] = result
        self.files = dict(sorted(fresh.items()))
        self._text_cache = {k: v for k, v in self._text_cache.items() if k in self.files}
        self.build_seconds = time.perf_counter() - t0
        t1 = time.perf_counter()
        self._rebuild()
        self.resolve_seconds = time.perf_counter() - t1
        self.generation += 1
        self._save_cache()
        return True

    def _extract_many(self, todo: list[SourceFile]):
        args = [(sf.abs_path, sf.rel_path, sf.lang, sf.mtime_ns, sf.size, self.options.tokenizer) for sf in todo]
        workers = self.options.workers
        if workers is None:
            workers = min(8, os.cpu_count() or 1)
        if workers > 1 and len(args) >= 64:
            try:
                with ProcessPoolExecutor(max_workers=workers) as pool:
                    yield from pool.map(extract_path, args, chunksize=max(4, len(args) // (workers * 8)))
                return
            except (OSError, RuntimeError):
                pass  # e.g. process spawning disallowed: fall back to serial
        for a in args:
            yield extract_path(a)

    # ========================================================== derived maps
    def _rebuild(self) -> None:
        self._load_project_files()
        self._crate_cache: dict[str, str] = {}
        self.symbols = {}
        self.by_name: dict[str, list[str]] = defaultdict(list)
        self.by_file: dict[str, list[str]] = {}
        self.toplevel_by_file: dict[str, dict[str, list[str]]] = {}
        self.methods_by_key: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        self.methods_by_name: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        self.imports_by_file: dict[str, dict[str, list[ImportBinding]]] = {}
        self.wildcards_by_file: dict[str, list[ImportBinding]] = {}
        self.dir_files: dict[str, list[str]] = defaultdict(list)
        self.py_modules: dict[str, list[str]] = defaultdict(list)
        self.rust_stems: dict[str, list[str]] = defaultdict(list)
        self.go_pkg_names: dict[str, str] = {}
        self.impls_by_key: dict[str, list[str]] = defaultdict(list)

        for path, fx in self.files.items():
            ids: list[str] = []
            top: dict[str, list[str]] = defaultdict(list)
            for sym in fx.symbols:
                self.symbols[sym.id] = sym
                ids.append(sym.id)
            for sym in fx.symbols:
                if sym.kind == BLOCK_KIND:
                    continue
                parent = self.symbols.get(sym.parent) if sym.parent else None
                if sym.kind != "impl":
                    self.by_name[sym.name].append(sym.id)
                if sym.kind == "method":
                    key = self._method_key(sym)
                    self.methods_by_key[key][sym.name].append(sym.id)
                    self.methods_by_name[FAMILY[sym.lang]][sym.name].append(sym.id)
                elif sym.kind == "impl":
                    self.impls_by_key[self._type_key_parts(sym.lang, sym.path, sym.owner or "")].append(sym.id)
                elif parent is None or parent.kind == "module":
                    top[sym.name].append(sym.id)
            self.by_file[path] = ids
            self.toplevel_by_file[path] = dict(top)
            imap: dict[str, list[ImportBinding]] = defaultdict(list)
            wild: list[ImportBinding] = []
            for b in fx.imports:
                if b.wildcard:
                    wild.append(b)
                else:
                    imap[b.local].append(b)
            self.imports_by_file[path] = dict(imap)
            self.wildcards_by_file[path] = wild
            self.dir_files[_dirname(path)].append(path)
            if fx.lang == "python":
                self._register_py_module(path)
            elif fx.lang == "rust":
                stem = PurePosixPath(path).stem
                if stem == "mod":
                    stem = PurePosixPath(path).parent.name
                self.rust_stems[stem].append(path)
            elif fx.lang == "go" and fx.package:
                self.go_pkg_names[_dirname(path)] = fx.package

        self._resolve_edges()

    def _register_py_module(self, path: str) -> None:
        p = PurePosixPath(path)
        parts = list(p.parent.parts) if p.stem == "__init__" else [*p.parent.parts, p.stem]
        for i in range(len(parts)):
            self.py_modules[".".join(parts[i:])].append(path)

    def _load_project_files(self) -> None:
        """Read go.mod / Cargo.toml / tsconfig.json / package.json metadata."""
        self.go_modules: dict[str, str] = {}
        self.rust_crates: dict[str, str] = {}
        self.ts_configs: dict[str, dict] = {}
        self.js_packages: dict[str, str] = {}
        for dirpath, dirnames, filenames in os.walk(self.root):
            rel_dir = os.path.relpath(dirpath, self.root).replace(os.sep, "/")
            rel_dir = "" if rel_dir == "." else rel_dir
            depth = 0 if not rel_dir else rel_dir.count("/") + 1
            from .scanner import DEFAULT_EXCLUDED_DIRS

            dirnames[:] = [d for d in dirnames if d not in DEFAULT_EXCLUDED_DIRS and not d.startswith(".")] if depth < 5 else []
            names = set(filenames)
            if "go.mod" in names:
                try:
                    text = (Path(dirpath) / "go.mod").read_text("utf-8", "replace")
                    m = re.search(r"^module\s+(\S+)", text, re.M)
                    if m:
                        self.go_modules[m.group(1)] = rel_dir
                except OSError:
                    pass
            if "Cargo.toml" in names:
                try:
                    text = (Path(dirpath) / "Cargo.toml").read_text("utf-8", "replace")
                    m = re.search(r'^\[package\][^\[]*?^name\s*=\s*"([^"]+)"', text, re.M | re.S)
                    if m:
                        self.rust_crates[m.group(1).replace("-", "_")] = rel_dir
                except OSError:
                    pass
            for cfg in ("tsconfig.json", "jsconfig.json"):
                if cfg in names and rel_dir not in self.ts_configs:
                    try:
                        data = json.loads(_strip_json_comments((Path(dirpath) / cfg).read_text("utf-8", "replace")))
                        opts = data.get("compilerOptions") or {}
                        base = _norm(f"{rel_dir}/{opts.get('baseUrl', '.')}")
                        self.ts_configs[rel_dir] = {"baseUrl": base, "paths": opts.get("paths") or {}}
                    except (OSError, ValueError, AttributeError):
                        pass
            if "package.json" in names and rel_dir:
                try:
                    data = json.loads((Path(dirpath) / "package.json").read_text("utf-8", "replace"))
                    if isinstance(data, dict) and isinstance(data.get("name"), str):
                        self.js_packages[data["name"]] = rel_dir
                except (OSError, ValueError):
                    pass

    # ================================================================ scopes
    def _crate_dir(self, path: str) -> str:
        cached = self._crate_cache.get(path)
        if cached is not None:
            return cached
        best = ""
        for d in self.rust_crates.values():
            if (not d or path.startswith(d + "/")) and len(d) >= len(best):
                best = d
        self._crate_cache[path] = best
        return best

    def _type_key_parts(self, lang: str, path: str, name: str) -> str:
        fam = FAMILY[lang]
        if fam == "go":
            return f"go:{_dirname(path)}:{name}"
        if fam == "rust":
            return f"rs:{self._crate_dir(path)}:{name}"
        return f"{fam}:{path}:{name}"

    def _method_key(self, sym: Symbol) -> str:
        fam = FAMILY[sym.lang]
        if fam in ("python", "js") and sym.parent:
            return sym.parent
        return self._type_key_parts(sym.lang, sym.path, sym.owner or "")

    def _type_key(self, type_sym: Symbol) -> str:
        fam = FAMILY[type_sym.lang]
        if fam in ("python", "js"):
            return type_sym.id
        return self._type_key_parts(type_sym.lang, type_sym.path, type_sym.name)

    # ===================================================== module resolution
    def resolve_module(self, from_path: str, binding: ImportBinding) -> list[str] | None:
        """Files a module specifier points to. ``None`` = external / unknown."""
        lang = self.files[from_path].lang
        fam = FAMILY[lang]
        spec = binding.module
        if spec == ".":
            return [from_path]
        if fam == "python":
            return self._py_resolve(from_path, spec)
        if fam == "js":
            return self._js_resolve(from_path, spec)
        if fam == "go":
            return self._go_resolve(spec)
        if fam == "rust":
            return self._rust_resolve(from_path, spec)
        return None

    def _py_resolve(self, from_path: str, spec: str) -> list[str] | None:
        if spec.startswith("."):
            dots = len(spec) - len(spec.lstrip("."))
            rest = spec[dots:]
            base = _dirname(from_path)
            for _ in range(dots - 1):
                base = _dirname(base)
            rel = "/".join(p for p in [base, rest.replace(".", "/")] if p)
            cands = [f"{rel}.py", f"{rel}/__init__.py", f"{rel}.pyi"] if rest else [f"{base}/__init__.py" if base else "__init__.py"]
            found = [c for c in cands if c in self.files]
            return found or None
        cands = self.py_modules.get(spec)
        if not cands:
            return None
        # Prefer files whose implied sys.path root is shallowest.
        def root_depth(p: str) -> int:
            return p.count("/") - spec.count(".") - (1 if p.endswith("__init__.py") else 0)

        best = min(root_depth(c) for c in cands)
        return [c for c in cands if root_depth(c) == best]

    def _js_candidates(self, base: str) -> list[str]:
        base = _norm(base)
        if base in self.files:
            return [base]
        stem = base
        for ext in (".js", ".jsx", ".mjs", ".cjs"):
            if base.endswith(ext):
                stem = base[: -len(ext)]
                break
        out = [stem + ext for ext in _JS_EXTS if stem + ext in self.files]
        if not out:
            out = [f"{base}/index{ext}" for ext in _JS_EXTS if f"{base}/index{ext}" in self.files]
        return out

    def _ts_config_for(self, from_path: str) -> dict | None:
        d = _dirname(from_path)
        while True:
            if d in self.ts_configs:
                return self.ts_configs[d]
            if not d:
                return None
            d = _dirname(d)

    def _js_resolve(self, from_path: str, spec: str) -> list[str] | None:
        if spec.startswith("."):
            return self._js_candidates(f"{_dirname(from_path)}/{spec}") or None
        cfg = self._ts_config_for(from_path)
        if cfg:
            for pattern, targets in cfg["paths"].items():
                if not isinstance(targets, list):
                    continue
                if pattern.endswith("*"):
                    prefix = pattern[:-1]
                    if not spec.startswith(prefix):
                        continue
                    rest = spec[len(prefix) :]
                elif spec == pattern:
                    rest = ""
                else:
                    continue
                for target in targets:
                    found = self._js_candidates(f"{cfg['baseUrl']}/{target.replace('*', rest)}")
                    if found:
                        return found
            found = self._js_candidates(f"{cfg['baseUrl']}/{spec}")
            if found:
                return found
        for name, pdir in sorted(self.js_packages.items(), key=lambda kv: -len(kv[0])):
            if spec == name or spec.startswith(name + "/"):
                rest = spec[len(name) :].lstrip("/")
                for base in ([f"{pdir}/{rest}", f"{pdir}/src/{rest}"] if rest else [f"{pdir}/src/index", f"{pdir}/index", f"{pdir}/src"]):
                    found = self._js_candidates(base)
                    if found:
                        return found
        if spec.startswith(("@/", "~/", "#/")):
            rest = spec[2:]
            for base in (f"src/{rest}", rest):
                found = self._js_candidates(base)
                if found:
                    return found
        return None

    def _go_resolve(self, spec: str) -> list[str] | None:
        for mod, mdir in sorted(self.go_modules.items(), key=lambda kv: -len(kv[0])):
            if spec == mod or spec.startswith(mod + "/"):
                rel = _norm(f"{mdir}/{spec[len(mod):]}")
                files = [f for f in self.dir_files.get(rel, []) if f.endswith(".go")]
                return files or None
        segs = spec.split("/")
        for i in range(len(segs) - 1):
            rel = "/".join(segs[i:])
            files = [f for f in self.dir_files.get(rel, []) if f.endswith(".go")]
            if files:
                return files
        return None

    def _rust_module_files(self, crate_dir: str, segs: list[str]) -> list[str]:
        src = f"{crate_dir}/src" if crate_dir else "src"
        if not segs:
            return [c for c in (f"{src}/lib.rs", f"{src}/main.rs") if c in self.files]
        rel = "/".join(segs)
        return [c for c in (f"{src}/{rel}.rs", f"{src}/{rel}/mod.rs") if c in self.files]

    def _rust_file_module(self, path: str) -> list[str]:
        crate = self._crate_dir(path)
        src = f"{crate}/src/" if crate else "src/"
        if not path.startswith(src):
            return []
        rel = path[len(src) :][: -len(".rs")]
        segs = rel.split("/")
        if segs[-1] == "mod" or (len(segs) == 1 and segs[0] in ("lib", "main")):
            segs = segs[:-1]
        return segs

    def _rust_resolve(self, from_path: str, spec: str) -> list[str] | None:
        if not spec:
            return None
        segs = [s for s in spec.split("::") if s]
        crate = self._crate_dir(from_path)
        if segs[0] == "crate":
            base: list[str] = []
            segs = segs[1:]
        elif segs[0] in ("self", "super"):
            base = self._rust_file_module(from_path)
            while segs and segs[0] in ("self", "super"):
                if segs[0] == "super" and base:
                    base = base[:-1]
                segs = segs[1:]
        elif segs[0] in self.rust_crates:
            crate = self.rust_crates[segs[0]]
            base = []
            segs = segs[1:]
        else:
            # Could be a sibling module path relative to the current module.
            base = self._rust_file_module(from_path)
            files = self._rust_module_files(crate, base + segs)
            if files:
                return files
            return None
        # The last segment may be an item (``use crate::a::Item``) rather
        # than a module; try the longest module prefix that exists.
        for cut in range(len(segs), -1, -1):
            files = self._rust_module_files(crate, base + segs[:cut])
            if files:
                return files
        return None

    # ======================================================= name resolution
    def _top(self, path: str, name: str) -> list[str]:
        ids = self.toplevel_by_file.get(path, {}).get(name, [])
        return [i for i in ids if self.symbols[i].kind not in ("method",) and self.symbols[i].kind not in _NOT_REFERENCEABLE]

    def export_lookup(self, path: str, name: str, depth: int = 0) -> list[str]:
        if depth > 6 or path not in self.files:
            return []
        found = self._top(path, name)
        if found:
            return found
        for b in self.imports_by_file.get(path, {}).get(name, []):
            if b.imported is None:
                continue
            files = self.resolve_module(path, b)
            if not files:
                continue
            for f in files:
                found.extend(self.export_lookup(f, b.imported, depth + 1) if f != path or b.imported != name else [])
            if found:
                return found
        for b in self.wildcards_by_file.get(path, []):
            for f in self.resolve_module(path, b) or []:
                if f != path:
                    found.extend(self.export_lookup(f, name, depth + 1))
            if found:
                return found
        return found

    def resolve_name(self, path: str, name: str) -> tuple[list[str], bool]:
        """Resolve a bare identifier in ``path``.

        Returns ``(symbol_ids, known)``; ``known`` is True when the name is
        bound to something (possibly external) so no fuzzy fallback applies.
        """
        local = self._top(path, name)
        if local:
            return local, True
        fx = self.files[path]
        fam = FAMILY[fx.lang]
        bindings = self.imports_by_file.get(path, {}).get(name, [])
        for b in bindings:
            files = self.resolve_module(path, b)
            if files is None:
                return [], True  # external package
            if b.imported is None:
                return [], True  # module / namespace binding, not a symbol
            found: list[str] = []
            for f in files:
                found.extend(self.export_lookup(f, b.imported))
            if found:
                return found, True
            if fam == "python":
                sub = self._py_resolve(path, f"{b.module}.{b.imported}" if not b.module.endswith(".") else f"{b.module}{b.imported}")
                if sub:
                    return [], True
            return [], True
        if fam == "go":
            same_pkg = [
                i
                for f in self.dir_files.get(_dirname(path), [])
                for i in self._top(f, name)
                if self.symbols[i].lang == "go"
            ]
            if same_pkg:
                return same_pkg, True
        for b in self.wildcards_by_file.get(path, []):
            for f in self.resolve_module(path, b) or []:
                found = self.export_lookup(f, name)
                if found:
                    return found, True
        if fam == "rust":
            crate = self._crate_dir(path)
            cands = [
                i
                for i in self.by_name.get(name, [])
                if self.symbols[i].lang == "rust"
                and self.symbols[i].kind not in _NOT_REFERENCEABLE and self.symbols[i].kind != "method"
                and self._crate_dir(self.symbols[i].path) == crate
            ]
            if len(cands) > 1:
                same_dir = [i for i in cands if _dirname(self.symbols[i].path) == _dirname(path)]
                cands = same_dir or cands
            if 0 < len(cands) <= _UNKNOWN_RECEIVER_LIMIT:
                return cands, True
        return [], False

    def _methods_of(self, type_ids: list[str], name: str, depth: int = 0) -> list[str]:
        if depth > 4:
            return []
        found: list[str] = []
        for tid in type_ids:
            t = self.symbols.get(tid)
            if t is None:
                continue
            key = self._type_key(t)
            found.extend(self.methods_by_key.get(key, {}).get(name, []))
            if t.kind in ("trait",):
                found.extend(self.methods_by_key.get(t.id, {}).get(name, []))
        if found:
            return found
        # Base classes / implemented traits.
        for tid in type_ids:
            t = self.symbols.get(tid)
            if t is None:
                continue
            bases = list(t.bases)
            if FAMILY[t.lang] == "rust":
                for impl_id in self.impls_by_key.get(self._type_key(t), []):
                    bases.extend(b for b in self.symbols[impl_id].bases if b)
            for base in bases:
                base_ids, _ = self.resolve_name(t.path, base)
                base_ids = [b for b in base_ids if self.symbols[b].kind in TYPE_KINDS]
                trait_methods = [
                    m for b in base_ids for m in self.symbols[b].children if self.symbols[m].name == name
                ]
                found.extend(trait_methods)
                if not trait_methods:
                    found.extend(self._methods_of(base_ids, name, depth + 1))
        return found

    def _owner_types(self, sym: Symbol) -> list[str]:
        if sym.parent:
            parent = self.symbols.get(sym.parent)
            if parent is not None and parent.kind in TYPE_KINDS:
                return [parent.id]
        if sym.owner:
            ids, _ = self.resolve_name(sym.path, sym.owner)
            return [i for i in ids if self.symbols[i].kind in TYPE_KINDS]
        return []

    def _unknown_receiver(self, sym: Symbol, name: str) -> list[tuple[str, float]]:
        if not self._ref_is_call or name.lower() in _UBIQUITOUS_METHODS:
            return []
        cands = self.methods_by_name.get(FAMILY[sym.lang], {}).get(name, [])
        if 0 < len(cands) <= _UNKNOWN_RECEIVER_LIMIT:
            conf = 0.7 if len(cands) == 1 else 0.5
            return [(c, conf) for c in cands]
        return []

    def _field_chain(self, types: list[str], fields: list[str]) -> list[str] | None:
        """Follow ``.a.b`` through declared field types. ``None`` = unknown field."""
        for fname in fields:
            nxt: list[str] = []
            known = False
            for tid in types:
                t = self.symbols[tid]
                ftype = t.field_types.get(fname)
                if ftype is None:
                    for base in t.bases:
                        for bid in self.resolve_name(t.path, base)[0]:
                            ftype = self.symbols[bid].field_types.get(fname)
                            if ftype is not None:
                                t = self.symbols[bid]
                                break
                        if ftype is not None:
                            break
                if ftype is None:
                    continue
                known = True
                nxt.extend(self._resolve_type_expr(t, ftype))
            if not known:
                return None
            types = nxt
            if not types:
                return []
        return types

    def _members_of_types(self, sym: Symbol, types: list[str], name: str) -> list[tuple[str, float]]:
        found = self._methods_of(types, name)
        if found:
            return [(m, 1.0) for m in found]
        fields = [c for t in types for c in self.symbols[t].children if self.symbols[c].name == name]
        return [(c, 1.0) for c in fields]

    def resolve_ref(self, sym: Symbol, name: str, receiver: str | None, call: bool = True) -> list[tuple[str, float]]:
        self._ref_is_call = call
        path = sym.path
        if receiver is None:
            ids, _ = self.resolve_name(path, name)
            out = [(i, 1.0) for i in ids]
            # Instantiation pulls in the constructor too.
            for i in ids:
                target = self.symbols[i]
                if target.kind == "class":
                    for ctor in ("__init__", "constructor"):
                        out.extend((m, 1.0) for m in self.methods_by_key.get(target.id, {}).get(ctor, []))
            return out
        fam = FAMILY[sym.lang]
        if receiver in ("self", "this", "Self", "cls") or receiver in sym.self_names:
            owners = self._owner_types(sym)
            if fam in ("go", "rust") and not owners and sym.owner:
                key = self._type_key_parts(sym.lang, path, sym.owner)
                return [(m, 1.0) for m in self.methods_by_key.get(key, {}).get(name, [])]
            if fam == "rust" and sym.owner:
                key = self._type_key_parts(sym.lang, path, sym.owner)
                direct = self.methods_by_key.get(key, {}).get(name, [])
                if direct:
                    return [(m, 1.0) for m in direct]
            found = self._methods_of(owners, name)
            if found:
                return [(m, 1.0) for m in found]
            if fam == "rust" and receiver == "Self":
                consts = [c for o in owners for c in self.symbols[o].children if self.symbols[c].name == name]
                return [(c, 1.0) for c in consts]
            return []
        if receiver == "super":
            owners = self._owner_types(sym)
            bases: list[str] = []
            for o in owners:
                for b in self.symbols[o].bases:
                    bases.extend(i for i in self.resolve_name(self.symbols[o].path, b)[0] if self.symbols[i].kind in TYPE_KINDS)
            return [(m, 1.0) for m in self._methods_of(bases, name)]
        if receiver == "?":
            return self._unknown_receiver(sym, name)
        if receiver.startswith("<"):
            type_expr, _, rest = receiver[1:].partition(">")
            types = self._resolve_type_expr(sym, type_expr)
            if not types:
                return self._unknown_receiver(sym, name)
            if rest:
                chain = self._field_chain(types, rest.lstrip(".").split("."))
                if chain is None:
                    return self._unknown_receiver(sym, name)
                types = chain
            return self._members_of_types(sym, types, name)
        head, _, rest = receiver.partition(".")
        if rest and (head in ("self", "this", "Self", "cls") or head in sym.self_names):
            owners = self._owner_types(sym)
            if not owners and sym.owner:
                owners = [i for i in self.resolve_name(sym.path, sym.owner)[0] if self.symbols[i].kind in TYPE_KINDS]
            chain = self._field_chain(owners, rest.split(".")) if owners else None
            if chain is None:
                return self._unknown_receiver(sym, name)
            return self._members_of_types(sym, chain, name)

        # Named receiver: module alias, type name, or value.
        bindings = self.imports_by_file.get(path, {}).get(receiver, [])
        if not bindings and fam == "go":
            bindings = self._go_alias(path, receiver)
        for b in bindings:
            files = self.resolve_module(path, b)
            if files is None:
                if fam == "rust" and b.imported:
                    files = self._rust_resolve(path, f"{b.module}::{b.imported}")
                if files is None:
                    return []
            if b.imported is None:
                found = [i for f in files for i in self.export_lookup(f, name)]
                return [(i, 1.0) for i in found]
            targets = [i for f in files for i in self.export_lookup(f, b.imported)]
            if not targets:
                sub = None
                if fam == "python":
                    sub = self._py_resolve(path, f"{b.module}.{b.imported}" if not b.module.endswith(".") else f"{b.module}{b.imported}")
                elif fam == "rust":
                    sub = self._rust_resolve(path, f"{b.module}::{b.imported}")
                if sub:
                    return [(i, 1.0) for f in sub for i in self.export_lookup(f, name)]
                return []
            return self._member_of_targets(sym, targets, name)
        head = receiver.split(".", 1)[0]
        if "." in receiver:
            # ``a.b.c.func`` where ``a.b.c`` was imported as a module (Python).
            return []
        ids, known = self.resolve_name(path, head)
        if ids:
            return self._member_of_targets(sym, ids, name)
        if fam == "rust":
            crate = self._crate_dir(path)
            files = [f for f in self.rust_stems.get(receiver, []) if self._crate_dir(f) == crate]
            found = [i for f in files for i in self.export_lookup(f, name)]
            if found:
                return [(i, 1.0) for i in found]
        return []

    def _resolve_type_expr(self, sym: Symbol, expr: str) -> list[str]:
        """Resolve a type name such as ``Gateway`` or ``ledger.Ledger`` to type symbols."""
        if "." in expr:
            qual, _, last = expr.rpartition(".")
            saved = getattr(self, "_ref_is_call", True)
            ids = [t for t, _ in self.resolve_ref(sym, last, qual, False)]
            self._ref_is_call = saved
        else:
            ids, _ = self.resolve_name(sym.path, expr)
        return [i for i in ids if self.symbols[i].kind in TYPE_KINDS]

    def _member_of_targets(self, sym: Symbol, targets: list[str], name: str) -> list[tuple[str, float]]:
        types = [t for t in targets if self.symbols[t].kind in TYPE_KINDS]
        modules = [t for t in targets if self.symbols[t].kind == "module"]
        out: list[tuple[str, float]] = []
        if types:
            out.extend((m, 1.0) for m in self._methods_of(types, name))
            for t in types:
                out.extend((c, 1.0) for c in self.symbols[t].children if self.symbols[c].name == name and (c, 1.0) not in out)
        for m in modules:
            out.extend((c, 1.0) for c in self.symbols[m].children if self.symbols[c].name == name)
        if not out and any(self.symbols[t].kind in VALUE_KINDS for t in targets):
            return self._unknown_receiver(sym, name)
        return out

    def _go_alias(self, path: str, receiver: str) -> list[ImportBinding]:
        """Go imports whose actual package name (not the last path segment) is ``receiver``."""
        out: list[ImportBinding] = []
        for bindings in self.imports_by_file.get(path, {}).values():
            for b in bindings:
                files = self._go_resolve(b.module)
                if files and self.go_pkg_names.get(_dirname(files[0])) == receiver:
                    out.append(b)
        return out

    def _resolve_edges(self) -> None:
        out: dict[str, dict[str, Edge]] = defaultdict(dict)
        for sym in self.symbols.values():
            if sym.kind == "impl":
                # The impl header references its type and trait; attach those
                # edges to every method so methods pull their type in.
                continue
            targets: list[tuple[str, float, int]] = []
            for ref in sym.refs:
                for tid, conf in self.resolve_ref(sym, ref.name, ref.receiver, ref.call):
                    targets.append((tid, conf, ref.line))
            if sym.kind == "method" and sym.owner:
                parent = self.symbols.get(sym.parent) if sym.parent else None
                if parent is None or parent.kind == "impl":
                    for tid in self.resolve_name(sym.path, sym.owner)[0]:
                        if self.symbols[tid].kind in TYPE_KINDS:
                            targets.append((tid, 1.0, sym.decl_line))
                if parent is not None and parent.kind == "impl":
                    for trait in parent.bases:
                        for tid in self.resolve_name(sym.path, trait)[0]:
                            if self.symbols[tid].kind in TYPE_KINDS:
                                targets.append((tid, 1.0, parent.decl_line))
            edges = out[sym.id]
            for tid, conf, line in targets:
                if tid == sym.id:
                    continue
                target = self.symbols.get(tid)
                if target is None or target.kind in _NOT_REFERENCEABLE:
                    continue
                kind = edge_kind_for(target.kind)
                if kind == "ref":
                    continue
                prev = edges.get(tid)
                if prev is None or conf > prev.confidence:
                    edges[tid] = Edge(sym.id, tid, kind, conf, line)
        self.edges_out = {k: list(v.values()) for k, v in out.items() if v}
        self.edges_in = defaultdict(list)
        for edges in self.edges_out.values():
            for e in edges:
                self.edges_in[e.target].append(e)
        self.edges_in = dict(self.edges_in)

    # ================================================================ access
    def file_lines(self, path: str) -> list[str]:
        fx = self.files[path]
        cached = self._text_cache.get(path)
        if cached is not None and cached[0] == fx.mtime_ns:
            return cached[1]
        try:
            text = (self.root / path).read_bytes().decode("utf-8", "replace")
        except OSError:
            text = ""
        lines = text.split("\n")
        self._text_cache[path] = (fx.mtime_ns, lines)
        return lines

    def symbol_text(self, sym: Symbol) -> str:
        return "\n".join(self.file_lines(sym.path)[sym.start_line - 1 : sym.end_line])

    def is_test(self, sym: Symbol) -> bool:
        if is_test_path(sym.path):
            return True
        # Rust ``#[cfg(test)] mod tests { ... }`` and similar inline test modules.
        return sym.qualname.startswith(("tests.", "test.")) or ".tests." in sym.qualname

    def symbols_at(self, path: str, line: int) -> list[Symbol]:
        """Symbols enclosing ``line``, innermost first."""
        hits = [
            self.symbols[i]
            for i in self.by_file.get(path, [])
            if self.symbols[i].start_line <= line <= self.symbols[i].end_line
        ]
        hits.sort(key=lambda s: (s.end_line - s.start_line, s.kind == "impl"))
        return hits

    @property
    def total_tokens(self) -> int:
        return sum(f.tokens for f in self.files.values())

    def edge_count(self) -> int:
        return sum(len(v) for v in self.edges_out.values())

    def stats(self) -> dict:
        langs: dict[str, dict[str, int]] = defaultdict(lambda: {"files": 0, "symbols": 0, "tokens": 0, "lines": 0})
        for fx in self.files.values():
            entry = langs[fx.lang]
            entry["files"] += 1
            entry["symbols"] += len(fx.symbols)
            entry["tokens"] += fx.tokens
            entry["lines"] += fx.line_count
        kinds: dict[str, int] = defaultdict(int)
        for s in self.symbols.values():
            kinds[s.kind] += 1
        edge_kinds: dict[str, int] = defaultdict(int)
        for edges in self.edges_out.values():
            for e in edges:
                edge_kinds[e.kind] += 1
        return {
            "root": str(self.root),
            "files": len(self.files),
            "symbols": len(self.symbols),
            "edges": self.edge_count(),
            "tokens": self.total_tokens,
            "lines": sum(f.line_count for f in self.files.values()),
            "tokenizer": self.counter.name,
            "tokenizer_exact": self.counter.exact,
            "languages": dict(sorted(langs.items())),
            "symbol_kinds": dict(sorted(kinds.items())),
            "edge_kinds": dict(sorted(edge_kinds.items())),
            "parse_errors": sum(f.parse_errors for f in self.files.values()),
            "timing": {
                "scan_parse_seconds": round(self.build_seconds, 4),
                "resolve_seconds": round(self.resolve_seconds, 4),
                "parsed_files": self.parsed_files,
                "cached_files": self.cached_files,
            },
            "generation": self.generation,
        }

    # ================================================================ search
    def search(self, query: str, limit: int = 20, kinds: set[str] | None = None) -> list[tuple[float, Symbol]]:
        q = query.strip()
        if not q:
            return []
        ql = q.lower()
        scored: list[tuple[float, Symbol]] = []
        for sym in self.symbols.values():
            if sym.kind in (BLOCK_KIND, "impl"):
                continue
            if kinds and sym.kind not in kinds:
                continue
            score = _fuzzy_score(ql, q, sym)
            if score > 0:
                scored.append((score, sym))
        scored.sort(key=lambda t: (-t[0], len(t[1].qualname), t[1].path, t[1].start_line))
        return scored[:limit]


def _fuzzy_score(ql: str, q: str, sym: Symbol) -> float:
    name = sym.name
    nl = name.lower()
    qual = sym.qualname.lower()
    if name == q or sym.qualname == q:
        base = 1000.0
    elif nl == ql or qual == ql:
        base = 900.0
    elif qual.endswith("." + ql) or nl.startswith(ql):
        base = 700.0 + 50.0 * len(ql) / max(len(nl), 1)
    elif ql in nl:
        base = 500.0 + 50.0 * len(ql) / max(len(nl), 1)
    elif ql in qual:
        base = 400.0
    elif ql in sym.path.lower():
        base = 150.0
    else:
        sub = _subsequence_score(ql, name)
        if sub <= 0:
            return 0.0
        base = 100.0 + sub
    if sym.kind in CALLABLE_KINDS:
        base += 5
    elif sym.kind in TYPE_KINDS:
        base += 4
    if "test" in sym.path.lower():
        base -= 3
    return base


def _subsequence_score(ql: str, name: str) -> float:
    """fzf-style subsequence match with bonuses for word boundaries."""
    i = 0
    score = 0.0
    prev_match = -2
    for j, ch in enumerate(name):
        if i < len(ql) and ch.lower() == ql[i]:
            bonus = 1.0
            if j == 0 or name[j - 1] in "_-." or (ch.isupper() and not name[j - 1].isupper()):
                bonus += 3.0
            if prev_match == j - 1:
                bonus += 2.0
            score += bonus
            prev_match = j
            i += 1
    if i < len(ql):
        return 0.0
    return score * 10.0 / max(len(name), 1) * len(ql)
