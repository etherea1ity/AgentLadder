"""Unify local signed tokens and deployment OIDC tokens with revocation checks."""

from __future__ import annotations

from typing import Protocol

from klara.production.auth import AuthError, AuthService, Principal
from klara.production.oidc import OidcVerifier


class RevocationStore(Protocol):
    def is_token_revoked(self, tenant_id: str, token_id: str) -> bool:
        """Return whether a token id is revoked inside its tenant."""


class ProductionIdentityBoundary:
    """Select an explicit token scheme and enforce persisted revocation."""

    def __init__(
        self,
        *,
        local: AuthService,
        revocations: RevocationStore,
        oidc: OidcVerifier | None = None,
        oidc_bearer: bool = False,
    ) -> None:
        self.local = local
        self.oidc = oidc
        self.revocations = revocations
        self.oidc_bearer = oidc_bearer

    def verify_authorization(self, authorization: str | None) -> Principal:
        """Verify `Bearer` local tokens or explicit `OIDC` deployment tokens."""

        if not authorization:
            raise AuthError("missing_bearer")
        if authorization.startswith("Bearer ") and self.oidc_bearer and self.oidc is not None:
            principal = self.oidc.verify(authorization[7:].strip())
        elif authorization.startswith("Bearer "):
            principal = self.local.verify_bearer(authorization)
        elif authorization.startswith("Klara "):
            principal = self.local.verify_bearer("Bearer " + authorization[6:].strip())
        else:
            raise AuthError("unsupported_authorization_scheme")
        if self.revocations.is_token_revoked(principal.tenant_id, principal.token_id):
            raise AuthError("credential_revoked")
        return principal
