from __future__ import annotations

from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading

import pytest

from klara.mcp import McpClient, McpProtocolError, McpServerConfig, McpTimeoutError, McpTransportKind, StdioTransport, StreamableHttpTransport
from klara.permissions import PermissionScope


def config(**changes):
    values = dict(server_id="server-1", scope=PermissionScope("t", "u", "klara"), name="fixture", transport=McpTransportKind.STDIO, command=sys.executable, args=(str(Path("tests/fixtures/mcp/stdio_server.py").resolve()),), created_at="now", updated_at="now")
    values.update(changes)
    return McpServerConfig(**values)


def test_stdio_initialize_catalog_tools_resources_prompts_and_shutdown() -> None:
    transport = StdioTransport(config())
    client = McpClient(transport, request_timeout_seconds=2)
    catalog = client.initialize()
    assert catalog.protocol_version == "2025-11-25"
    assert [item["name"] for item in catalog.tools] == ["echo", "slow"]
    assert client.call_tool("echo", {"message": "hello"})["content"][0]["text"] == "hello"
    assert client.read_resource("fixture://guide")["contents"][0]["text"] == "fixture resource"
    assert client.get_prompt("brief", {})["messages"][0]["role"] == "user"
    client.close()
    assert transport.process.poll() is not None


def test_stdio_timeout_sends_cancellation_and_never_hangs() -> None:
    log_path = Path("data/test-artifacts/mcp-cancellation.log").resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.unlink(missing_ok=True)
    fixture = str(Path("tests/fixtures/mcp/stdio_server.py").resolve())
    transport = StdioTransport(config(args=(fixture, "normal", str(log_path))))
    client = McpClient(transport, request_timeout_seconds=2)
    try:
        client.initialize()
        client.request_timeout_seconds = 0.03
        with pytest.raises(McpTimeoutError, match="request_timeout"):
            client.call_tool("slow", {})
    finally:
        client.close()
    assert "notifications/cancelled" in log_path.read_text(encoding="utf-8")


@pytest.mark.parametrize("mode,expected", [("malformed", "malformed_jsonrpc"), ("oversized", "response_too_large")])
def test_stdio_malformed_and_oversized_responses_fail_closed(mode: str, expected: str) -> None:
    fixture = str(Path("tests/fixtures/mcp/stdio_server.py").resolve())
    transport = StdioTransport(config(args=(fixture, mode)))
    try:
        with pytest.raises(McpProtocolError, match=expected):
            McpClient(transport, request_timeout_seconds=2).initialize()
    finally:
        transport.close()


class Handler(BaseHTTPRequestHandler):
    headers_seen: list[dict[str, str]] = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.headers_seen.append(dict(self.headers))
        method = body.get("method")
        if "id" not in body:
            self.send_response(202); self.end_headers(); return
        result = {
            "initialize": {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}}, "serverInfo": {"name": "http-fixture", "version": "1"}},
            "tools/list": {"tools": [{"name": "echo", "inputSchema": {"type": "object"}}]},
            "ping": {},
        }[method]
        payload = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        if method == "initialize": self.send_header("Mcp-Session-Id", "fixture-session")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers(); self.wfile.write(payload)

    def do_DELETE(self): self.send_response(204); self.end_headers()
    def log_message(self, *_args): pass


def test_streamable_http_preserves_protocol_session_and_accept_headers() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        http_config = replace(config(), transport=McpTransportKind.STREAMABLE_HTTP, command=None, args=(), endpoint=f"http://127.0.0.1:{server.server_port}/mcp")
        transport = StreamableHttpTransport(http_config)
        client = McpClient(transport)
        client.initialize(); client.ping(); client.close()
        assert Handler.headers_seen[0]["Mcp-Method"] == "initialize"
        assert "application/json" in Handler.headers_seen[0]["Accept"]
        assert Handler.headers_seen[-1]["Mcp-Session-Id"] == "fixture-session"
        assert Handler.headers_seen[-1]["Mcp-Protocol-Version"] == "2025-11-25"
    finally:
        server.shutdown(); server.server_close(); Handler.headers_seen.clear()


class BadTransport:
    def request(self, message, *, timeout_seconds): return {"jsonrpc": "2.0", "id": message["id"] + 1, "result": {}}
    def notify(self, message): pass
    def close(self): pass


def test_jsonrpc_id_mismatch_fails_closed() -> None:
    with pytest.raises(McpProtocolError, match="response_mismatch"):
        McpClient(BadTransport()).initialize()


class TimeoutTransport:
    def __init__(self): self.notifications = []
    def request(self, message, *, timeout_seconds): raise McpTimeoutError("mcp_request_timeout")
    def notify(self, message): self.notifications.append(message)
    def close(self): pass


def test_timeout_cancellation_is_transport_independent() -> None:
    transport = TimeoutTransport()
    with pytest.raises(McpTimeoutError):
        McpClient(transport).initialize()
    assert transport.notifications == [{"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1, "reason": "timeout"}}]
