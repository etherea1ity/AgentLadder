"""Canonicalize tool actions before the permission policy sees them."""

from __future__ import annotations

import hashlib
import ipaddress
import json
from pathlib import Path
import posixpath
import re
from urllib.parse import unquote, urlsplit

from klara.core.tools import ToolCall, ToolMetadata, ToolSideEffect
from klara.permissions.models import PermissionAction, PermissionRisk


class PermissionResolutionError(ValueError):
    """Raised when capability, risk, or resource cannot be normalized safely."""


_SAFE_LOCAL_TOOLS = {
    "current_time",
    "evidence_submit",
    "skills_list",
    "skill_view",
    "memory_search",
    "todo_write",
}
_MEMORY_MUTATIONS = {"memory_remember", "memory_update", "memory_forget"}
_DESTRUCTIVE_TOOLS = {"memory_delete", "file_delete", "delete_file"}
_SHELL_NAMES = {"shell", "shell_command", "terminal", "exec", "execute_command"}
_PATH_KEYS = ("path", "file", "filename", "cwd", "workdir", "directory")
_URL_KEYS = ("url", "uri", "endpoint")
_DESTRUCTIVE_COMMAND = re.compile(
    r"(?i)(?:^|[;&|\s])(?:rm\s+-rf|del\s+/[sq]|remove-item\b.*-recurse|format\b|shutdown\b)"
)


class PermissionActionResolver:
    """Resolve a raw tool call into a stable capability/resource tuple."""

    def __init__(self, metadata_by_tool: dict[str, ToolMetadata], workspace_root: Path) -> None:
        self.metadata_by_tool = dict(metadata_by_tool)
        self.workspace_root = workspace_root.resolve()

    def resolve(self, call: ToolCall) -> PermissionAction:
        metadata = self.metadata_by_tool.get(call.name)
        if metadata is None:
            raise PermissionResolutionError("permission_unknown_tool")
        if not isinstance(metadata.side_effect, ToolSideEffect):
            raise PermissionResolutionError("permission_unknown_side_effect")
        arguments_hash = _stable_hash(call.arguments)
        capability = f"{metadata.category}.{call.name}"
        resource_type, resource = self._resource(call, metadata)
        risk, destructive, external = self._risk(call, metadata)
        return PermissionAction(
            tool_name=call.name,
            capability=capability,
            side_effect=metadata.side_effect,
            resource_type=resource_type,
            resource=resource,
            risk=risk,
            destructive=destructive,
            externally_consequential=external,
            arguments_sha256=arguments_hash,
        )

    def _resource(self, call: ToolCall, metadata: ToolMetadata) -> tuple[str, str]:
        if call.name == "web_search":
            return "network", "network:web-search"
        if call.name == "web_fetch":
            return "domain", _canonical_url_resource(_required_text(call.arguments, "url"))
        if call.name == "image_generate":
            return "provider", "provider:image-generation"
        if call.name.startswith("memory_"):
            memory_id = _optional_text(call.arguments, "memory_id")
            return "memory", f"memory:{memory_id or 'owner-scope'}"
        if call.name == "todo_write":
            return "task", "task:active-plan"
        if call.name in {"skills_list", "skill_view"}:
            name = _optional_text(call.arguments, "name")
            return "catalog", f"skills:{name or 'catalog'}"
        if call.name == "current_time":
            timezone = _optional_text(call.arguments, "timezone")
            return "clock", f"clock:{timezone or 'runtime'}"
        if call.name == "evidence_submit":
            return "run", "evidence:active-run"
        if call.name in _SHELL_NAMES or metadata.category in {"shell", "terminal"}:
            command = _required_text(call.arguments, "command")
            _reject_encoded_control(command)
            return "shell", f"shell:{hashlib.sha256(command.encode('utf-8')).hexdigest()[:24]}"
        if call.name.startswith("mcp__") or metadata.category == "mcp":
            parts = call.name.split("__", 2)
            if len(parts) < 3 or not all(part.strip() for part in parts[1:]):
                raise PermissionResolutionError("permission_unknown_mcp_resource")
            return "mcp", f"mcp:{parts[1]}/{parts[2]}"
        for key in _URL_KEYS:
            if key in call.arguments:
                return "domain", _canonical_url_resource(_required_text(call.arguments, key))
        for key in _PATH_KEYS:
            if key in call.arguments:
                return "path", self._canonical_path(_required_text(call.arguments, key))
        if metadata.side_effect in {ToolSideEffect.WRITE, ToolSideEffect.NETWORK, ToolSideEffect.CONTROL}:
            raise PermissionResolutionError("permission_unknown_resource")
        return "tool", f"tool:{call.name}"

    def _canonical_path(self, raw: str) -> str:
        decoded = _fully_unquote(raw)
        if "\x00" in decoded:
            raise PermissionResolutionError("permission_invalid_path")
        candidate = Path(decoded)
        if not candidate.is_absolute():
            candidate = self.workspace_root / candidate
        resolved = candidate.resolve(strict=False)
        try:
            relative = resolved.relative_to(self.workspace_root)
        except ValueError as exc:
            raise PermissionResolutionError("permission_path_outside_workspace") from exc
        return "workspace:/" + relative.as_posix()

    def _risk(
        self, call: ToolCall, metadata: ToolMetadata
    ) -> tuple[PermissionRisk, bool, bool]:
        destructive = call.name in _DESTRUCTIVE_TOOLS
        external = metadata.side_effect in {ToolSideEffect.NETWORK, ToolSideEffect.CONTROL}
        if call.name in _SHELL_NAMES or metadata.category in {"shell", "terminal"}:
            command = _required_text(call.arguments, "command")
            destructive = destructive or bool(_DESTRUCTIVE_COMMAND.search(command))
            return (
                PermissionRisk.CRITICAL if destructive else PermissionRisk.HIGH,
                destructive,
                True,
            )
        if destructive:
            return PermissionRisk.CRITICAL, True, external
        if metadata.side_effect is ToolSideEffect.CONTROL:
            return PermissionRisk.CRITICAL, False, True
        if metadata.requires_approval:
            return PermissionRisk.HIGH, False, external
        if call.name == "image_generate":
            return PermissionRisk.HIGH, False, True
        if metadata.side_effect is ToolSideEffect.NETWORK:
            return PermissionRisk.MEDIUM, False, True
        if call.name in _MEMORY_MUTATIONS:
            return PermissionRisk.MEDIUM, False, False
        if call.name in _SAFE_LOCAL_TOOLS or metadata.side_effect in {
            ToolSideEffect.NONE,
            ToolSideEffect.READ,
        }:
            return PermissionRisk.LOW, False, False
        if metadata.side_effect is ToolSideEffect.WRITE:
            return PermissionRisk.MEDIUM, False, False
        raise PermissionResolutionError("permission_unknown_risk")


