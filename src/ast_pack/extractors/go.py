"""Go extractor."""

from __future__ import annotations

from tree_sitter import Node

from ..models import ImportBinding, Ref
from .base import BaseExtractor, is_call_target, main_type


class GoExtractor(BaseExtractor):
    comment_types = frozenset({"comment"})

    def extract(self, root: Node) -> None:
        for child in root.named_children:
            t = child.type
            if t == "package_clause":
                ident = child.named_children[0] if child.named_children else None
                self.package = self.text(ident)
                self.always_keep.append(self.start_line(child))
            elif t == "import_declaration":
                self._imports(child)
            elif t == "function_declaration":
                self._function(child)
            elif t == "method_declaration":
                self._method(child)
            elif t == "type_declaration":
                self._types(child)
            elif t in ("const_declaration", "var_declaration"):
                self._values(child, "const" if t == "const_declaration" else "variable")

    # --------------------------------------------------------------- imports
    def _imports(self, decl: Node) -> None:
        specs: list[Node] = []
        grouped = False
        for c in decl.named_children:
            if c.type == "import_spec":
                specs.append(c)
            elif c.type == "import_spec_list":
                grouped = True
                specs.extend(s for s in c.named_children if s.type == "import_spec")
        wrapper = (self.start_line(decl), self.end_line(decl)) if grouped else ()
        for spec in specs:
            path_node = spec.child_by_field_name("path")
            module = self.text(path_node).strip('"`')
            name_node = spec.child_by_field_name("name")
            if name_node is not None:
                alias = self.text(name_node)
                if alias == "_":
                    continue
            else:
                alias = module.rstrip("/").rsplit("/", 1)[-1]
            s, e = (self.start_line(spec), self.end_line(spec)) if grouped else (self.start_line(decl), self.end_line(decl))
            self.imports.append(
                ImportBinding(
                    local=alias,
                    module=module,
                    imported=None,
                    start_line=s,
                    end_line=e,
                    wildcard=alias == ".",
                    wrapper_lines=wrapper,
                )
            )

    # ---------------------------------------------------------- definitions
    def _function(self, node: Node) -> None:
        name = self.text(node.child_by_field_name("name"))
        body = node.child_by_field_name("body")
        sym = self.add_symbol(node, name, "function", body=body, start_line=self.leading_start(node),
                              exported=name[:1].isupper())
        self._refs(sym, node)

    def _method(self, node: Node) -> None:
        name = self.text(node.child_by_field_name("name"))
        body = node.child_by_field_name("body")
        receiver = node.child_by_field_name("receiver")
        recv_name = ""
        recv_type = ""
        if receiver is not None:
            for p in receiver.named_children:
                if p.type != "parameter_declaration":
                    continue
                n = p.child_by_field_name("name")
                if n is not None:
                    recv_name = self.text(n)
                recv_type = self._base_type(p.child_by_field_name("type"))
                break
        sym = self.add_symbol(
            node,
            name,
            "method",
            qual_prefix=recv_type,
            body=body,
            start_line=self.leading_start(node),
            owner=recv_type or None,
            self_names=(recv_name,) if recv_name else (),
            exported=name[:1].isupper(),
        )
        self._refs(sym, node)

    def _base_type(self, node: Node | None) -> str:
        while node is not None and node.type in ("pointer_type", "generic_type", "parenthesized_type"):
            if node.type == "generic_type":
                node = node.child_by_field_name("type")
            else:
                node = node.named_children[0] if node.named_children else None
        return self.text(node) if node is not None else ""

    def _refs(self, sym, node: Node) -> None:
        roots = [c for c in (node.child_by_field_name(f) for f in ("receiver", "type_parameters", "parameters", "result", "body")) if c is not None]
        sig = [c for c in (node.child_by_field_name(f) for f in ("type_parameters", "parameters", "result")) if c is not None]
        self.set_refs(sym, roots, sig_roots=sig)

    def _types(self, decl: Node) -> None:
        start = self.leading_start(decl)
        for spec in decl.named_children:
            if spec.type not in ("type_spec", "type_alias"):
                continue
            name = self.text(spec.child_by_field_name("name"))
            tnode = spec.child_by_field_name("type")
            kind = "type"
            body = None
            if tnode is not None and tnode.type == "struct_type":
                kind = "struct"
                body = next((c for c in tnode.named_children if c.type == "field_declaration_list"), None)
            elif tnode is not None and tnode.type == "interface_type":
                kind = "interface"
                body = tnode
            sym = self.add_symbol(decl, name, kind, body=body, start_line=start, decl_node=spec,
                                  exported=name[:1].isupper())
            roots = [c for c in (spec.child_by_field_name("type_parameters"), tnode) if c is not None]
            self.set_refs(sym, roots, sig_roots=roots)
            if kind == "struct" and body is not None:
                for fd in body.named_children:
                    if fd.type != "field_declaration":
                        continue
                    ftype = fd.child_by_field_name("type")
                    t = main_type(self.text(ftype).lstrip("*")) if ftype is not None else None
                    names = [self.text(c) for i, c in enumerate(fd.children) if fd.field_name_for_child(i) == "name"]
                    if not t:
                        continue
                    if not names:  # embedded field: its type name is the field name
                        names = [t.rsplit(".", 1)[-1]]
                    for n in names:
                        sym.field_types[n] = t

    def _values(self, decl: Node, kind: str) -> None:
        start = self.leading_start(decl)
        specs: list[Node] = []
        for c in decl.named_children:
            if c.type in ("const_spec", "var_spec"):
                specs.append(c)
            elif c.type in ("var_spec_list", "const_spec_list"):
                specs.extend(s for s in c.named_children if s.type in ("const_spec", "var_spec"))
        for spec in specs:
            names = [self.text(c) for i, c in enumerate(spec.children) if spec.field_name_for_child(i) == "name"]
            roots = [c for i, c in enumerate(spec.children) if c.is_named and spec.field_name_for_child(i) in ("type", "value")]
            for name in names:
                if name == "_":
                    continue
                sym = self.add_symbol(decl, name, kind, start_line=start, decl_node=spec, exported=name[:1].isupper())
                self.set_refs(sym, roots)

    # ------------------------------------------------------------ references
    def _receiver(self, node: Node | None) -> str:
        if node is None:
            return "?"
        if node.type == "identifier":
            return self.text(node)
        if node.type == "selector_expression":
            parts: list[str] = []
            cur: Node | None = node
            while cur is not None and cur.type == "selector_expression":
                parts.append(self.text(cur.child_by_field_name("field")))
                cur = cur.child_by_field_name("operand")
            if cur is not None and cur.type == "identifier":
                parts.append(self.text(cur))
                return ".".join(reversed(parts))
        return "?"

    def visit(self, node: Node, out: list[Ref]) -> list[Node] | None:
        t = node.type
        if t in ("identifier", "type_identifier"):
            out.append(Ref(self.text(node), None, self.start_line(node)))
            return []
        if t in ("field_identifier", "package_identifier", "label_name"):
            return []
        if t == "selector_expression":
            operand = node.child_by_field_name("operand")
            field = node.child_by_field_name("field")
            if field is not None:
                out.append(Ref(self.text(field), self._receiver(operand), self.start_line(field), is_call_target(node)))
            return [operand] if operand is not None else []
        if t == "qualified_type":
            pkg = node.child_by_field_name("package")
            name = node.child_by_field_name("name")
            if name is not None:
                out.append(Ref(self.text(name), self.text(pkg) if pkg is not None else "?", self.start_line(name)))
            return []
        if t == "keyed_element":
            kids = node.named_children
            if len(kids) == 2:
                key = kids[0]
                # ``Field: value`` in struct literals: the key is a field name.
                inner = key.named_children[0] if key.type == "literal_element" and key.named_children else key
                if inner.type in ("identifier", "field_identifier"):
                    return [kids[1]]
            return None
        if t in ("interpreted_string_literal", "raw_string_literal", "rune_literal", "int_literal", "float_literal"):
            return []
        return None

    def type_hints(self, node: Node, out: dict[str, str]) -> None:
        t = node.type
        if t in ("parameter_declaration", "var_spec"):
            tnode = node.child_by_field_name("type")
            if tnode is None:
                return
            typ = main_type(self.text(tnode).lstrip("*"))
            if not typ:
                return
            for i, c in enumerate(node.children):
                if node.field_name_for_child(i) == "name":
                    out[self.text(c)] = typ
        elif t == "short_var_declaration":
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            if left is None or right is None:
                return
            lefts = [c for c in left.named_children] if left.type == "expression_list" else [left]
            rights = [c for c in right.named_children] if right.type == "expression_list" else [right]
            if len(rights) == 1 and rights[0].type == "type_assertion_expression" and lefts and lefts[0].type == "identifier":
                tnode = rights[0].child_by_field_name("type")
                typ = main_type(self.text(tnode).lstrip("*")) if tnode is not None else None
                if typ:
                    out[self.text(lefts[0])] = typ
                return
            for ln, rn in zip(lefts, rights):
                if ln.type != "identifier":
                    continue
                if rn.type == "unary_expression" and rn.named_children:
                    rn = rn.named_children[-1]
                if rn.type == "composite_literal":
                    tnode = rn.child_by_field_name("type")
                    typ = main_type(self.text(tnode)) if tnode is not None else None
                    if typ:
                        out[self.text(ln)] = typ

    def bindings(self, node: Node, out: set[str]) -> None:
        t = node.type
        if t in ("parameter_declaration", "variadic_parameter_declaration", "const_spec", "var_spec"):
            for i, c in enumerate(node.children):
                if node.field_name_for_child(i) == "name":
                    out.add(self.text(c))
        elif t in ("short_var_declaration", "range_clause"):
            left = node.child_by_field_name("left")
            if left is not None:
                for c in [left, *left.named_children]:
                    if c.type == "identifier":
                        out.add(self.text(c))
        elif t == "type_parameter_declaration":
            for i, c in enumerate(node.children):
                if node.field_name_for_child(i) == "name":
                    out.add(self.text(c))
