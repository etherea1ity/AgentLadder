"""Deterministic JSON-RPC MCP server used only by Chapter 17 tests."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path


TOOLS = [{"name": "echo", "description": "Echo one message.", "inputSchema": {"type": "object", "properties": {"message": {"type": "string"}}}}, {"name": "slow", "description": "Wait for timeout testing.", "inputSchema": {"type": "object"}}]
MODE = sys.argv[1] if len(sys.argv) > 1 else "normal"
LOG_PATH = Path(sys.argv[2]) if len(sys.argv) > 2 else None


for line in sys.stdin:
    try:
        request = json.loads(line)
    except json.JSONDecodeError:
        continue
    method = request.get("method")
    params = request.get("params", {})
    if LOG_PATH is not None:
        with LOG_PATH.open("a", encoding="utf-8") as handle:
            handle.write(str(method) + "\n")
    if "id" not in request:
        continue
    if method == "initialize" and MODE == "malformed":
        sys.stdout.write("not-json\n")
        sys.stdout.flush()
        continue
    if method == "initialize" and MODE == "oversized":
        sys.stdout.write("{" + ("x" * (1024 * 1024 + 32)) + "}\n")
        sys.stdout.flush()
        continue
    if method == "initialize":
        result = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}, "resources": {}, "prompts": {}}, "serverInfo": {"name": "chapter17-fixture", "version": "1.0"}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "resources/list":
        result = {"resources": [{"uri": "fixture://guide", "name": "Guide", "mimeType": "text/plain"}]}
    elif method == "prompts/list":
        result = {"prompts": [{"name": "brief", "description": "Create a brief."}]}
    elif method == "tools/call":
        if params.get("name") == "slow":
            time.sleep(0.25)
        result = {"content": [{"type": "text", "text": str(params.get("arguments", {}).get("message", "done"))}], "isError": False}
    elif method == "resources/read":
        result = {"contents": [{"uri": params.get("uri"), "mimeType": "text/plain", "text": "fixture resource"}]}
    elif method == "prompts/get":
        result = {"description": "Brief", "messages": [{"role": "user", "content": {"type": "text", "text": "Write a brief."}}]}
    elif method == "ping":
        result = {}
    else:
        sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": request["id"], "error": {"code": -32601, "message": "not found"}}, separators=(",", ":")) + "\n")
        sys.stdout.flush()
        continue
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}, separators=(",", ":")) + "\n")
    sys.stdout.flush()