def _canonical_url_resource(raw: str) -> str:
    value = _fully_unquote(raw)
    if "\x00" in value or "\\" in value:
        raise PermissionResolutionError("permission_invalid_url")
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise PermissionResolutionError("permission_invalid_url")
    if parsed.username or parsed.password:
        raise PermissionResolutionError("permission_url_credentials_forbidden")
    try:
        host = parsed.hostname.encode("idna").decode("ascii").lower().rstrip(".")
    except UnicodeError as exc:
        raise PermissionResolutionError("permission_invalid_url_host") from exc
    if not host or host in {"localhost", "localhost.localdomain"}:
        raise PermissionResolutionError("permission_private_url_forbidden")
    if _looks_private_host(host):
        raise PermissionResolutionError("permission_private_url_forbidden")
    try:
        port = parsed.port
    except ValueError as exc:
        raise PermissionResolutionError("permission_invalid_url_port") from exc
    authority = host
    if port is not None and port not in {80, 443}:
        authority = f"{authority}:{port}"
    normalized_path = posixpath.normpath(parsed.path or "/")
    if not normalized_path.startswith("/"):
        normalized_path = f"/{normalized_path}"
    # Query and fragment are intentionally excluded: they commonly contain tokens.
    return f"{parsed.scheme.lower()}://{authority}{normalized_path}"


def _fully_unquote(value: str) -> str:
    current = value.strip()
    if not current:
        raise PermissionResolutionError("permission_empty_resource")
    for _ in range(5):
        decoded = unquote(current)
        if decoded == current:
            return decoded
        current = decoded
    if unquote(current) != current:
        raise PermissionResolutionError("permission_overencoded_resource")
    return current


def _reject_encoded_control(value: str) -> None:
    decoded = _fully_unquote(value)
    if decoded != value.strip() or any(character in decoded for character in ("\x00", "\r", "\n")):
        raise PermissionResolutionError("permission_encoded_command_forbidden")


def _looks_private_host(host: str) -> bool:
    if host.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        # Numeric-looking hosts must be valid IP literals, not parser ambiguities.
        return bool(host) and all(character in "0123456789.:" for character in host)
    return any(
        (
            address.is_private,
            address.is_loopback,
            address.is_link_local,
            address.is_multicast,
            address.is_reserved,
            address.is_unspecified,
        )
    )


def _required_text(arguments: dict[str, object], key: str) -> str:
    value = _optional_text(arguments, key)
    if value is None:
        raise PermissionResolutionError(f"permission_missing_resource:{key}")
    return value


def _optional_text(arguments: dict[str, object], key: str) -> str | None:
    value = arguments.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise PermissionResolutionError(f"permission_invalid_resource:{key}")
    return value.strip()


def _stable_hash(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
