from __future__ import annotations

import pytest

from klara.production import AuthConfig, AuthError, AuthService


def test_signed_token_round_trip_tamper_and_expiry() -> None:
    clock = [1_700_000_000.0]
    service = AuthService(
        AuthConfig(mode="production", signing_key=b"x" * 32, token_ttl_seconds=120),
        clock=lambda: clock[0],
    )
    token = service.issue(tenant_id="tenant-a", user_id="user-a", roles=("owner",))
    principal = service.verify_bearer(f"Bearer {token}")
    assert principal.tenant_id == "tenant-a"
    assert principal.user_id == "user-a"
    assert principal.roles == {"owner"}
    assert "token_id" not in principal.to_public_dict()

    header, payload, signature = token.split(".")
    replacement = "A" if signature[0] != "A" else "B"
    with pytest.raises(AuthError, match="invalid_signature"):
        service.verify_bearer(f"Bearer {header}.{payload}.{replacement}{signature[1:]}")
    with pytest.raises(AuthError, match="malformed"):
        service.verify_bearer(f"Bearer {token}=")
    clock[0] += 121
    with pytest.raises(AuthError, match="expired"):
        service.verify_bearer(f"Bearer {token}")


def test_production_mode_refuses_implicit_signing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KLARA_AUTH_MODE", "production")
    monkeypatch.delenv("KLARA_AUTH_SIGNING_KEY", raising=False)
    with pytest.raises(AuthError, match="required in production"):
        AuthConfig.from_env()


def test_role_attenuation_is_explicit() -> None:
    service = AuthService(AuthConfig(mode="development", signing_key=b"y" * 32))
    token = service.issue(tenant_id="tenant-a", user_id="user-a", roles=("owner",))
    principal = service.verify_bearer(f"Bearer {token}")
    principal.require("owner")
    with pytest.raises(AuthError, match="insufficient_role"):
        principal.require("worker")
