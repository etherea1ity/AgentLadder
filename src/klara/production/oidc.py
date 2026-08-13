"""OIDC discovery/JWKS validation without accepting provider-hidden state."""

from __future__ import annotations

from dataclasses import dataclass
import base64
import json
import time
from typing import Any, Callable, Mapping
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.hashes import SHA256

from klara.production.auth import AuthError, Principal


@dataclass(frozen=True)
class OidcConfig:
    """Pinned issuer/audience and safe role/tenant claim mappings."""

    issuer: str
    audience: str
    tenant_claim: str = "tenant_id"
    roles_claim: str = "roles"
    allowed_roles: frozenset[str] = frozenset({"owner", "operator", "worker", "evaluator", "admin"})
    discovery_timeout_seconds: float = 5.0
    clock_skew_seconds: int = 30

    def __post_init__(self) -> None:
        parsed = urlparse(self.issuer)
        if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
            raise AuthError("OIDC issuer must be an exact HTTPS origin/path")
        if not self.audience:
            raise AuthError("OIDC audience is required")


class OidcVerifier:
    """Verify RS256 access tokens from pinned OIDC discovery metadata."""

    def __init__(
        self,
        config: OidcConfig,
        *,
        fetch_json: Callable[[str, float], Mapping[str, Any]] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.config = config
        self._fetch_json = fetch_json or _fetch_json
        self._clock = clock
        self._jwks_uri: str | None = None
        self._keys: dict[str, rsa.RSAPublicKey] = {}

    def verify(self, token: str) -> Principal:
        """Return one principal after signature, audience, time, and claim checks."""

        parts = token.split(".")
        if len(parts) != 3:
            raise AuthError("malformed_oidc_token")
        try:
            header = _json_part(parts[0])
            claims = _json_part(parts[1])
            signature = _decode(parts[2])
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise AuthError("malformed_oidc_token") from exc
        if header.get("alg") != "RS256" or header.get("typ") not in {None, "JWT", "at+jwt"}:
            raise AuthError("unsupported_oidc_token_header")
        key_id = str(header.get("kid", ""))
        if not key_id:
            raise AuthError("oidc_kid_required")
        key = self._key(key_id)
        try:
            key.verify(
                signature,
                f"{parts[0]}.{parts[1]}".encode("ascii"),
                padding.PKCS1v15(),
                SHA256(),
            )
        except Exception as exc:
            raise AuthError("invalid_oidc_signature") from exc
        now = int(self._clock())
        skew = self.config.clock_skew_seconds
        if claims.get("iss") != self.config.issuer:
            raise AuthError("invalid_oidc_issuer")
        audience = claims.get("aud")
        audiences = {str(value) for value in audience} if isinstance(audience, list) else {str(audience)}
        if self.config.audience not in audiences:
            raise AuthError("invalid_oidc_audience")
        if int(claims.get("exp", 0)) <= now - skew:
            raise AuthError("expired_oidc_token")
        if int(claims.get("nbf", 0)) > now + skew or int(claims.get("iat", 0)) > now + skew:
            raise AuthError("oidc_token_not_yet_valid")
        subject = str(claims.get("sub", ""))
        tenant_id = str(claims.get(self.config.tenant_claim, ""))
        token_id = str(claims.get("jti", ""))
        raw_roles = claims.get(self.config.roles_claim, [])
        if isinstance(raw_roles, str):
            raw_roles = raw_roles.split()
        if not isinstance(raw_roles, list):
            raise AuthError("invalid_oidc_roles")
        roles = frozenset(str(role) for role in raw_roles) & self.config.allowed_roles
        if not roles:
            raise AuthError("oidc_token_has_no_allowed_role")
        return Principal(
            tenant_id=tenant_id,
            user_id=subject,
            roles=roles,
            token_id=token_id,
            expires_at=int(claims["exp"]),
        )

    def _key(self, key_id: str) -> rsa.RSAPublicKey:
        if key_id in self._keys:
            return self._keys[key_id]
        discovery_url = self.config.issuer.rstrip("/") + "/.well-known/openid-configuration"
        discovery = self._fetch_json(discovery_url, self.config.discovery_timeout_seconds)
        if discovery.get("issuer") != self.config.issuer:
            raise AuthError("OIDC discovery issuer mismatch")
        jwks_uri = str(discovery.get("jwks_uri", ""))
        if not _same_https_authority(self.config.issuer, jwks_uri):
            raise AuthError("OIDC JWKS URI must use the issuer HTTPS authority")
        jwks = self._fetch_json(jwks_uri, self.config.discovery_timeout_seconds)
        keys = jwks.get("keys", [])
        if not isinstance(keys, list) or len(keys) > 32:
            raise AuthError("invalid_oidc_jwks")
        self._keys = {
            str(item["kid"]): _rsa_key(item)
            for item in keys
            if isinstance(item, dict)
            and item.get("kty") == "RSA"
            and item.get("use", "sig") == "sig"
            and item.get("alg", "RS256") == "RS256"
            and item.get("kid")
        }
        if key_id not in self._keys:
            raise AuthError("unknown_oidc_key")
        return self._keys[key_id]


def _fetch_json(url: str, timeout: float) -> Mapping[str, Any]:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "Klara-OIDC/1"})
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise AuthError("OIDC metadata request failed")
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise AuthError("OIDC metadata too large")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise AuthError("OIDC metadata must be an object")
    return value


def _rsa_key(jwk: Mapping[str, Any]) -> rsa.RSAPublicKey:
    try:
        exponent = int.from_bytes(_decode(str(jwk["e"])), "big")
        modulus = int.from_bytes(_decode(str(jwk["n"])), "big")
        if modulus.bit_length() < 2048 or exponent < 3:
            raise ValueError("weak RSA key")
        return rsa.RSAPublicNumbers(exponent, modulus).public_key()
    except (KeyError, TypeError, ValueError) as exc:
        raise AuthError("invalid_oidc_rsa_key") from exc


def _same_https_authority(issuer: str, target: str) -> bool:
    expected = urlparse(issuer)
    actual = urlparse(target)
    return actual.scheme == "https" and actual.netloc == expected.netloc and not actual.query and not actual.fragment


def _json_part(value: str) -> dict[str, Any]:
    parsed = json.loads(_decode(value).decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("JWT part must be an object")
    return parsed


def _decode(value: str) -> bytes:
    decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    if base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != value:
        raise ValueError("non-canonical base64url")
    return decoded
