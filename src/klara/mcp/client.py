"""Bounded JSON-RPC MCP client with stdio and Streamable HTTP transports."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import tempfile
import threading
from time import monotonic
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from klara.mcp.models import McpCapabilityCatalog, McpServerConfig, McpTransportKind


PROTOCOL_VERSION = "2025-11-25"
MAX_MESSAGE_BYTES = 1024 * 1024


class McpError(RuntimeError):
    pass


class McpProtocolError(McpError):
    pass


class McpTimeoutError(McpError):
    pass


class McpTransport(Protocol):
    def request(self, message: dict[str, Any], *, timeout_seconds: float) -> dict[str, Any]: ...
    def notify(self, message: dict[str, Any]) -> None: ...
    def close(self) -> None: ...


class StdioTransport:
    """Newline-delimited UTF-8 JSON-RPC over an isolated child process."""

    def __init__(self, config: McpServerConfig) -> None:
        if not config.command:
            raise McpProtocolError("mcp_stdio_command_required")
        executable = _resolve_executable(config.command)
        environment = _minimal_environment(config.env_refs)
        self._working_directory = Path(tempfile.mkdtemp(prefix="klara-mcp-"))
        self._closed = False
        try:
            self.process = subprocess.Popen(
                [executable, *config.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                shell=False,
                env=environment,
                cwd=str(self._working_directory),
                creationflags=(
                    subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                ),
            )
        except OSError as exc:
            shutil.rmtree(self._working_directory, ignore_errors=True)
            raise McpError("mcp_stdio_start_failed") from exc
        self._responses: queue.Queue[dict[str, Any] | BaseException] = queue.Queue()
        self._write_lock = threading.Lock()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self._stderr_reader = threading.Thread(target=self._drain_stderr, daemon=True)
        self._stderr_reader.start()

    def request(self, message: dict[str, Any], *, timeout_seconds: float) -> dict[str, Any]:
        self._send(message)
        deadline = monotonic() + timeout_seconds
        deferred: list[dict[str, Any]] = []
        try:
            while True:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise McpTimeoutError("mcp_request_timeout")
                try:
                    value = self._responses.get(timeout=remaining)
                except queue.Empty:
                    raise McpTimeoutError("mcp_request_timeout") from None
                if isinstance(value, McpError):
                    raise value
                if isinstance(value, BaseException):
                    raise McpError("mcp_stdio_closed") from value
                if value.get("id") == message.get("id"):
                    return value
                if isinstance(value.get("id"), int) and isinstance(message.get("id"), int) and value["id"] < message["id"]:
                    continue
                deferred.append(value)
        finally:
            for value in deferred:
                self._responses.put(value)

    def notify(self, message: dict[str, Any]) -> None:
        self._send(message)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        process = self.process
        if process.poll() is None:
            if process.stdin:
                try:
                    process.stdin.close()
                except OSError:
                    pass
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream:
                try:
                    stream.close()
                except OSError:
                    pass
        self._reader.join(timeout=1)
        self._stderr_reader.join(timeout=1)
        shutil.rmtree(self._working_directory, ignore_errors=True)

    def _send(self, message: dict[str, Any]) -> None:
        encoded = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        if "\n" in encoded or len(encoded.encode("utf-8")) > MAX_MESSAGE_BYTES:
            raise McpProtocolError("mcp_message_too_large_or_invalid")
        if self.process.poll() is not None or self.process.stdin is None:
            raise McpError("mcp_stdio_not_running")
        with self._write_lock:
            self.process.stdin.write(encoded + "\n")
            self.process.stdin.flush()

    def _read_loop(self) -> None:
        try:
            assert self.process.stdout is not None
            for line in self.process.stdout:
                if len(line.encode("utf-8")) > MAX_MESSAGE_BYTES:
                    self._responses.put(McpProtocolError("mcp_response_too_large"))
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    self._responses.put(McpProtocolError("mcp_malformed_jsonrpc"))
                    continue
                if not isinstance(value, dict):
                    self._responses.put(McpProtocolError("mcp_jsonrpc_object_required"))
                    continue
                self._responses.put(value)
        except BaseException as exc:
            self._responses.put(exc)

    def _drain_stderr(self) -> None:
        """Prevent an untrusted server from blocking on a full stderr pipe."""

        try:
            assert self.process.stderr is not None
            for _line in self.process.stderr:
                pass
        except BaseException:
            pass


class StreamableHttpTransport:
    """POST-based Streamable HTTP supporting JSON and finite SSE responses."""

    def __init__(self, config: McpServerConfig) -> None:
        if not config.endpoint:
            raise McpProtocolError("mcp_http_endpoint_required")
        self.endpoint = config.endpoint
        self.credential_ref = config.credential_ref
        self.session_id: str | None = None
        self.protocol_version = PROTOCOL_VERSION

    def request(self, message: dict[str, Any], *, timeout_seconds: float) -> dict[str, Any]:
        return self._post(message, timeout_seconds=timeout_seconds, expect_response=True)

    def notify(self, message: dict[str, Any]) -> None:
        self._post(message, timeout_seconds=5, expect_response=False)

    def close(self) -> None:
        if not self.session_id:
            return
        request = Request(self.endpoint, method="DELETE", headers=self._headers(message=None))
        try:
            with urlopen(request, timeout=3):
                pass
        except (HTTPError, URLError, TimeoutError):
            pass
        self.session_id = None

    def _post(self, message: dict[str, Any], *, timeout_seconds: float, expect_response: bool) -> dict[str, Any]:
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(payload) > MAX_MESSAGE_BYTES:
            raise McpProtocolError("mcp_message_too_large")
        request = Request(
            self.endpoint,
            data=payload,
            method="POST",
            headers=self._headers(message=message),
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                session = response.headers.get("Mcp-Session-Id")
                if session:
                    _validate_session_id(session)
                    self.session_id = session
                body = response.read(MAX_MESSAGE_BYTES + 1)
                if len(body) > MAX_MESSAGE_BYTES:
                    raise McpProtocolError("mcp_response_too_large")
                if not expect_response and response.status == 202:
                    return {"jsonrpc": "2.0", "result": {}}
                content_type = response.headers.get_content_type()
        except HTTPError as exc:
            if exc.code == 404 and self.session_id:
                self.session_id = None
            raise McpError(f"mcp_http_status_{exc.code}") from exc
        except (URLError, TimeoutError) as exc:
            if isinstance(getattr(exc, "reason", None), TimeoutError):
                raise McpTimeoutError("mcp_request_timeout") from exc
            raise McpError("mcp_http_unavailable") from exc
        if content_type == "text/event-stream":
            return _parse_sse(body, request_id=message.get("id"))
        try:
            value = json.loads(body or b"{}")
        except json.JSONDecodeError as exc:
            raise McpProtocolError("mcp_malformed_jsonrpc") from exc
        if not isinstance(value, dict):
            raise McpProtocolError("mcp_jsonrpc_object_required")
        return value

    def _headers(self, *, message: dict[str, Any] | None) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Origin": "http://127.0.0.1",
            "MCP-Protocol-Version": self.protocol_version,
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        if self.credential_ref:
            secret = os.getenv(self.credential_ref)
            if not secret:
                raise McpError("mcp_credential_reference_unresolved")
            headers["Authorization"] = f"Bearer {secret}"
        if message:
            method = str(message.get("method", ""))
            _safe_header(method)
            if method:
                headers["Mcp-Method"] = method
        return headers


@dataclass
class McpClient:
    transport: McpTransport
    request_timeout_seconds: float = 10
    _next_id: int = 1
    catalog: McpCapabilityCatalog | None = None
    _request_lock: threading.RLock = field(
        default_factory=threading.RLock, init=False, repr=False
    )

    def initialize(self) -> McpCapabilityCatalog:
        response = self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "Klara", "version": "0.1.0"},
            },
        )
        result = _result(response)
        version = str(result.get("protocolVersion", ""))
        if version != PROTOCOL_VERSION:
            raise McpProtocolError("mcp_protocol_version_unsupported")
        capabilities = result.get("capabilities", {})
        server_info = result.get("serverInfo", {})
        if not isinstance(capabilities, dict) or not isinstance(server_info, dict):
            raise McpProtocolError("mcp_initialize_result_invalid")
        self.transport.notify({"jsonrpc": "2.0", "method": "notifications/initialized"})
        tools = self.list_items("tools") if "tools" in capabilities else ()
        resources = self.list_items("resources") if "resources" in capabilities else ()
        prompts = self.list_items("prompts") if "prompts" in capabilities else ()
        self.catalog = McpCapabilityCatalog(
            protocol_version=version,
            server_name=str(server_info.get("name", "unknown"))[:160],
            server_version=str(server_info.get("version", "unknown"))[:80],
            capabilities=_bounded_object(capabilities),
            tools=tools,
            resources=resources,
            prompts=prompts,
        )
        return self.catalog

    def list_items(self, kind: str) -> tuple[dict[str, Any], ...]:
        if kind not in {"tools", "resources", "prompts"}:
            raise McpProtocolError("mcp_unknown_catalog_kind")
        result = _result(self._request(f"{kind}/list", {}))
        values = result.get(kind, [])
        if not isinstance(values, list) or len(values) > 1000:
            raise McpProtocolError("mcp_catalog_invalid_or_oversized")
        return tuple(_bounded_object(item) for item in values if isinstance(item, dict))

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return _result(self._request("tools/call", {"name": name, "arguments": arguments}))

    def read_resource(self, uri: str) -> dict[str, Any]:
        return _result(self._request("resources/read", {"uri": uri}))

    def get_prompt(self, name: str, arguments: dict[str, str]) -> dict[str, Any]:
        return _result(self._request("prompts/get", {"name": name, "arguments": arguments}))

    def ping(self) -> None:
        _result(self._request("ping", {}))

    def close(self) -> None:
        self.transport.close()

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        # One client owns one ordered JSON-RPC stream and (for HTTP) one
        # session. Serializing requests prevents response and session races.
        with self._request_lock:
            request_id = self._next_id
            self._next_id += 1
            message = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
            try:
                response = self.transport.request(
                    message, timeout_seconds=self.request_timeout_seconds
                )
            except McpTimeoutError:
                try:
                    self.transport.notify(
                        _cancel_notification(request_id, "timeout")
                    )
                except McpError:
                    # The request still fails as a timeout. Cancellation is
                    # best effort when the transport itself is unavailable.
                    pass
                raise
            if response.get("jsonrpc") != "2.0" or response.get("id") != request_id:
                raise McpProtocolError("mcp_jsonrpc_response_mismatch")
            return response


def build_transport(config: McpServerConfig) -> McpTransport:
    if config.transport is McpTransportKind.STDIO:
        return StdioTransport(config)
    if config.transport is McpTransportKind.STREAMABLE_HTTP:
        return StreamableHttpTransport(config)
    raise McpProtocolError("mcp_transport_unknown")


def _result(response: dict[str, Any]) -> dict[str, Any]:
    if "error" in response:
        error = response.get("error")
        code = error.get("code") if isinstance(error, dict) else "unknown"
        raise McpError(f"mcp_remote_error_{code}")
    result = response.get("result")
    if not isinstance(result, dict):
        raise McpProtocolError("mcp_result_object_required")
    return result


def _parse_sse(body: bytes, *, request_id: object) -> dict[str, Any]:
    for event in body.decode("utf-8", errors="replace").split("\n\n"):
        data = "\n".join(line[5:].lstrip() for line in event.splitlines() if line.startswith("data:"))
        if not data:
            continue
        try:
            value = json.loads(data)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("id") == request_id:
            return value
    raise McpProtocolError("mcp_sse_response_missing")


def _cancel_notification(request_id: object, reason: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": request_id, "reason": reason}}


def _minimal_environment(refs: dict[str, str]) -> dict[str, str]:
    keep = ("SystemRoot", "WINDIR", "PATH", "PATHEXT", "TEMP", "TMP")
    environment = {name: os.environ[name] for name in keep if name in os.environ}
    for child_name, source_name in refs.items():
        _safe_env_name(child_name)
        _safe_env_name(source_name)
        value = os.getenv(source_name)
        if value is None:
            raise McpError("mcp_environment_reference_unresolved")
        environment[child_name] = value
    return environment


def _resolve_executable(command: str) -> str:
    clean = command.strip()
    if not clean or any(character in clean for character in ("\0", "\r", "\n")):
        raise McpProtocolError("mcp_stdio_command_invalid")
    if Path(clean).name != clean and not Path(clean).is_absolute():
        raise McpProtocolError("mcp_stdio_command_must_be_name_or_absolute")
    return clean


def _safe_env_name(value: str) -> None:
    if not value or not value.replace("_", "A").isalnum() or value[0].isdigit():
        raise McpProtocolError("mcp_environment_reference_invalid")


def _safe_header(value: str) -> None:
    if any(ord(character) < 32 or ord(character) > 126 for character in value):
        raise McpProtocolError("mcp_header_value_invalid")


def _validate_session_id(value: str) -> None:
    if not value or any(ord(character) < 0x21 or ord(character) > 0x7E for character in value):
        raise McpProtocolError("mcp_session_id_invalid")


def _bounded_object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    encoded = json.dumps(value, ensure_ascii=False, default=str)
    if len(encoded) > 12000:
        raise McpProtocolError("mcp_observation_too_large")
    return json.loads(encoded)
