"""Rust extractor."""

from __future__ import annotations

from tree_sitter import Node

from ..models import ImportBinding, Ref, Symbol
from .base import BaseExtractor, is_call_target, main_type

_SIMPLE_TYPES = {
    "struct_item": "struct",
    "enum_item": "enum",
    "union_item": "union",
    "type_item": "type",
}
_GLUE = ("attribute_item",)


class RustExtractor(BaseExtractor):
    comment_types = frozenset({"line_comment", "block_comment"})

    def extract(self, root: Node) -> None:
        self._items(root.named_children, None, "")

    def _items(self, nodes: list[Node], parent: Symbol | None, prefix: str) -> None:
        for node in nodes:
            t = node.type
            start = self.leading_start(node, _GLUE)
            if t == "use_declaration":
                arg = node.child_by_field_name("argument")
                self._use(arg, "", self.start_line(node), self.end_line(node))
            elif t == "function_item" or t == "function_signature_item":
                self._function(node, parent, prefix, start)
            elif t in _SIMPLE_TYPES:
                name = self.text(node.child_by_field_name("name"))
                body = node.child_by_field_name("body")
                sym = self.add_symbol(node, name, _SIMPLE_TYPES[t], qual_prefix=prefix, parent=parent,
                                      body=body, start_line=start, exported=self._is_pub(node))
                if t == "struct_item" and body is not None and body.type == "field_declaration_list":
                    for fd in body.named_children:
                        if fd.type != "field_declaration":
                            continue
                        fname, ftype = fd.child_by_field_name("name"), fd.child_by_field_name("type")
                        ty = main_type(self.text(ftype).replace("::", ".")) if ftype is not None else None
                        if fname is not None and ty:
                            sym.field_types[self.text(fname)] = ty.rsplit(".", 1)[-1]
                roots = [c for c in (node.child_by_field_name("type_parameters"), body, node.child_by_field_name("type")) if c is not None]
                self.set_refs(sym, roots, sig_roots=roots)
            elif t in ("const_item", "static_item"):
                name = self.text(node.child_by_field_name("name"))
                sym = self.add_symbol(node, name, "const" if t == "const_item" else "static", qual_prefix=prefix,
                                      parent=parent, start_line=start, exported=self._is_pub(node))
                roots = [c for c in (node.child_by_field_name("type"), node.child_by_field_name("value")) if c is not None]
                self.set_refs(sym, roots)
            elif t == "trait_item":
                self._trait(node, parent, prefix, start)
            elif t == "impl_item":
                self._impl(node, parent, start)
            elif t == "mod_item":
                body = node.child_by_field_name("body")
                if body is None:
                    continue
                name = self.text(node.child_by_field_name("name"))
                sym = self.add_symbol(node, name, "module", qual_prefix=prefix, parent=parent, body=body,
                                      start_line=start, exported=self._is_pub(node))
                self._items(body.named_children, sym, sym.qualname)
            elif t == "macro_definition":
                name = self.text(node.child_by_field_name("name"))
                sym = self.add_symbol(node, name, "macro", qual_prefix=prefix, parent=parent, start_line=start)
                self.set_refs(sym, [c for c in node.named_children if c.type == "macro_rule"])

    @staticmethod
    def _is_pub(node: Node) -> bool:
        return any(c.type == "visibility_modifier" for c in node.named_children)

    def _function(self, node: Node, parent: Symbol | None, prefix: str, start: int, owner: str | None = None) -> Symbol:
        name = self.text(node.child_by_field_name("name"))
        body = node.child_by_field_name("body")
        is_method = owner is not None
        sym = self.add_symbol(
            node,
            name,
            "method" if is_method else "function",
            qual_prefix=prefix,
            parent=parent,
            body=body,
            start_line=start,
            owner=owner,
            self_names=("self", "Self") if is_method else (),
            exported=self._is_pub(node) or is_method,
        )
        roots = [c for c in (node.child_by_field_name(f) for f in ("type_parameters", "parameters", "return_type", "body")) if c is not None]
        roots.extend(c for c in node.named_children if c.type == "where_clause")
        sig = [c for c in (node.child_by_field_name(f) for f in ("type_parameters", "parameters", "return_type")) if c is not None]
        self.set_refs(sym, roots, sig_roots=sig)
        return sym

    def _type_name(self, node: Node | None) -> str:
        while node is not None and node.type in ("generic_type", "reference_type", "scoped_type_identifier", "pointer_type"):
            if node.type == "generic_type":
                node = node.child_by_field_name("type")
            elif node.type == "scoped_type_identifier":
                node = node.child_by_field_name("name")
            else:
                node = node.child_by_field_name("type") or (node.named_children[-1] if node.named_children else None)
        return self.text(node) if node is not None else "?"

    def _impl(self, node: Node, parent: Symbol | None, start: int) -> None:
        type_name = self._type_name(node.child_by_field_name("type"))
        trait_node = node.child_by_field_name("trait")
        trait = self._type_name(trait_node) if trait_node is not None else None
        label = f"impl {trait} for {type_name}" if trait else f"impl {type_name}"
        body = node.child_by_field_name("body")
        sym = self.add_symbol(node, label, "impl", parent=parent, body=body, start_line=start,
                              owner=type_name, bases=(trait,) if trait else ())
        members: set[int] = set()
        if body is not None:
            for item in body.named_children:
                if item.type in ("function_item", "function_signature_item"):
                    self._function(item, sym, type_name, self.leading_start(item, _GLUE), owner=type_name)
                    members.add(item.id)
        roots = [c for c in (node.child_by_field_name("type_parameters"), trait_node, node.child_by_field_name("type")) if c is not None]
        if body is not None:
            roots.extend(c for c in body.named_children if c.id not in members)
        self.set_refs(sym, roots, sig_roots=roots)

    def _trait(self, node: Node, parent: Symbol | None, prefix: str, start: int) -> None:
        name = self.text(node.child_by_field_name("name"))
        body = node.child_by_field_name("body")
        sym = self.add_symbol(node, name, "trait", qual_prefix=prefix, parent=parent, body=body, start_line=start,
                              exported=self._is_pub(node))
        members: set[int] = set()
        if body is not None:
            for item in body.named_children:
                if item.type in ("function_item", "function_signature_item"):
                    self._function(item, sym, sym.qualname, self.leading_start(item, _GLUE), owner=name)
                    members.add(item.id)
        roots = [c for c in (node.child_by_field_name("type_parameters"), node.child_by_field_name("bounds")) if c is not None]
        if body is not None:
            roots.extend(c for c in body.named_children if c.id not in members)
        self.set_refs(sym, roots, sig_roots=roots)

    # ------------------------------------------------------------------- use
    def _use(self, node: Node | None, prefix: str, s: int, e: int) -> None:
        if node is None:
            return
        t = node.type
        join = (lambda p, x: f"{p}::{x}" if p else x)
        if t in ("identifier", "self", "crate", "super"):
            name = self.text(node)
            if name == "self":
                # ``use a::b::{self}`` binds ``b`` as a module alias.
                if prefix:
                    mod, _, last = prefix.rpartition("::")
                    self.imports.append(ImportBinding(last, mod, last, s, e))
                return
            self.imports.append(ImportBinding(name, prefix, name, s, e))
        elif t == "scoped_identifier":
            path = node.child_by_field_name("path")
            name = self.text(node.child_by_field_name("name"))
            self.imports.append(ImportBinding(name, join(prefix, self.text(path)) if path is not None else prefix, name, s, e))
        elif t == "use_as_clause":
            path = node.child_by_field_name("path")
            alias = self.text(node.child_by_field_name("alias"))
            full = join(prefix, self.text(path))
            mod, _, last = full.rpartition("::")
            self.imports.append(ImportBinding(alias, mod, last, s, e))
        elif t == "scoped_use_list":
            path = node.child_by_field_name("path")
            lst = node.child_by_field_name("list")
            new_prefix = join(prefix, self.text(path)) if path is not None else prefix
            if lst is not None:
                for item in lst.named_children:
                    self._use(item, new_prefix, s, e)
        elif t == "use_list":
            for item in node.named_children:
                self._use(item, prefix, s, e)
        elif t == "use_wildcard":
            inner = node.named_children[0] if node.named_children else None
            module = join(prefix, self.text(inner)) if inner is not None else prefix
            self.imports.append(ImportBinding("*", module, None, s, e, wildcard=True))

    # ------------------------------------------------------------ references
    def _last_segment(self, node: Node | None) -> str:
        if node is None:
            return "?"
        if node.type in ("scoped_identifier", "scoped_type_identifier"):
            return self.text(node.child_by_field_name("name"))
        if node.type == "generic_type":
            return self._last_segment(node.child_by_field_name("type"))
        return self.text(node)

    def _receiver(self, node: Node | None) -> str:
        if node is None:
            return "?"
        if node.type in ("self", "identifier"):
            return self.text(node)
        if node.type == "field_expression":
            parts: list[str] = []
            cur: Node | None = node
            while cur is not None and cur.type == "field_expression":
                f = cur.child_by_field_name("field")
                if f is None or f.type != "field_identifier":
                    return "?"
                parts.append(self.text(f))
                cur = cur.child_by_field_name("value")
            if cur is not None and cur.type in ("self", "identifier"):
                parts.append(self.text(cur))
                return ".".join(reversed(parts))
        return "?"

    def visit(self, node: Node, out: list[Ref]) -> list[Node] | None:
        t = node.type
        if t in ("identifier", "type_identifier"):
            out.append(Ref(self.text(node), None, self.start_line(node)))
            return []
        if t in ("field_identifier", "self", "crate", "super", "lifetime", "primitive_type", "shorthand_field_identifier"):
            if t == "shorthand_field_identifier":
                out.append(Ref(self.text(node), None, self.start_line(node)))
            return []
        if t == "field_expression":
            value = node.child_by_field_name("value")
            field = node.child_by_field_name("field")
            if field is not None and field.type == "field_identifier":
                out.append(Ref(self.text(field), self._receiver(value), self.start_line(field), is_call_target(node)))
            return [value] if value is not None else []
        if t in ("scoped_identifier", "scoped_type_identifier"):
            path = node.child_by_field_name("path")
            name = node.child_by_field_name("name")
            if name is not None:
                out.append(Ref(self.text(name), self._last_segment(path) if path is not None else "?", self.start_line(name), is_call_target(name)))
            if path is not None and path.type in ("identifier", "type_identifier"):
                out.append(Ref(self.text(path), None, self.start_line(path)))
            elif path is not None and path.type in ("scoped_identifier", "generic_type"):
                return [path]
            return []
        if t in ("string_literal", "raw_string_literal", "char_literal", "integer_literal", "float_literal", "attribute_item", "inner_attribute_item", "use_declaration"):
            return []
        if t == "field_initializer":
            value = node.child_by_field_name("value")
            return [value] if value is not None else []
        return None

    def _pattern_names(self, node: Node | None, out: set[str]) -> None:
        if node is None:
            return
        t = node.type
        if t == "identifier":
            out.add(self.text(node))
            return
        if t in ("shorthand_field_identifier",):
            out.add(self.text(node))
            return
        if t in ("scoped_identifier", "type_identifier", "scoped_type_identifier"):
            return
        for i, c in enumerate(node.children):
            if not c.is_named:
                continue
            if t in ("tuple_struct_pattern", "struct_pattern") and node.field_name_for_child(i) == "type":
                continue
            if t == "field_pattern" and node.field_name_for_child(i) == "name":
                continue
            self._pattern_names(c, out)

    def type_hints(self, node: Node, out: dict[str, str]) -> None:
        t = node.type
        if t not in ("parameter", "let_declaration"):
            return
        pattern = node.child_by_field_name("pattern")
        if pattern is not None and pattern.type == "mut_pattern" and pattern.named_children:
            pattern = pattern.named_children[0]
        if pattern is None or pattern.type != "identifier":
            return
        tnode = node.child_by_field_name("type")
        typ = main_type(self.text(tnode).replace("::", ".")) if tnode is not None else None
        value = node.child_by_field_name("value") if t == "let_declaration" else None
        if typ is None and value is not None:
            if value.type == "try_expression" and value.named_children:
                value = value.named_children[0]
            if value.type == "struct_expression":
                name = value.child_by_field_name("name")
                typ = self._last_segment(name) if name is not None else None
            elif value.type == "call_expression":
                fn = value.child_by_field_name("function")
                if fn is not None and fn.type == "scoped_identifier":
                    path = fn.child_by_field_name("path")
                    seg = self._last_segment(path) if path is not None else ""
                    if seg[:1].isupper() and seg not in ("Self", "Some", "Ok", "Err", "Box", "Rc", "Arc", "Vec", "String", "HashMap"):
                        typ = seg
        if typ:
            out[self.text(pattern)] = typ.rsplit(".", 1)[-1] if "." in typ and typ.split(".", 1)[0] in ("crate", "self", "super") else typ

    def bindings(self, node: Node, out: set[str]) -> None:
        t = node.type
        if t in ("let_declaration", "parameter", "for_expression", "let_condition"):
            self._pattern_names(node.child_by_field_name("pattern"), out)
        elif t == "closure_parameters":
            for c in node.named_children:
                if c.type == "parameter":
                    self._pattern_names(c.child_by_field_name("pattern"), out)
                else:
                    self._pattern_names(c, out)
        elif t == "match_pattern":
            self._pattern_names(node, out)
        elif t == "type_parameter":
            name = node.child_by_field_name("name")
            if name is not None:
                out.add(self.text(name))
        elif t == "type_parameters":
            for c in node.named_children:
                if c.type == "type_identifier":
                    out.add(self.text(c))
                elif c.type in ("constrained_type_parameter", "type_parameter"):
                    left = c.child_by_field_name("left") or c.child_by_field_name("name")
                    if left is not None:
                        out.add(self.text(left))
