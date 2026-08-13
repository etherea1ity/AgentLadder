"""Small signed bearer-token boundary for the local production runtime."""

from __future__ import annotations

from dataclasses import dataclass
import base64
from datetime import UTC, datetime
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import time
from typing import Callable, Iterable


TOKEN_SCHEMA = "klara.auth-token.v1"
_IDENTIFIER = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$")
_ROLES = frozenset({"owner", "operator", "worker", "evaluator", "admin"})


class AuthError(ValueError):
    """Raised when a credential or requested authority is invalid."""


@dataclass(frozen=True)
class Principal:
    """Authenticated identity projected into every tenant-owned operation."""

    tenant_id: str
    user_id: str
    roles: frozenset[str]
    token_id: str
    expires_at: int

    def __post_init__(self) -> None:
        _validate_identifier(self.tenant_id, "tenant_id")
        _validate_identifier(self.user_id, "user_id")
        _validate_identifier(self.token_id, "token_id")
        if not self.roles or not self.roles.issubset(_ROLES):
            raise AuthError("roles contain unsupported authority")

    def has_any_role(self, roles: Iterable[str]) -> bool:
        """Return whether this principal has one requested role or admin."""

        requested = set(roles)
        return "admin" in self.roles or bool(self.roles & requested)

    def require(self, *roles: str) -> None:
        """Reject an operation unless one requested role is present."""

        if not self.has_any_role(roles):
            raise AuthError("insufficient_role")

    def to_public_dict(self) -> dict[str, object]:
        """Return safe identity metadata without the bearer or token id."""

        return {
            "schema_version": "klara.principal.v1",
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "roles": sorted(self.roles),
            "expires_at": datetime.fromtimestamp(self.expires_at, UTC).isoformat(),
        }


@dataclass(frozen=True)
class AuthConfig:
    """Frozen authentication configuration."""

    mode: str
    signing_key: bytes
    issuer: str = "klara"
    audience: str = "klara-production-api"
    token_ttl_seconds: int = 3600

    def __post_init__(self) -> None:
        if self.mode not in {"development", "production"}:
            raise AuthError("auth mode must be development or production")
        if len(self.signing_key) < 32:
            raise AuthError("auth signing key must contain at least 32 bytes")
        if not 60 <= self.token_ttl_seconds <= 86400:
            raise AuthError("token ttl must be between 60 and 86400 seconds")

    @classmethod
    def from_env(cls) -> "AuthConfig":
        """Load configuration, refusing implicit credentials in production."""

        mode = os.getenv("KLARA_AUTH_MODE", "development").strip().lower()
        configured = os.getenv("KLARA_AUTH_SIGNING_KEY", "").encode("utf-8")
        if not configured:
            if mode == "production":
                raise AuthError("KLARA_AUTH_SIGNING_KEY is required in production")
            workstation_binding = str(Path.cwd().resolve()).encode("utf-8")
            configured = hashlib.sha256(b"klara-local-development\0" + workstation_binding).digest()
        ttl = int(os.getenv("KLARA_AUTH_TOKEN_TTL_SECONDS", "3600"))
        return cls(mode=mode, signing_key=configured, token_ttl_seconds=ttl)


class AuthService:
    """Issue and verify compact HMAC credentials without logging their value."""

    def __init__(self, config: AuthConfig, *, clock: Callable[[], float] = time.time) -> None:
        self.config = config
        self._clock = clock

    def issue(
        self,
        *,
        tenant_id: str,
        user_id: str,
        roles: Iterable[str],
        ttl_seconds: int | None = None,
    ) -> str:
        """Issue one bounded bearer token for an already authenticated identity."""

        _validate_identifier(tenant_id, "tenant_id")
        _validate_identifier(user_id, "user_id")
        normalized_roles = frozenset(str(role) for role in roles)
        if not normalized_roles or not normalized_roles.issubset(_ROLES):
            raise AuthError("roles contain unsupported authority")
        ttl = ttl_seconds or self.config.token_ttl_seconds
        if not 60 <= ttl <= self.config.token_ttl_seconds:
            raise AuthError("requested token ttl exceeds configured bound")
        now = int(self._clock())
        header = {"alg": "HS256", "typ": "KAT", "v": 1}
        payload = {
            "schema_version": TOKEN_SCHEMA,
            "iss": self.config.issuer,
            "aud": self.config.audience,
            "sub": user_id,
            "tenant": tenant_id,
            "roles": sorted(normalized_roles),
            "iat": now,
            "exp": now + ttl,
            "jti": secrets.token_hex(16),
        }
        signing_input = f"{_encode(header)}.{_encode(payload)}"
        signature = hmac.new(
            self.config.signing_key,
            signing_input.encode("ascii"),
            hashlib.sha256,
        ).digest()
        return f"{signing_input}.{_b64url(signature)}"

    def verify_bearer(self, authorization: str | None) -> Principal:
        """Verify one Authorization header and return its scoped principal."""

        if not authorization or not authorization.startswith("Bearer "):
            raise AuthError("missing_bearer")
        token = authorization[7:].strip()
        parts = token.split(".")
        if len(parts) != 3 or any(not part for part in parts):
            raise AuthError("malformed_bearer")
        signing_input = f"{parts[0]}.{parts[1]}"
        expected = hmac.new(
            self.config.signing_key,
            signing_input.encode("ascii"),
            hashlib.sha256,
        ).digest()
        try:
            supplied = _decode_bytes(parts[2])
            header = _decode_json(parts[0])
            payload = _decode_json(parts[1])
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise AuthError("malformed_bearer") from exc
        if not hmac.compare_digest(expected, supplied):
            raise AuthError("invalid_signature")
        if header != {"alg": "HS256", "typ": "KAT", "v": 1}:
            raise AuthError("unsupported_token_header")
        now = int(self._clock())
        if payload.get("schema_version") != TOKEN_SCHEMA:
            raise AuthError("unsupported_token_schema")
        if payload.get("iss") != self.config.issuer or payload.get("aud") != self.config.audience:
            raise AuthError("invalid_token_audience")
        issued_at = int(payload.get("iat", 0))
        expires_at = int(payload.get("exp", 0))
        if issued_at > now + 30 or expires_at <= now or expires_at - issued_at > self.config.token_ttl_seconds:
            raise AuthError("expired_or_invalid_lifetime")
        return Principal(
            tenant_id=str(payload.get("tenant", "")),
            user_id=str(payload.get("sub", "")),
            roles=frozenset(str(role) for role in payload.get("roles", [])),
            token_id=str(payload.get("jti", "")),
            expires_at=expires_at,
        )


def _validate_identifier(value: str, label: str) -> None:
    if not _IDENTIFIER.fullmatch(value):
        raise AuthError(f"invalid_{label}")


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _encode(value: dict[str, object]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _b64url(raw)


def _decode_bytes(value: str) -> bytes:
    decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if _b64url(decoded) != value:
        raise ValueError("non-canonical base64url")
    return decoded


def _decode_json(value: str) -> dict[str, object]:
    parsed = json.loads(_decode_bytes(value).decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("token section must be an object")
    return parsed
