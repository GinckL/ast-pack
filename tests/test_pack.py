"""End-to-end slicing, rendering, traces, budgets."""

import ast

import pytest

from ast_pack.engine import PackOptions, pack
from ast_pack.extractors.base import count_errors
from ast_pack.languages import get_parser


def files_of(result):
    return {f.path: f for f in result.files}


def test_symbol_slice_includes_callees_types_and_prunes_siblings(index):
    r = pack(index, PackOptions(targets=["process_payment"], depth=1))
    assert r.ok and r.resolution.seeds == ["py/shop/payments/service.py::process_payment"]
    ids = set(r.graph.nodes)
    assert "py/shop/payments/validation.py::validate_request" in ids
    assert "py/shop/payments/gateway.py::Gateway.charge" in ids
    assert "py/shop/api.py::checkout_handler" in ids  # caller
    assert "py/shop/models.py::MAX_AMOUNT" in ids  # constant used by a callee
    assert "py/shop/payments/service.py::daily_report" not in ids  # sibling
    svc = files_of(r)["py/shop/payments/service.py"]
    assert "def process_payment" in svc.text and "def daily_report" not in svc.text
    assert any(s.kind == "pruned" and "daily_report" in s.symbols for s in svc.segments)
    assert "### py/shop/payments/service.py · lines" in r.bundle


def test_depth_zero_and_direction(index):
    r0 = pack(index, PackOptions(targets=["validate_request"], depth=0))
    roles = {n.role for n in r0.graph.nodes.values()}
    assert "callee" not in roles and "caller" not in roles
    callers = pack(index, PackOptions(targets=["validate_request"], depth=2, direction="callers"))
    ids = set(callers.graph.nodes)
    assert "py/shop/payments/service.py::process_payment" in ids
    assert "py/shop/api.py::checkout_handler" in ids
    assert "py/shop/payments/validation.py::luhn_ok" not in ids  # a callee
    callees = pack(index, PackOptions(targets=["validate_request"], depth=2, direction="callees"))
    assert "py/shop/payments/validation.py::luhn_ok" in callees.graph.nodes
    assert "py/shop/api.py::checkout_handler" not in callees.graph.nodes


def test_outline_mode_for_classes_used_as_types(index):
    r = pack(index, PackOptions(targets=["process_payment"], depth=0))
    node = r.graph.nodes["py/shop/models.py::PaymentRequest"]
    assert node.role == "type" and node.mode == "outline"
    models = files_of(r)["py/shop/models.py"].text
    assert "amount: Decimal" in models  # dataclass fields stay
    assert "return self.amount > MAX_AMOUNT / 2" not in models  # unused method bodies go


def test_every_rendered_file_is_syntactically_valid(index):
    for sym in list(index.symbols.values()):
        if sym.kind in ("block", "impl"):
            continue
        for depth in (0, 2):
            r = pack(index, PackOptions(targets=[f"{sym.path}::{sym.qualname}"], depth=depth))
            for f in r.files:
                if f.lang == "python":
                    ast.parse(f.text)
                else:
                    tree = get_parser(f.lang).parse(f.text.encode())
                    assert count_errors(tree.root_node) == 0, (sym.id, f.path, f.text)


def test_tests_are_excluded_unless_asked(index):
    r = pack(index, PackOptions(targets=["process_payment"], depth=1))
    assert not any(n.startswith("py/tests/") for n in r.graph.nodes)
    r2 = pack(index, PackOptions(targets=["process_payment"], depth=1, include_tests=True))
    assert "py/tests/test_service.py::test_process_payment_charges" in r2.graph.nodes


def test_file_line_target(index):
    r = pack(index, PackOptions(targets=["rscore/src/billing/invoice.rs:33"], depth=0))
    assert r.resolution.kind == "file_line"
    assert r.resolution.seeds == ["rscore/src/billing/invoice.rs::Invoice.total"]
    assert "▼ L33: target line" in r.bundle


def test_qualified_and_path_targets(index):
    assert pack(index, PackOptions(targets=["Gateway.charge"], depth=0)).resolution.seeds == [
        "py/shop/payments/gateway.py::Gateway.charge"
    ]
    assert pack(index, PackOptions(targets=["ledger.Append"], depth=0)).resolution.seeds == [
        "gosvc/internal/ledger/ledger.go::Ledger.Append"
    ]
    r = pack(index, PackOptions(targets=["py/shop/payments/service.py::refund_payment"], depth=0))
    assert r.resolution.seeds == ["py/shop/payments/service.py::refund_payment"]


def test_unknown_target_suggests(index):
    r = pack(index, PackOptions(targets=["procss_paymnt"], depth=1))
    assert not r.ok
    assert any("process_payment" in s for s in r.resolution.suggestions)


PY_TRACE = '''Traceback (most recent call last):
  File "/srv/app/py/shop/api.py", line 14, in checkout_handler
    receipt = process_payment(req, Gateway("sk_live"))
  File "/srv/app/py/shop/payments/service.py", line 12, in process_payment
    validate_request(req)
  File "/srv/app/py/shop/payments/validation.py", line 30, in validate_request
    raise ValidationError("invalid card")
  File "/usr/lib/python3.12/re.py", line 10, in match
shop.payments.validation.ValidationError: invalid card
'''

