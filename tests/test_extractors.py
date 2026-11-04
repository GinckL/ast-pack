"""Per-language extraction: symbols, ranges, imports, references."""

from ast_pack.extractors import extract_source
from ast_pack.extractors.base import main_type


def syms(result):
    return {s.qualname: s for s in result.symbols}


def test_python_symbols_and_imports():
    src = b'''import os
from .models import Payment, Card as C

RATE = 0.3

# helper comment
@decorator
class Gateway(Base):
    """Doc."""
    fee: int = 0

    def charge(self, p: Payment) -> "Receipt":
        self.validate(p)
        return compute(p, RATE)

    def validate(self, p):
        pass

def process(req, gw: Gateway):
    total = helper(req)
    return gw.charge(C(total))
'''
    r = extract_source("pay.py", src, "python")
    s = syms(r)
    assert s["RATE"].kind == "const"
    gw = s["Gateway"]
    assert gw.kind == "class" and gw.start_line == 6 and gw.bases == ("Base",)
    assert gw.field_types == {"fee": "int"} or gw.field_types == {}  # int is opaque
    charge = s["Gateway.charge"]
    assert charge.kind == "method" and charge.owner == "Gateway" and charge.self_names == ("self",)
    refs = {(x.name, x.receiver) for x in charge.refs}
    assert ("validate", "self") in refs and ("compute", None) in refs and ("RATE", None) in refs
    proc = {(x.name, x.receiver) for x in s["process"].refs}
    # gw is a typed parameter: the receiver is resolved to its type.
    assert ("charge", "<Gateway>") in proc
    assert ("total", None) not in proc  # locals are filtered
    imports = {(b.local, b.module, b.imported) for b in r.imports}
    assert ("C", ".models", "Card") in imports and ("os", "os", None) in imports
    assert 6 in r.comment_lines


def test_typescript_symbols_exports_and_jsx():
    src = b'''import D, { a, b as c } from "./x";
export * from "./r";
export default class A<T> extends B {
  x: number = 1;
  private m(v: T): void { this.n(); new C(); }
}
export const f = async (q: X): Promise<Y> => <Comp prop={h} />;
interface I { m(): void }
'''
    r = extract_source("a.tsx", src, "tsx")
    s = syms(r)
    assert s["A"].kind == "class" and s["A.m"].kind == "method"
    assert s["f"].kind == "function" and s["I"].kind == "interface"
    assert ("n", "this") in {(x.name, x.receiver) for x in s["A.m"].refs}
    f_refs = {x.name for x in s["f"].refs}
    assert {"Comp", "h", "X", "Y"} <= f_refs and "prop" not in f_refs
    locals_ = {(b.local, b.imported, b.wildcard, b.reexport) for b in r.imports}
    assert ("c", "b", False, False) in locals_
    assert ("*", None, True, True) in locals_
    assert ("default", "A", False, True) in locals_


def test_go_methods_receivers_and_grouped_imports():
    src = b'''package pay

import (
	"fmt"
	m "example.com/proj/models"
)

type Server struct {
	store *m.Store
}

func (s *Server) Charge(amt int) error {
	s.store.Save(m.Payment{Amount: amt})
	fmt.Println(amt)
	return s.helper()
}
'''
    r = extract_source("pay.go", src, "go")
    s = syms(r)
    charge = s["Server.Charge"]
    assert charge.owner == "Server" and charge.self_names == ("s",)
    refs = {(x.name, x.receiver) for x in charge.refs}
    assert ("helper", "s") in refs and ("Payment", "m") in refs and ("Save", "s.store") in refs
    assert s["Server"].field_types == {"store": "m.Store"}
    assert r.package == "pay" and r.always_keep_lines == [1]
    fmt = next(b for b in r.imports if b.local == "fmt")
    assert fmt.wrapper_lines == (3, 6) and fmt.start_line == 4


def test_rust_impl_traits_and_use_trees():
    src = b'''use crate::models::{Payment, Card as C};

/// doc
#[derive(Debug)]
pub struct Gateway { fee: Fee }

impl Gateway {
    pub fn charge(&self, p: &Payment) -> u64 {
        self.validate();
        Self::helper(compute(p))
    }
}
'''
    r = extract_source("src/lib.rs", src, "rust")
    s = syms(r)
    assert s["Gateway"].start_line == 3  # doc comment + attribute are glued on
    charge = s["Gateway.charge"]
    assert charge.kind == "method" and charge.owner == "Gateway"
    refs = {(x.name, x.receiver) for x in charge.refs}
    assert ("validate", "self") in refs and ("helper", "Self") in refs and ("compute", None) in refs
    assert {(b.local, b.module, b.imported) for b in r.imports} == {
        ("Payment", "crate::models", "Payment"),
        ("C", "crate::models", "Card"),
    }


def test_main_type():
    assert main_type("Optional[Gateway]") == "Gateway"
    assert main_type("*ledger.Ledger") == "ledger.Ledger"
    assert main_type("&mut Arc<Invoice>") == "Invoice"
    assert main_type("list[Card]") is None
    assert main_type("[]Entry") is None
