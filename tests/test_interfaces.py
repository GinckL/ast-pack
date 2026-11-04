"""CLI, HTTP/WebSocket server and MCP server."""

import json

import pytest

from ast_pack.cli import main, normalize_argv


def run_cli(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_normalize_argv():
    assert normalize_argv(["processPayment"]) == ["pack", "processPayment"]
    assert normalize_argv(["-C", "repo", "stats", "--json"]) == ["stats", "-C", "repo", "--json"]
    assert normalize_argv(["--ui"]) == ["serve", "--open"]
    assert normalize_argv(["search", "x"]) == ["search", "x"]


def test_cli_pack_json(capsys, fixture_root):
    code, out, _ = run_cli(capsys, "-C", str(fixture_root), "process_payment", "-d", "1", "--json", "--no-cache")
    assert code == 0
    data = json.loads(out)
    assert data["ok"] and data["command"] == "pack" and data["stats"]["symbols"] > 5
    assert "def process_payment" in data["bundle"]


def test_cli_pack_markdown_and_output_file(capsys, fixture_root, tmp_path):
    out_file = tmp_path / "ctx.md"
    code, out, err = run_cli(capsys, "pack", "tax_for", "-C", str(fixture_root), "-o", str(out_file), "--no-cache")
    assert code == 0 and out == ""
    assert "pub fn tax_for" in out_file.read_text()
    assert "saved" in err


def test_cli_errors_are_json_with_exit_code_2(capsys, fixture_root):
    code, out, _ = run_cli(capsys, "-C", str(fixture_root), "does_not_exist_anywhere", "--json", "--no-cache")
    assert code == 2
    data = json.loads(out)
    assert data["ok"] is False and data["error"]["exit_code"] == 2


def test_cli_search_and_stats_json(capsys, fixture_root):
    code, out, _ = run_cli(capsys, "search", "ledger", "-C", str(fixture_root), "--json", "--no-cache")
    assert code == 0 and any(r["qualname"] == "Ledger" for r in json.loads(out)["results"])
    code, out, _ = run_cli(capsys, "stats", "-C", str(fixture_root), "--json", "--no-cache")
    assert code == 0 and json.loads(out)["files"] >= 18


def test_cli_trace_from_file(capsys, fixture_root, tmp_path):
    from tests.test_pack import GO_TRACE

    trace = tmp_path / "panic.txt"
    trace.write_text(GO_TRACE)
    code, out, _ = run_cli(capsys, "trace", str(trace), "-C", str(fixture_root), "--json", "--no-bundle", "--no-cache")
    assert code == 0
    data = json.loads(out)
    assert data["trace"]["language"] == "go" and "bundle" not in data


@pytest.fixture()
def client(index):
    from starlette.testclient import TestClient

    from ast_pack.server import create_app

    with TestClient(create_app(index, watch_interval=0)) as c:
        yield c


def test_http_api(client):
    assert client.get("/api/health").json()["ok"]
    assert client.get("/api/stats").json()["files"] >= 18
    res = client.get("/api/search", params={"q": "subtotal"}).json()["results"]
    assert res[0]["name"] == "subtotal"
    body = client.post("/api/pack", json={"targets": ["CheckoutButton"], "depth": 2}).json()
    assert body["ok"] and any(n["qualname"] == "ApiClient.post" for n in body["nodes"])
    f = client.get("/api/file", params={"path": "web/src/lib/money.ts"}).json()
    assert "export function withTax" in f["text"]
    assert client.get("/api/file", params={"path": "../../etc/passwd"}).status_code == 404
    graph = client.get("/api/graph", params={"limit": 20}).json()
    assert len(graph["nodes"]) <= 20 and graph["edges"]
    page = client.get("/").text
    assert "application/ld+json" in page and "SoftwareApplication" in page
    assert client.post("/api/pack", json={"targets": ["x"], "depth": -1}).status_code == 400


def test_websocket_pack_and_search(client):
    with client.websocket_connect("/ws") as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello" and hello["stats"]["symbols"] > 0
        ws.send_json({"type": "search", "id": 1, "q": "charge"})
        msg = ws.receive_json()
        assert msg["type"] == "search_result" and msg["id"] == 1
        ws.send_json({"type": "pack", "id": 2, "params": {"targets": ["Invoice.total"], "depth": 1, "depth_profile": True}})
        msg = ws.receive_json()
        assert msg["type"] == "pack_result" and msg["id"] == 2
        assert msg["result"]["stats"]["bundle_tokens"] > 0 and msg["result"]["depth_profile"]
        ws.send_json({"type": "file", "id": 3, "path": "rscore/src/billing/tax.rs"})
        assert ws.receive_json()["type"] == "file_result"
        ws.send_json({"type": "nope", "id": 4})
        assert ws.receive_json()["type"] == "error"


def test_mcp_protocol(fixture_root):
    from ast_pack.index import IndexOptions
    from ast_pack.mcp import McpServer

    srv = McpServer(str(fixture_root), IndexOptions(use_cache=False))
    init = srv.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
    assert init["result"]["serverInfo"]["name"] == "ast-pack"
    assert srv.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    tools = srv.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
    assert {t["name"] for t in tools} == {"pack_context", "search_symbols", "repo_stats"}
    call = srv.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                       "params": {"name": "pack_context", "arguments": {"target": "transfer", "depth": 1}}})["result"]
    assert call["isError"] is False and "func transfer" in call["content"][0]["text"]
    assert call["structuredContent"]["stats"]["symbols"] > 1
    bad = srv.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                      "params": {"name": "pack_context", "arguments": {"target": "zzzz_none"}}})["result"]
    assert bad["isError"] is True
    assert srv.handle({"jsonrpc": "2.0", "id": 5, "method": "bogus"})["error"]["code"] == -32601


def test_json_outputs_match_schema(capsys, fixture_root):
    jsonschema = pytest.importorskip("jsonschema")
    from pathlib import Path

    schema = json.loads((Path(__file__).parents[1] / "schema.json").read_text())
    root = str(fixture_root)
    runs = [
        ("-C", root, "process_payment", "-d", "1", "--json", "--depth-profile"),
        ("-C", root, "transfer", "--json", "--no-bundle"),
        ("search", "pay", "-C", root, "--json"),
        ("stats", "-C", root, "--json"),
        ("-C", root, "no_such_symbol_xyz", "--json"),
    ]
    for argv in runs:
        main([*argv, "--no-cache"])
        doc = json.loads(capsys.readouterr().out)
        jsonschema.validate(doc, schema)