NODE_TRACE = """TypeError: Cannot read properties of undefined (reading 'reduce')
    at subtotal (/app/web/src/lib/money.ts:10:21)
    at ApiClient.checkout (/app/web/src/lib/api.ts:13:28)
    at handleClick (webpack-internal:///(app-pages-browser)/./web/src/components/CheckoutButton.tsx:16:31)
    at processTicksAndRejections (node:internal/process/task_queues:95:5)"""

GO_TRACE = """panic: runtime error: invalid memory address or nil pointer dereference

goroutine 1 [running]:
example.com/gosvc/internal/ledger.(*Ledger).Append(0x0, {0x4b6f43, 0x5}, 0x64, 0x0)
	/home/dev/gosvc/internal/ledger/ledger.go:34 +0x55
main.transfer(0x0, {0x4b6f43, 0x5}, {0x4b6f48, 0x3}, 0x64)
	/home/dev/gosvc/main.go:11 +0x6b
main.main()
	/home/dev/gosvc/main.go:19 +0x45
exit status 2"""

RUST_TRACE = """thread 'main' panicked at rscore/src/billing/tax.rs:12:30:
attempt to multiply with overflow
note: run with `RUST_BACKTRACE=1` environment variable to display a backtrace"""


@pytest.mark.parametrize(
    "trace,lang,crash_symbol,n_seeds",
    [
        (PY_TRACE, "python", "py/shop/payments/validation.py::validate_request", 3),
        (NODE_TRACE, "javascript", "web/src/lib/money.ts::subtotal", 3),
        (GO_TRACE, "go", "gosvc/internal/ledger/ledger.go::Ledger.Append", 3),
        (RUST_TRACE, "rust", "rscore/src/billing/tax.rs::tax_for", 1),
    ],
)
def test_stack_traces(index, trace, lang, crash_symbol, n_seeds):
    r = pack(index, PackOptions(targets=[trace], depth=0))
    res = r.resolution
    assert res.kind == "trace" and res.trace_language == lang
    assert res.crash_site is not None and res.crash_site.symbol_id == crash_symbol
    assert len(res.seeds) == n_seeds
    assert "crash site" in r.bundle
    d = r.to_dict()
    assert d["trace"]["crash_site"]["symbol"] == crash_symbol


def test_token_budget_drops_far_nodes_first(index):
    full = pack(index, PackOptions(targets=["CheckoutButton"], depth=3))
    budget = full.bundle_tokens // 2
    r = pack(index, PackOptions(targets=["CheckoutButton"], depth=3, max_tokens=budget))
    assert r.bundle_tokens <= budget
    assert "web/src/components/CheckoutButton.tsx::CheckoutButton" in r.graph.nodes
    assert r.dropped
    assert r.bundle_tokens == index.counter.count(r.bundle)


def test_summary_token_count_is_exact(index):
    r = pack(index, PackOptions(targets=["Invoice.total"], depth=1))
    assert f"{r.bundle_tokens:,} tokens" in r.bundle
    assert r.bundle_tokens == index.counter.count(r.bundle)


def test_formats_and_flags(index):
    xml = pack(index, PackOptions(targets=["tax_for"], depth=0, format="xml", prompt="Fix the overflow"))
    assert xml.bundle.startswith("<task>\nFix the overflow\n</task>")
    assert '<file path="rscore/src/billing/tax.rs" language="rust"' in xml.bundle
    plain = pack(index, PackOptions(targets=["tax_for"], depth=0, format="plain", slice_map=False))
    assert "==> rscore/src/billing/tax.rs" in plain.bundle and "Slice map" not in plain.bundle
    numbered = pack(index, PackOptions(targets=["tax_for"], depth=0, line_numbers=True))
    assert "10 │ pub fn tax_for" in numbered.bundle
    stripped = pack(index, PackOptions(targets=["tax_for"], depth=0, strip_comments=True))
    assert "Standard VAT rate" not in stripped.bundle


def test_depth_profile_monotonic(index):
    r = pack(index, PackOptions(targets=["validate_request"], depth=1, depth_profile=True))
    prof = r.depth_profile
    assert prof[0]["depth"] == 0
    assert all(a["symbols"] <= b["symbols"] for a, b in zip(prof, prof[1:]))


def test_to_dict_contract(index):
    d = pack(index, PackOptions(targets=["process_payment"], depth=1)).to_dict()
    for key in ("schema_version", "ok", "query", "seeds", "stats", "nodes", "edges", "files", "bundle", "warnings"):
        assert key in d
    assert d["stats"]["tokenizer"] in ("cl100k_base", "approx")
    seg_kinds = {s["kind"] for f in d["files"] for s in f["segments"]}
    assert seg_kinds == {"code", "pruned"}
    node_ids = {n["id"] for n in d["nodes"]}
    assert all(e["source"] in node_ids and e["target"] in node_ids for e in d["edges"])


def test_segment_line_maps_align_with_text(index):
    for target in ["process_payment", "CheckoutButton", "Ledger.Append", "Invoice.total"]:
        r = pack(index, PackOptions(targets=[target], depth=2))
        for f in r.files:
            for seg in f.segments:
                assert len(seg.lines) == len(seg.text.split("\n")), (f.path, seg.start)
                if seg.kind == "code":
                    src = index.file_lines(f.path)
                    for text_line, n in zip(seg.text.split("\n"), seg.lines):
                        if n is not None:
                            assert text_line == src[n - 1]
