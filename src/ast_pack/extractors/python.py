"""Python extractor."""

from __future__ import annotations

from tree_sitter import Node

from ..models import Ref, Symbol
from .base import BaseExtractor, is_call_target, main_type

_PATTERN_CONTAINERS = frozenset(
    {"pattern_list", "tuple_pattern", "list_pattern", "tuple", "list", "list_splat_pattern", "parenthesized_expression"}
)
_IMPORT_TYPES = frozenset({"import_statement", "import_from_statement", "future_import_statement"})
_DEF_TYPES = frozenset({"function_definition", "class_definition", "decorated_definition"})


def _pattern_names(node: Node | None, out: set[str], src: bytes) -> None:
    if node is None:
        return
    if node.type == "identifier":
        out.add(src[node.start_byte : node.end_byte].decode("utf-8", "replace"))
    elif node.type in _PATTERN_CONTAINERS:
        for child in node.named_children:
            _pattern_names(child, out, src)


class PythonExtractor(BaseExtractor):
    comment_types = frozenset({"comment"})

    # ----------------------------------------------------------- top level
    def extract(self, root: Node) -> None:
        self._method_nodes: dict[str, Node] = {}
        pending_block: list[Node] = []
        for child in root.named_children:
            if child.type == "comment":
                continue
            if (
                child.type == "expression_statement"
                and child.named_child_count == 1
                and child.named_children[0].type == "string"
            ):
                continue  # module / attribute docstring
            if self._handle_definition(child, None, ""):
                self._flush_block(pending_block)
                continue
            if child.type in _IMPORT_TYPES:
                self._flush_block(pending_block)
                self._imports(child, self.start_line(child), self.end_line(child))
                continue
            if child.type == "expression_statement" and self._assignment(child):
                self._flush_block(pending_block)
                continue
            nested_imports = [n for n in self._find_nested_imports(child)]
            if nested_imports:
                self._flush_block(pending_block)
                for imp in nested_imports:
                    self._imports(imp, self.start_line(child), self.end_line(child))
                if all(self._is_import_only(c) for c in self._statements(child)):
                    continue
            pending_block.append(child)
        self._flush_block(pending_block)

    def _statements(self, node: Node) -> list[Node]:
        out: list[Node] = []
        for child in node.named_children:
            if child.type == "block":
                out.extend(c for c in child.named_children if c.type != "comment")
            elif child.type in ("else_clause", "elif_clause", "except_clause", "finally_clause"):
                out.extend(self._statements(child))
        return out

    @staticmethod
    def _is_import_only(node: Node) -> bool:
        return node.type in _IMPORT_TYPES or node.type == "pass_statement"

    def _find_nested_imports(self, node: Node) -> list[Node]:
        if node.type not in ("if_statement", "try_statement", "with_statement"):
            return []
        found: list[Node] = []
        stack = [node]
        while stack:
            cur = stack.pop()
            for child in cur.named_children:
                if child.type in _IMPORT_TYPES:
                    found.append(child)
                elif child.type not in _DEF_TYPES:
                    stack.append(child)
        return found

    def _flush_block(self, nodes: list[Node]) -> None:
        if not nodes:
            return
        first, last = nodes[0], nodes[-1]
        name = f"<toplevel@L{self.start_line(first)}>"
        if first.type == "if_statement" and "__main__" in self.text(first.child_by_field_name("condition")):
            name = "__main__"
        sym = Symbol(
            id=self.make_id(name, self.start_line(first)),
            name=name,
            qualname=name,
            kind="block",
            lang=self.lang,
            path=self.path,
            start_line=self.start_line(first),
            end_line=self.end_line(last),
            decl_line=self.start_line(first),
            signature=self.text(first).split("\n", 1)[0][:240],
        )
        self.set_refs(sym, nodes)
        self.symbols.append(sym)
        nodes.clear()

    # ---------------------------------------------------------- definitions
    def _handle_definition(self, node: Node, parent: Symbol | None, prefix: str) -> bool:
        outer = node
        decorators: list[Node] = []
        if node.type == "decorated_definition":
            decorators = [c for c in node.named_children if c.type == "decorator"]
            node = node.child_by_field_name("definition")
            if node is None:
                return False
        if node.type == "function_definition":
            self._function(node, outer, decorators, parent, prefix)
            return True
        if node.type == "class_definition":
            self._class(node, outer, decorators, parent, prefix)
            return True
        return False

    def _function(self, node: Node, outer: Node, decorators: list[Node], parent: Symbol | None, prefix: str) -> None:
        name = self.text(node.child_by_field_name("name"))
        body = node.child_by_field_name("body")
        params = node.child_by_field_name("parameters")
        self_names: tuple[str, ...] = ()
        if parent is not None and parent.kind == "class" and params is not None:
            for p in params.named_children:
                if p.type == "identifier":
                    self_names = (self.text(p),)
                    break
                if p.type in ("typed_parameter", "default_parameter", "typed_default_parameter"):
                    first = p.child_by_field_name("name") or (p.named_children[0] if p.named_children else None)
                    if first is not None and first.type == "identifier":
                        self_names = (self.text(first),)
                    break
                break
        sym = self.add_symbol(
            outer,
            name,
            "method" if parent is not None and parent.kind == "class" else "function",
            qual_prefix=prefix,
            parent=parent,
            body=body,
            start_line=self.leading_start(outer),
            owner=parent.name if parent is not None and parent.kind == "class" else None,
            self_names=self_names,
            exported=not name.startswith("_") or (name.startswith("__") and name.endswith("__")),
            decl_node=node,
        )
        sym.docstring_end_line = self._docstring_end(body)
        self._method_nodes[sym.id] = node
        roots: list[Node] = [*decorators]
        for field in ("parameters", "return_type", "body"):
            child = node.child_by_field_name(field)
            if child is not None:
                roots.append(child)
        sig_roots = [c for c in (params, node.child_by_field_name("return_type")) if c is not None]
        self.set_refs(sym, roots, sig_roots=sig_roots)

    def _class(self, node: Node, outer: Node, decorators: list[Node], parent: Symbol | None, prefix: str) -> None:
        name = self.text(node.child_by_field_name("name"))
        body = node.child_by_field_name("body")
        supers = node.child_by_field_name("superclasses")
        bases: list[str] = []
        if supers is not None:
            for arg in supers.named_children:
                if arg.type in ("identifier", "attribute"):
                    bases.append(self.text(arg).rsplit(".", 1)[-1])
        sym = self.add_symbol(
            outer,
            name,
            "class",
            qual_prefix=prefix,
            parent=parent,
            body=body,
            start_line=self.leading_start(outer),
            bases=tuple(bases),
            exported=not name.startswith("_"),
            decl_node=node,
        )
        sym.docstring_end_line = self._docstring_end(body)
        member_nodes: set[int] = set()
        qual = sym.qualname
        if body is not None:
            for child in body.named_children:
                if child.type in _DEF_TYPES and self._handle_definition(child, sym, qual):
                    member_nodes.add(child.id)
        roots: list[Node] = [*decorators]
        if supers is not None:
            roots.append(supers)
        if body is not None:
            roots.extend(c for c in body.named_children if c.id not in member_nodes)
            self._field_types(sym, body)
        self.set_refs(sym, roots, sig_roots=[supers] if supers is not None else ())

    def _field_types(self, sym: Symbol, body: Node) -> None:
        """``x: Foo`` class attributes and ``self.x = Foo(...)`` / ``self.x: Foo`` in methods."""
        for stmt in body.named_children:
            if stmt.type == "expression_statement" and stmt.named_children:
                a = stmt.named_children[0]
                if a.type == "assignment":
                    left, typ = a.child_by_field_name("left"), a.child_by_field_name("type")
                    if left is not None and left.type == "identifier" and typ is not None:
                        t = main_type(self.text(typ))
                        if t:
                            sym.field_types[self.text(left)] = t
        for cid in sym.children:
            method = next((s for s in self.symbols if s.id == cid), None)
            if method is None or method.kind != "method" or not method.self_names:
                continue
            self_name = method.self_names[0]
            node = self._method_nodes.get(cid)
            if node is None:
                continue
            params: dict[str, str] = {}
            stack = [node]
            while stack:
                cur = stack.pop()
                self.type_hints(cur, params)
                if cur.type == "assignment":
                    left = cur.child_by_field_name("left")
                    if left is None or left.type != "attribute":
                        pass
                    else:
                        obj = left.child_by_field_name("object")
                        attr = left.child_by_field_name("attribute")
                        if obj is not None and attr is not None and self.text(obj) == self_name:
                            fname = self.text(attr)
                            t = None
                            typ = cur.child_by_field_name("type")
                            right = cur.child_by_field_name("right")
                            if typ is not None:
                                t = main_type(self.text(typ))
                            elif right is not None and right.type == "call":
                                fn = right.child_by_field_name("function")
                                if fn is not None and fn.type in ("identifier", "attribute") and self.text(fn).rsplit(".", 1)[-1][:1].isupper():
                                    t = self.text(fn)
                            elif right is not None and right.type == "identifier":
                                t = params.get(self.text(right))
                            if t and fname not in sym.field_types:
                                sym.field_types[fname] = t
                stack.extend(cur.named_children)

    def _docstring_end(self, body: Node | None) -> int | None:
        if body is None or not body.named_children:
            return None
        first = body.named_children[0]
        if first.type == "expression_statement" and first.named_children and first.named_children[0].type == "string":
            return self.end_line(first)
        return None

    def _assignment(self, stmt: Node) -> bool:
        if not stmt.named_children:
            return False
        assign = stmt.named_children[0]
        if assign.type not in ("assignment", "augmented_assignment"):
            return False
        names: set[str] = set()
        _pattern_names(assign.child_by_field_name("left"), names, self.src)
        if not names:
            return False
        right = assign.child_by_field_name("right")
        type_node = assign.child_by_field_name("type")
        for name in sorted(names, key=lambda n: self.text(stmt).find(n)):
            kind = "const" if name.isupper() and len(name) > 1 else "variable"
            sym = self.add_symbol(
                stmt,
                name,
                kind,
                start_line=self.leading_start(stmt),
                exported=not name.startswith("_"),
            )
            sym.signature = self.text(stmt).split("\n", 1)[0][:240]
            self.set_refs(sym, [n for n in (type_node, right) if n is not None], extra_local=names - {name})
        return True

    # ---------------------------------------------------------------- imports
    def _imports(self, node: Node, start: int, end: int) -> None:
        if node.type == "import_statement":
            for child in node.named_children:
                if child.type == "dotted_name":
                    mod = self.text(child)
                    self.imports.append(self._binding(mod, mod, None, start, end))
                    if "." in mod:
                        self.imports.append(self._binding(mod.split(".", 1)[0], mod.split(".", 1)[0], None, start, end))
                elif child.type == "aliased_import":
                    mod = self.text(child.child_by_field_name("name"))
                    alias = self.text(child.child_by_field_name("alias"))
                    self.imports.append(self._binding(alias, mod, None, start, end))
        elif node.type == "import_from_statement":
            module_node = node.child_by_field_name("module_name")
            module = self.text(module_node)
            for i, child in enumerate(node.children):
                field = node.field_name_for_child(i)
                if child.type == "wildcard_import":
                    self.imports.append(self._binding("*", module, None, start, end, wildcard=True))
                elif field == "name":
                    if child.type == "aliased_import":
                        orig = self.text(child.child_by_field_name("name"))
                        alias = self.text(child.child_by_field_name("alias"))
                    else:
                        orig = alias = self.text(child)
                    self.imports.append(self._binding(alias, module, orig, start, end))

    @staticmethod
    def _binding(local: str, module: str, imported: str | None, start: int, end: int, wildcard: bool = False):
        from ..models import ImportBinding

        return ImportBinding(local=local, module=module, imported=imported, start_line=start, end_line=end, wildcard=wildcard)

    # ------------------------------------------------------------ references
    def _receiver(self, obj: Node | None) -> str:
        if obj is None:
            return "?"
        if obj.type == "identifier":
            return self.text(obj)
        if obj.type == "attribute":
            parts = []
            cur: Node | None = obj
            while cur is not None and cur.type == "attribute":
                parts.append(self.text(cur.child_by_field_name("attribute")))
                cur = cur.child_by_field_name("object")
            if cur is not None and cur.type == "identifier":
                parts.append(self.text(cur))
                return ".".join(reversed(parts))
            return "?"
        if obj.type == "call":
            fn = obj.child_by_field_name("function")
            if fn is not None and self.text(fn) == "super":
                return "super"
        return "?"

    def visit(self, node: Node, out: list[Ref]) -> list[Node] | None:
        t = node.type
        if t == "identifier":
            out.append(Ref(self.text(node), None, self.start_line(node)))
            return []
        if t == "attribute":
            obj = node.child_by_field_name("object")
            attr = node.child_by_field_name("attribute")
            if attr is not None:
                out.append(Ref(self.text(attr), self._receiver(obj), self.start_line(attr), is_call_target(node)))
            return [obj] if obj is not None else []
        if t == "keyword_argument":
            value = node.child_by_field_name("value")
            return [value] if value is not None else []
        if t in ("function_definition", "class_definition"):
            return [
                c
                for i, c in enumerate(node.children)
                if c.is_named and node.field_name_for_child(i) != "name"
            ]
        if t == "string":
            return [c for c in node.named_children if c.type == "interpolation"]
        if t in _IMPORT_TYPES:
            return []
        return None

    def type_hints(self, node: Node, out: dict[str, str]) -> None:
        t = node.type
        name_node = type_node = None
        if t == "typed_parameter":
            name_node = next((c for c in node.named_children if c.type == "identifier"), None)
            type_node = node.child_by_field_name("type")
        elif t == "typed_default_parameter":
            name_node, type_node = node.child_by_field_name("name"), node.child_by_field_name("type")
        elif t == "assignment":
            left = node.child_by_field_name("left")
            if left is None or left.type != "identifier":
                return
            name_node, type_node = left, node.child_by_field_name("type")
            right = node.child_by_field_name("right")
            if type_node is None and right is not None and right.type == "call":
                fn = right.child_by_field_name("function")
                if fn is not None and fn.type in ("identifier", "attribute") and self.text(fn).rsplit(".", 1)[-1][:1].isupper():
                    out[self.text(left)] = self.text(fn)
                    return
        if name_node is not None and type_node is not None:
            typ = main_type(self.text(type_node))
            if typ:
                out[self.text(name_node)] = typ

    def bindings(self, node: Node, out: set[str]) -> None:
        t = node.type
        src = self.src
        if t in ("parameters", "lambda_parameters"):
            for p in node.named_children:
                if p.type == "identifier":
                    out.add(self.text(p))
                elif p.type in ("default_parameter", "typed_default_parameter"):
                    _pattern_names(p.child_by_field_name("name"), out, src)
                elif p.type in ("typed_parameter", "list_splat_pattern", "dictionary_splat_pattern"):
                    for c in p.named_children:
                        if c.type == "identifier":
                            out.add(self.text(c))
                            break
                        if c.type in ("list_splat_pattern", "dictionary_splat_pattern"):
                            for cc in c.named_children:
                                if cc.type == "identifier":
                                    out.add(self.text(cc))
        elif t in ("assignment", "augmented_assignment"):
            _pattern_names(node.child_by_field_name("left"), out, src)
        elif t in ("for_statement", "for_in_clause"):
            _pattern_names(node.child_by_field_name("left"), out, src)
        elif t == "as_pattern":
            alias = node.child_by_field_name("alias")
            if alias is not None:
                for c in [alias, *alias.named_children]:
                    _pattern_names(c, out, src)
        elif t == "named_expression":
            _pattern_names(node.child_by_field_name("name"), out, src)
        elif t in ("function_definition", "class_definition"):
            _pattern_names(node.child_by_field_name("name"), out, src)
        elif t == "import_statement":
            for c in node.named_children:
                if c.type == "dotted_name":
                    out.add(self.text(c).split(".", 1)[0])
                elif c.type == "aliased_import":
                    out.add(self.text(c.child_by_field_name("alias")))
        elif t == "import_from_statement":
            for i, c in enumerate(node.children):
                if node.field_name_for_child(i) == "name":
                    if c.type == "aliased_import":
                        out.add(self.text(c.child_by_field_name("alias")))
                    else:
                        out.add(self.text(c))
