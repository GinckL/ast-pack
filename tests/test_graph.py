"""Cross-file resolution on the polyglot fixture."""


def edges(index):
    return {(e.source, e.target, e.kind): e.confidence for v in index.edges_out.values() for e in v}


def test_python_cross_file_calls(index):
    e = edges(index)
    svc = "py/shop/payments/service.py::process_payment"
    assert e[(svc, "py/shop/payments/validation.py::validate_request", "call")] == 1.0
    # typed parameter `gateway: Gateway` resolves the method exactly
    assert e[(svc, "py/shop/payments/gateway.py::Gateway.charge", "call")] == 1.0
    assert (svc, "py/shop/models.py::PaymentRequest", "type") in e
    assert ("py/shop/payments/validation.py::validate_request", "py/shop/models.py::MAX_AMOUNT", "value") in e
    # instantiation pulls the constructor
    assert ("py/shop/api.py::checkout_handler", "py/shop/payments/gateway.py::Gateway.__init__", "call") in e


def test_typescript_barrel_alias_and_tsconfig_paths(index):
    e = edges(index)
    btn = "web/src/components/CheckoutButton.tsx::CheckoutButton"
    # `import { Client } from "@/lib"` -> index.ts `export { ApiClient as Client } from "./api"`
    assert (btn, "web/src/lib/api.ts::ApiClient", "type") in e
    assert e[(btn, "web/src/lib/api.ts::ApiClient.checkout", "call")] == 1.0
    # `export * from "./money"` through the barrel
    assert (btn, "web/src/lib/money.ts::formatMoney", "call") in e
    assert ("web/src/lib/api.ts::ApiClient.checkout", "web/src/lib/api.ts::ApiClient.post", "call") in e


def test_go_module_imports_and_receivers(index):
    e = edges(index)
    assert e[("gosvc/main.go::transfer", "gosvc/internal/ledger/ledger.go::Ledger.Append", "call")] == 1.0
    assert ("gosvc/main.go::transfer", "gosvc/internal/ledger/ledger.go::KindDebit", "value") in e
    assert ("gosvc/internal/ledger/ledger.go::Ledger.Append", "gosvc/internal/ledger/ledger.go::validate", "call") in e


def test_rust_use_paths_and_self_calls(index):
    e = edges(index)
    total = "rscore/src/billing/invoice.rs::Invoice.total"
    assert (total, "rscore/src/billing/tax.rs::tax_for", "call") in e
    assert (total, "rscore/src/billing/invoice.rs::Invoice.subtotal", "call") in e
    assert (total, "rscore/src/billing/tax.rs::Region", "type") in e
    # methods link to their impl type
    assert ("rscore/src/billing/invoice.rs::Invoice.add", "rscore/src/billing/invoice.rs::Invoice", "type") in e


def test_no_low_confidence_noise_on_fixture(index):
    assert all(c == 1.0 for c in edges(index).values())


def test_search_ranks_exact_first(index):
    hits = index.search("process_payment", limit=3)
    assert hits[0][1].qualname == "process_payment"
    fuzzy = index.search("prcpay", limit=5)
    assert any(s.qualname == "process_payment" for _, s in fuzzy)


def test_stats_shape(index):
    st = index.stats()
    assert st["files"] >= 18 and st["symbols"] > 70 and st["edges"] > 80
    assert set(st["languages"]) >= {"python", "typescript", "tsx", "go", "rust"}
