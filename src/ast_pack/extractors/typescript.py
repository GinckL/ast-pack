"""TypeScript / TSX / JavaScript extractor (one grammar family)."""

from __future__ import annotations

from tree_sitter import Node

from ..models import ImportBinding, Ref, Symbol
from .base import BaseExtractor, is_call_target, main_type

_FUNC_VALUES = frozenset({"arrow_function", "function_expression", "function", "generator_function"})
_CLASS_TYPES = frozenset({"class_declaration", "abstract_class_declaration", "class"})
_PATTERN_LEAVES = frozenset({"identifier", "shorthand_property_identifier_pattern"})


class TypeScriptExtractor(BaseExtractor):
    comment_types = frozenset({"comment", "hash_bang_line"})

    # ----------------------------------------------------------- top level
    def extract(self, root: Node) -> None:
        self._statements(root.named_children, None, "")

    def _statements(self, nodes: list[Node], parent: Symbol | None, prefix: str) -> None:
        pending: list[Node] = []
        for child in nodes:
            if child.type in self.comment_types:
                continue
            if self._statement(child, child, parent, prefix):
                self._flush_block(pending, parent)
            else:
                pending.append(child)
        self._flush_block(pending, parent)

    def _statement(self, node: Node, outer: Node, parent: Symbol | None, prefix: str, default: bool = False) -> bool:
        t = node.type
        start = self.leading_start(outer)
        if t == "import_statement":
            self._import(node)
            return True
        if t == "export_statement":
            return self._export(node, parent, prefix)
        if t in ("function_declaration", "generator_function_declaration", "function_signature"):
            name_node = node.child_by_field_name("name")
            name = self.text(name_node) if name_node is not None else "default"
            body = node.child_by_field_name("body")
            sym = self.add_symbol(outer, name, "function", qual_prefix=prefix, parent=parent, body=body,
                                  start_line=start, decl_node=node, exported=outer.type == "export_statement")
            self._function_refs(sym, node)
            if default:
                self._default_export(name)
            return True
        if t in _CLASS_TYPES:
            self._class(node, outer, parent, prefix, start, default)
            return True
        if t == "interface_declaration":
            self._simple_type(node, outer, "interface", parent, prefix, start)
            return True
        if t == "type_alias_declaration":
            self._simple_type(node, outer, "type", parent, prefix, start)
            return True
        if t == "enum_declaration":
            self._simple_type(node, outer, "enum", parent, prefix, start)
            return True
        if t in ("lexical_declaration", "variable_declaration"):
            return self._variables(node, outer, parent, prefix, start)
        if t == "ambient_declaration":
            for child in node.named_children:
                if self._statement(child, outer, parent, prefix):
                    return True
            return False
        if t in ("internal_module", "module"):
            name_node = node.child_by_field_name("name")
            body = node.child_by_field_name("body")
            if name_node is None or body is None:
                return False
            name = self.text(name_node).strip("'\"")
            sym = self.add_symbol(outer, name, "module", qual_prefix=prefix, parent=parent, body=body,
                                  start_line=start, decl_node=node)
            self._statements(body.named_children, sym, sym.qualname)
            return True
        if t == "expression_statement" and node.named_children:
            inner = node.named_children[0]
            if inner.type in ("internal_module", "module"):
                return self._statement(inner, outer, parent, prefix)
        return False

    def _flush_block(self, nodes: list[Node], parent: Symbol | None) -> None:
        if not nodes:
            return
        first, last = nodes[0], nodes[-1]
        name = f"<toplevel@L{self.start_line(first)}>"
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
            parent=parent.id if parent else None,
        )
        if parent is not None:
            parent.children.append(sym.id)
        self.set_refs(sym, nodes)
        self.symbols.append(sym)
        nodes.clear()

    # --------------------------------------------------------------- exports
    def _export(self, node: Node, parent: Symbol | None, prefix: str) -> bool:
        source = node.child_by_field_name("source")
        decl = node.child_by_field_name("declaration")
        value = node.child_by_field_name("value")
        is_default = any(not c.is_named and c.type == "default" for c in node.children)
        if source is not None:
            module = self._string(source)
            clause = next((c for c in node.named_children if c.type == "export_clause"), None)
            ns = next((c for c in node.named_children if c.type == "namespace_export"), None)
            if clause is not None:
                for spec in clause.named_children:
                    if spec.type != "export_specifier":
                        continue
                    name = self.text(spec.child_by_field_name("name"))
                    alias_node = spec.child_by_field_name("alias")
                    alias = self.text(alias_node) if alias_node is not None else name
                    self.imports.append(ImportBinding(alias, module, name, self.start_line(node), self.end_line(node), reexport=True))
            elif ns is not None:
                ident = ns.named_children[0] if ns.named_children else None
                self.imports.append(ImportBinding(self.text(ident), module, None, self.start_line(node), self.end_line(node), reexport=True))
            else:
                self.imports.append(ImportBinding("*", module, None, self.start_line(node), self.end_line(node), wildcard=True, reexport=True))
            return True
        if decl is not None:
            return self._statement(decl, node, parent, prefix, default=is_default)
        if value is not None:
            if value.type == "identifier":
                self._default_export(self.text(value))
                return True
            if value.type in _CLASS_TYPES:
                self._class(value, node, parent, prefix, self.leading_start(node), True)
                return True
            if value.type in _FUNC_VALUES or value.type in ("function_expression",):
                name_node = value.child_by_field_name("name")
                name = self.text(name_node) if name_node is not None else "default"
                sym = self.add_symbol(node, name, "function", qual_prefix=prefix, parent=parent,
                                      body=value.child_by_field_name("body"), start_line=self.leading_start(node),
                                      decl_node=node)
                self._function_refs(sym, value)
                if name != "default":
                    self._default_export(name)
                return True
            return False
        clause = next((c for c in node.named_children if c.type == "export_clause"), None)
        if clause is not None:
            for spec in clause.named_children:
                if spec.type != "export_specifier":
                    continue
                name = self.text(spec.child_by_field_name("name"))
                alias_node = spec.child_by_field_name("alias")
                if alias_node is not None:
                    self.imports.append(ImportBinding(self.text(alias_node), ".", name, self.start_line(node), self.end_line(node), reexport=True))
            return True
        return False

    def _default_export(self, name: str) -> None:
        if name != "default":
            self.imports.append(ImportBinding("default", ".", name, 0, 0, reexport=True))

    # ---------------------------------------------------------- definitions
    def _function_refs(self, sym: Symbol, fn: Node) -> None:
        roots = [c for c in (fn.child_by_field_name(f) for f in ("type_parameters", "parameters", "parameter", "return_type", "body")) if c is not None]
        sig = [c for c in (fn.child_by_field_name(f) for f in ("type_parameters", "parameters", "parameter", "return_type")) if c is not None]
        self.set_refs(sym, roots, sig_roots=sig)

    def _class(self, node: Node, outer: Node, parent: Symbol | None, prefix: str, start: int, default: bool) -> None:
        name_node = node.child_by_field_name("name")
        name = self.text(name_node) if name_node is not None else "default"
        body = node.child_by_field_name("body")
        bases: list[str] = []
        heritage = next((c for c in node.named_children if c.type == "class_heritage"), None)
        if heritage is not None:
            for clause in heritage.named_children:
                for c in clause.named_children:
                    if c.type in ("identifier", "type_identifier", "member_expression", "nested_type_identifier", "generic_type"):
                        base = self.text(c.child_by_field_name("name") if c.type == "generic_type" else c)
                        bases.append(base.rsplit(".", 1)[-1])
        sym = self.add_symbol(outer, name, "class", qual_prefix=prefix, parent=parent, body=body,
                              start_line=start, bases=tuple(bases), decl_node=node,
                              exported=outer.type == "export_statement")
        if default:
            self._default_export(name)
        members: set[int] = set()
        if body is not None:
            for member in body.named_children:
                m_name, fn = self._member(member)
                if fn is None:
                    continue
                msym = self.add_symbol(member, m_name, "method", qual_prefix=sym.qualname, parent=sym,
                                       body=fn.child_by_field_name("body"), start_line=self.leading_start(member, ("decorator",)),
                                       owner=name, self_names=("this",), decl_node=member,
                                       exported=not m_name.startswith("#"))
                self._function_refs(msym, fn)
                members.add(member.id)
        if body is not None:
            for member in body.named_children:
                if member.type in ("public_field_definition", "field_definition"):
                    fname = member.child_by_field_name("name") or member.child_by_field_name("property")
                    ann = member.child_by_field_name("type")
                    value = member.child_by_field_name("value")
                    t = main_type(self.text(ann).lstrip(":")) if ann is not None else None
                    if t is None and value is not None and value.type == "new_expression":
                        ctor = value.child_by_field_name("constructor")
                        t = self.text(ctor) if ctor is not None else None
                    if fname is not None and t:
                        sym.field_types[self.text(fname)] = t
                elif member.type == "method_definition" and self.text(member.child_by_field_name("name")) == "constructor":
                    params = member.child_by_field_name("parameters")
                    for p in params.named_children if params is not None else []:
                        if p.type in ("required_parameter", "optional_parameter") and any(
                            c.type == "accessibility_modifier" or c.type == "readonly" for c in p.children
                        ):
                            pat, ann = p.child_by_field_name("pattern"), p.child_by_field_name("type")
                            t = main_type(self.text(ann).lstrip(":")) if ann is not None else None
                            if pat is not None and t:
                                sym.field_types[self.text(pat)] = t
                    # this.x = new Foo() inside the constructor body
                    stack = [member.child_by_field_name("body")]
                    while stack:
                        cur = stack.pop()
                        if cur is None:
                            continue
                        if cur.type == "assignment_expression":
                            left, right = cur.child_by_field_name("left"), cur.child_by_field_name("right")
                            if (
                                left is not None and left.type == "member_expression"
                                and self.text(left.child_by_field_name("object")) == "this"
                                and right is not None and right.type == "new_expression"
                            ):
                                ctor = right.child_by_field_name("constructor")
                                prop = self.text(left.child_by_field_name("property"))
                                if ctor is not None and prop not in sym.field_types:
                                    sym.field_types[prop] = self.text(ctor)
                        stack.extend(cur.named_children)
        roots: list[Node] = []
        if heritage is not None:
            roots.append(heritage)
        tp = node.child_by_field_name("type_parameters")
        if tp is not None:
            roots.append(tp)
        if body is not None:
            roots.extend(c for c in body.named_children if c.id not in members)
        self.set_refs(sym, roots, sig_roots=[heritage] if heritage is not None else ())

    def _member(self, member: Node) -> tuple[str, Node | None]:
        if member.type == "method_definition":
            name_node = member.child_by_field_name("name")
            return self.text(name_node), member
        if member.type in ("public_field_definition", "field_definition"):
            value = member.child_by_field_name("value")
            name_node = member.child_by_field_name("name") or member.child_by_field_name("property")
            if value is not None and value.type in _FUNC_VALUES and name_node is not None:
                return self.text(name_node), value
        return "", None

    def _simple_type(self, node: Node, outer: Node, kind: str, parent: Symbol | None, prefix: str, start: int) -> None:
        name = self.text(node.child_by_field_name("name"))
        body = node.child_by_field_name("body")
        sym = self.add_symbol(outer, name, kind, qual_prefix=prefix, parent=parent, body=body if kind != "type" else None,
                              start_line=start, decl_node=node, exported=outer.type == "export_statement")
        name_node = node.child_by_field_name("name")
        name_id = name_node.id if name_node is not None else -1
        roots = [c for c in node.named_children if c.id != name_id]
        self.set_refs(sym, roots, sig_roots=roots)

    def _variables(self, node: Node, outer: Node, parent: Symbol | None, prefix: str, start: int) -> bool:
        declarators = [c for c in node.named_children if c.type == "variable_declarator"]
        if not declarators:
            return False
        kind_kw = node.children[0].type if node.children else "const"
        created = False
        for decl in declarators:
            name_node = decl.child_by_field_name("name")
            value = decl.child_by_field_name("value")
            if value is not None and value.type == "call_expression" and self._require(decl, name_node, value, node):
                created = True
                continue
            if name_node is None or name_node.type != "identifier":
                continue
            name = self.text(name_node)
            exported = outer.type == "export_statement"
            if value is not None and value.type in _FUNC_VALUES:
                sym = self.add_symbol(outer, name, "function", qual_prefix=prefix, parent=parent,
                                      body=value.child_by_field_name("body"), start_line=start,
                                      decl_node=node, sig_node=node, exported=exported)
                self._function_refs(sym, value)
            else:
                kind = "const" if kind_kw == "const" else "variable"
                sym = self.add_symbol(outer, name, kind, qual_prefix=prefix, parent=parent, start_line=start,
                                      decl_node=node, exported=exported)
                roots = [c for c in (decl.child_by_field_name("type"), value) if c is not None]
                self.set_refs(sym, roots)
            created = True
        return created

    def _require(self, decl: Node, name_node: Node | None, call: Node, stmt: Node) -> bool:
        fn = call.child_by_field_name("function")
        if fn is None or self.text(fn) != "require":
            return False
        args = call.child_by_field_name("arguments")
        if args is None or not args.named_children or args.named_children[0].type != "string":
            return False
        module = self._string(args.named_children[0])
        s, e = self.start_line(stmt), self.end_line(stmt)
        if name_node is None:
            return True
        if name_node.type == "identifier":
            self.imports.append(ImportBinding(self.text(name_node), module, None, s, e))
        elif name_node.type == "object_pattern":
            for p in name_node.named_children:
                if p.type == "shorthand_property_identifier_pattern":
                    n = self.text(p)
                    self.imports.append(ImportBinding(n, module, n, s, e))
                elif p.type == "pair_pattern":
                    key = self.text(p.child_by_field_name("key"))
                    val = p.child_by_field_name("value")
                    if val is not None and val.type == "identifier":
                        self.imports.append(ImportBinding(self.text(val), module, key, s, e))
        return True

    # --------------------------------------------------------------- imports
    def _string(self, node: Node) -> str:
        return self.text(node).strip("'\"`")

    def _import(self, node: Node) -> None:
        source = node.child_by_field_name("source")
        s, e = self.start_line(node), self.end_line(node)
        for child in node.named_children:
            if child.type == "import_require_clause":
                ident = child.named_children[0] if child.named_children else None
                src = child.child_by_field_name("source")
                if ident is not None and src is not None:
                    self.imports.append(ImportBinding(self.text(ident), self._string(src), None, s, e))
        if source is None:
            return
        module = self._string(source)
        clause = next((c for c in node.named_children if c.type == "import_clause"), None)
        if clause is None:
            return
        for c in clause.named_children:
            if c.type == "identifier":
                self.imports.append(ImportBinding(self.text(c), module, "default", s, e))
            elif c.type == "namespace_import":
                ident = c.named_children[0] if c.named_children else None
                if ident is not None:
                    self.imports.append(ImportBinding(self.text(ident), module, None, s, e))
            elif c.type == "named_imports":
                for spec in c.named_children:
                    if spec.type != "import_specifier":
                        continue
                    name = self.text(spec.child_by_field_name("name"))
                    alias_node = spec.child_by_field_name("alias")
                    alias = self.text(alias_node) if alias_node is not None else name
                    self.imports.append(ImportBinding(alias, module, name, s, e))

    # ------------------------------------------------------------ references
    def _receiver(self, obj: Node | None) -> str:
        if obj is None:
            return "?"
        if obj.type in ("identifier", "this", "super"):
            return self.text(obj)
        if obj.type == "member_expression":
            parts: list[str] = []
            cur: Node | None = obj
            while cur is not None and cur.type == "member_expression":
                parts.append(self.text(cur.child_by_field_name("property")))
                cur = cur.child_by_field_name("object")
            if cur is not None and cur.type in ("identifier", "this"):
                parts.append(self.text(cur))
                return ".".join(reversed(parts))
        return "?"

    def visit(self, node: Node, out: list[Ref]) -> list[Node] | None:
        t = node.type
        if t in ("identifier", "type_identifier", "shorthand_property_identifier"):
            out.append(Ref(self.text(node), None, self.start_line(node)))
            return []
        if t in ("property_identifier", "private_property_identifier", "statement_identifier", "predefined_type"):
            return []
        if t == "member_expression":
            obj = node.child_by_field_name("object")
            prop = node.child_by_field_name("property")
            if prop is not None and prop.type in ("property_identifier", "private_property_identifier"):
                out.append(Ref(self.text(prop), self._receiver(obj), self.start_line(prop), is_call_target(node)))
            return [obj] if obj is not None else []
        if t == "nested_type_identifier":
            module = node.child_by_field_name("module")
            name = node.child_by_field_name("name")
            if name is not None:
                out.append(Ref(self.text(name), self.text(module) if module is not None else "?", self.start_line(name)))
            return []
        if t in ("jsx_opening_element", "jsx_self_closing_element"):
            name = node.child_by_field_name("name")
            name_id = name.id if name is not None else -1
            rest = [c for c in node.named_children if c.id != name_id]
            if name is not None:
                if name.type == "identifier":
                    label = self.text(name)
                    if label[:1].isupper():
                        out.append(Ref(label, None, self.start_line(name)))
                else:
                    rest.append(name)
            return rest
        if t == "jsx_closing_element":
            return []
        if t == "pair":
            value = node.child_by_field_name("value")
            key = node.child_by_field_name("key")
            kids = [value] if value is not None else []
            if key is not None and key.type == "computed_property_name":
                kids.append(key)
            return kids
        if t in ("string", "regex", "number"):
            return []
        if t == "template_string":
            return [c for c in node.named_children if c.type == "template_substitution"]
        if t in ("import_statement",):
            return []
        if t in ("function_declaration", "generator_function_declaration", "class_declaration", "function_expression"):
            name = node.child_by_field_name("name")
            return [c for c in node.named_children if c.id != name.id] if name is not None else None
        if t == "jsx_attribute":
            return node.named_children[1:]
        return None

    def _pattern_names(self, node: Node | None, out: set[str]) -> None:
        if node is None:
            return
        if node.type in _PATTERN_LEAVES:
            out.add(self.text(node))
            return
        if node.type == "pair_pattern":
            self._pattern_names(node.child_by_field_name("value"), out)
            return
        if node.type in ("assignment_pattern", "object_assignment_pattern"):
            self._pattern_names(node.child_by_field_name("left"), out)
            return
        if node.type in ("object_pattern", "array_pattern", "rest_pattern"):
            for c in node.named_children:
                self._pattern_names(c, out)

    def type_hints(self, node: Node, out: dict[str, str]) -> None:
        t = node.type
        if t in ("required_parameter", "optional_parameter"):
            pattern = node.child_by_field_name("pattern")
            ann = node.child_by_field_name("type")
            if pattern is not None and pattern.type == "identifier" and ann is not None:
                typ = main_type(self.text(ann).lstrip(":"))
                if typ:
                    out[self.text(pattern)] = typ
        elif t == "variable_declarator":
            name = node.child_by_field_name("name")
            if name is None or name.type != "identifier":
                return
            ann = node.child_by_field_name("type")
            value = node.child_by_field_name("value")
            typ = main_type(self.text(ann).lstrip(":")) if ann is not None else None
            if typ is None and value is not None:
                if value.type == "await_expression" and value.named_children:
                    value = value.named_children[0]
                if value.type == "new_expression":
                    ctor = value.child_by_field_name("constructor")
                    if ctor is not None:
                        typ = self.text(ctor)
            if typ:
                out[self.text(name)] = typ

    def bindings(self, node: Node, out: set[str]) -> None:
        t = node.type
        if t == "variable_declarator":
            self._pattern_names(node.child_by_field_name("name"), out)
        elif t in ("required_parameter", "optional_parameter"):
            self._pattern_names(node.child_by_field_name("pattern"), out)
        elif t == "formal_parameters":
            for c in node.named_children:
                if c.type in ("identifier", "object_pattern", "array_pattern", "assignment_pattern", "rest_pattern"):
                    self._pattern_names(c, out)
        elif t == "arrow_function":
            p = node.child_by_field_name("parameter")
            if p is not None:
                self._pattern_names(p, out)
        elif t == "catch_clause":
            self._pattern_names(node.child_by_field_name("parameter"), out)
        elif t == "for_in_statement":
            self._pattern_names(node.child_by_field_name("left"), out)
        elif t in ("function_declaration", "generator_function_declaration", "class_declaration"):
            name = node.child_by_field_name("name")
            if name is not None:
                out.add(self.text(name))
        elif t == "type_parameter":
            name = node.child_by_field_name("name")
            if name is not None:
                out.add(self.text(name))
