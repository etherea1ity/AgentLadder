from __future__ import annotations

import base64
import json

from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.hashes import SHA256
import pytest

from klara.production import AuthConfig, AuthError, AuthService, OidcConfig, OidcVerifier, ProductionIdentityBoundary, ProductionRepository


def test_oidc_rs256_discovery_claims_roles_and_revocation(tmp_path) -> None:
    clock = 1_700_000_000
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = private.public_key().public_numbers()
    jwk = {
        "kty": "RSA",
        "kid": "key-1",
        "use": "sig",
        "alg": "RS256",
        "n": _integer(numbers.n),
        "e": _integer(numbers.e),
    }

    def fetch(url: str, _timeout: float):
        if url.endswith("openid-configuration"):
            return {"issuer": "https://identity.example/tenant", "jwks_uri": "https://identity.example/jwks"}
        return {"keys": [jwk]}

    verifier = OidcVerifier(
        OidcConfig(issuer="https://identity.example/tenant", audience="klara-api"),
        fetch_json=fetch,
        clock=lambda: clock,
    )
    token = _sign(private, {
        "iss": "https://identity.example/tenant",
        "aud": "klara-api",
        "sub": "user-a",
        "tenant_id": "tenant-a",
        "roles": ["owner", "unknown-role"],
        "iat": clock,
        "exp": clock + 300,
        "jti": "oidc-token-1",
    })
    principal = verifier.verify(token)
    assert principal.roles == {"owner"}
    repository = ProductionRepository(tmp_path / "production.sqlite3", clock=lambda: clock)
    boundary = ProductionIdentityBoundary(
        local=AuthService(AuthConfig(mode="production", signing_key=b"l" * 32)),
        oidc=verifier,
        oidc_bearer=True,
        revocations=repository,
    )
    assert boundary.verify_authorization(f"Bearer {token}").user_id == "user-a"
    repository.revoke_token(principal, token_id=principal.token_id, expires_at=principal.expires_at, reason="logout")
    with pytest.raises(AuthError, match="credential_revoked"):
        boundary.verify_authorization(f"Bearer {token}")


def test_oidc_rejects_wrong_audience_algorithm_and_cross_authority_jwks() -> None:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    base = {
        "iss": "https://identity.example/tenant",
        "aud": "wrong-api",
        "sub": "user-a",
        "tenant_id": "tenant-a",
        "roles": ["owner"],
        "iat": 100,
        "exp": 500,
        "jti": "token-1",
    }
    numbers = private.public_key().public_numbers()
    jwk = {"kty": "RSA", "kid": "key-1", "n": _integer(numbers.n), "e": _integer(numbers.e)}
    verifier = OidcVerifier(
        OidcConfig(issuer="https://identity.example/tenant", audience="klara-api"),
        fetch_json=lambda url, timeout: ({"issuer": base["iss"], "jwks_uri": "https://identity.example/jwks"} if url.endswith("configuration") else {"keys": [jwk]}),
        clock=lambda: 200,
    )
    with pytest.raises(AuthError, match="audience"):
        verifier.verify(_sign(private, base))
    bad_header_token = _sign(private, {**base, "aud": "klara-api"}, algorithm="HS256")
    with pytest.raises(AuthError, match="unsupported"):
        verifier.verify(bad_header_token)
    cross = OidcVerifier(
        OidcConfig(issuer=base["iss"], audience="klara-api"),
        fetch_json=lambda _url, _timeout: {"issuer": base["iss"], "jwks_uri": "https://evil.example/jwks"},
        clock=lambda: 200,
    )
    with pytest.raises(AuthError, match="issuer HTTPS authority"):
        cross.verify(_sign(private, {**base, "aud": "klara-api"}))


def _sign(private, claims: dict, algorithm: str = "RS256") -> str:
    header = _encode({"alg": algorithm, "typ": "JWT", "kid": "key-1"})
    payload = _encode(claims)
    signature = private.sign(f"{header}.{payload}".encode("ascii"), padding.PKCS1v15(), SHA256())
    return f"{header}.{payload}.{_bytes(signature)}"


def _encode(value: dict) -> str:
    return _bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def _integer(value: int) -> str:
    return _bytes(value.to_bytes((value.bit_length() + 7) // 8, "big"))


def _bytes(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")
