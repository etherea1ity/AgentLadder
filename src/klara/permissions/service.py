"""Fail-closed permission policy and approval lifecycle."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hashlib
import json

from klara.permissions.models import (
    PermissionAction,
    PermissionAuditEvent,
    PermissionDecision,
    PermissionEffect,
    PermissionGrant,
    PermissionGrantStatus,
    PermissionRequest,
    PermissionRequestStatus,
    PermissionRisk,
    PermissionScope,
    new_permission_audit_id,
    new_permission_grant_id,
    new_permission_request_id,
    utc_now_iso,
)
from klara.permissions.repository import SQLitePermissionRepository


class PermissionNotFoundError(LookupError):
    """Raised without disclosing another tenant's records."""


class PermissionValidationError(ValueError):
    """Raised when an approval would exceed the requested authority."""


class PermissionService:
    """Evaluate actions and manage explicit, scoped user authority."""

    REQUEST_TTL_SECONDS = 24 * 60 * 60
    MAX_GRANT_SECONDS = 30 * 24 * 60 * 60

    def __init__(self, repository: SQLitePermissionRepository) -> None:
        self.repository = repository

    def evaluate(self, *, scope: PermissionScope, action: PermissionAction) -> PermissionDecision:
        """Allow frozen low-risk local actions or require an exact active grant."""

        now = datetime.now(UTC)
        matching: list[PermissionGrant] = []
        for grant in self.repository.list_grants(scope):
            normalized = self._normalize_grant_status(grant, now=now)
            if normalized.status is not PermissionGrantStatus.ACTIVE:
                continue
            if _grant_matches(normalized, scope=scope, action=action):
                matching.append(normalized)
        denials = [grant for grant in matching if grant.effect is PermissionEffect.DENY]
        if denials:
            grant = denials[0]
            self._audit(scope, action, "evaluated", "denied_by_grant", grant_id=grant.grant_id)
            return PermissionDecision(
                allowed=False,
                reason="permission_denied",
                action=action,
                grant_id=grant.grant_id,
                effect=PermissionEffect.DENY,
            )

        allows = [grant for grant in matching if grant.effect is not PermissionEffect.DENY]
        if allows:
            grant = sorted(allows, key=_grant_precedence)[0]
            if grant.effect is PermissionEffect.ALLOW_ONCE:
                consumed = self.repository.consume_once(scope, grant.grant_id)
                if consumed is None:
                    self._audit(scope, action, "evaluated", "grant_race_denied", grant_id=grant.grant_id)
                    return self._request_required(scope=scope, action=action)
            self._audit(
                scope,
                action,
                "evaluated",
                "allowed_by_grant",
                grant_id=grant.grant_id,
                details={"effect": grant.effect.value},
            )
            return PermissionDecision(
                allowed=True,
                reason="permission_granted",
                action=action,
                grant_id=grant.grant_id,
                effect=grant.effect,
            )

        if _frozen_policy_allows(action):
            self._audit(scope, action, "evaluated", "allowed_by_policy")
            return PermissionDecision(
                allowed=True,
                reason="permission_low_risk_policy",
                action=action,
            )
        return self._request_required(scope=scope, action=action)

    def record_resolution_failure(
        self, *, scope: PermissionScope, tool_name: str, reason: str
    ) -> PermissionDecision:
        """Audit an unresolvable action and deny without manufacturing a resource."""

        event = PermissionAuditEvent(
            audit_id=new_permission_audit_id(),
            tenant_id=scope.tenant_id,
            actor_id=scope.actor_id,
            agent_id=scope.agent_id,
            task_id=scope.task_id,
            operation="resolution_failed",
            decision="denied_fail_closed",
            occurred_at=utc_now_iso(),
            tool_name=tool_name,
            details={"reason": reason},
        )
        self.repository.append_audit(event)
        return PermissionDecision(allowed=False, reason=reason)

    def decide_request(
        self,
        *,
        scope: PermissionScope,
        request_id: str,
        effect: PermissionEffect,
        expires_seconds: int,
        parent_grant_id: str | None = None,
    ) -> PermissionGrant:
        """Apply one explicit owner decision and create exact scoped authority."""

        request = self.repository.get_request(scope, request_id)
        if request is None:
            raise PermissionNotFoundError("permission_request_not_found")
        if request.status is not PermissionRequestStatus.PENDING:
            raise PermissionValidationError("permission_request_already_decided")
        if effect is PermissionEffect.ALLOW_TASK and not request.scope.task_id:
            raise PermissionValidationError("permission_task_scope_required")
        if expires_seconds < 1 or expires_seconds > self.MAX_GRANT_SECONDS:
            raise PermissionValidationError("permission_expiry_out_of_range")
        now = datetime.now(UTC)
        grant_scope = request.scope
        if effect is not PermissionEffect.ALLOW_TASK:
            grant_scope = replace(request.scope, task_id=None)
        grant = PermissionGrant(
            grant_id=new_permission_grant_id(),
            request_id=request.request_id,
            effect=effect,
            status=PermissionGrantStatus.ACTIVE,
            scope=grant_scope,
            action=request.action,
            created_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=expires_seconds)).isoformat(),
            remaining_uses=1 if effect is PermissionEffect.ALLOW_ONCE else None,
            parent_grant_id=parent_grant_id,
        )
        if parent_grant_id is not None:
            parent = self.repository.get_grant(scope, parent_grant_id)
            if parent is None:
                raise PermissionNotFoundError("permission_parent_grant_not_found")
            _require_attenuation(parent, grant)
        decided_status = (
            PermissionRequestStatus.DENIED
            if effect is PermissionEffect.DENY
            else PermissionRequestStatus.APPROVED
        )
        self.repository.save_grant(grant)
        self.repository.save_request(
            replace(
                request,
                status=decided_status,
                decision_effect=effect,
                updated_at=now.isoformat(),
            )
        )
        self._audit(
            request.scope,
            request.action,
            "request_decided",
            effect.value,
            request_id=request.request_id,
            grant_id=grant.grant_id,
            details={"expires_at": grant.expires_at, "parent_grant_id": parent_grant_id},
        )
        return grant

    def delegate(
        self,
        *,
        scope: PermissionScope,
        parent_grant_id: str,
        child_scope: PermissionScope,
        effect: PermissionEffect,
        expires_seconds: int,
    ) -> PermissionGrant:
        """Create child authority that cannot exceed the parent grant."""

        if expires_seconds < 1 or expires_seconds > self.MAX_GRANT_SECONDS:
            raise PermissionValidationError("permission_expiry_out_of_range")
        parent = self.repository.get_grant(scope, parent_grant_id)
        if parent is None:
            raise PermissionNotFoundError("permission_parent_grant_not_found")
        now = datetime.now(UTC)
        child = PermissionGrant(
            grant_id=new_permission_grant_id(),
            request_id=None,
            effect=effect,
            status=PermissionGrantStatus.ACTIVE,
            scope=child_scope,
            action=parent.action,
            created_at=now.isoformat(),
            expires_at=(now + timedelta(seconds=expires_seconds)).isoformat(),
            remaining_uses=1 if effect is PermissionEffect.ALLOW_ONCE else None,
            parent_grant_id=parent.grant_id,
        )
        _require_attenuation(parent, child)
        self.repository.save_grant(child)
        self._audit(
            scope,
            parent.action,
            "grant_delegated",
            effect.value,
            grant_id=child.grant_id,
            details={"parent_grant_id": parent.grant_id, "child_agent_id": child_scope.agent_id},
        )
        return child

    def revoke_grant(self, *, scope: PermissionScope, grant_id: str) -> PermissionGrant:
        grant = self.repository.get_grant(scope, grant_id)
        if grant is None:
            raise PermissionNotFoundError("permission_grant_not_found")
        if grant.status is not PermissionGrantStatus.ACTIVE:
            raise PermissionValidationError("permission_grant_not_active")
        revoked = replace(
            grant,
            status=PermissionGrantStatus.REVOKED,
            revoked_at=utc_now_iso(),
        )
        self.repository.save_grant(revoked)
        self._audit(
            scope,
            grant.action,
            "grant_revoked",
            "revoked",
            grant_id=grant.grant_id,
        )
        return revoked

    def list_state(self, *, scope: PermissionScope) -> dict[str, object]:
        now = datetime.now(UTC)
        requests = [self._normalize_request_status(item, now=now) for item in self.repository.list_requests(scope)]
        grants = [self._normalize_grant_status(item, now=now) for item in self.repository.list_grants(scope)]
        return {
            "schema_version": "klara.permissions-state.v1",
            "requests": [item.to_owner_dict() for item in requests],
            "grants": [item.to_owner_dict() for item in grants],
            "audit": [item.to_owner_dict() for item in self.repository.list_audit(scope)],
        }

    def _request_required(
        self, *, scope: PermissionScope, action: PermissionAction
    ) -> PermissionDecision:
        fingerprint = _request_fingerprint(scope, action)
        now = datetime.now(UTC)
        request = self.repository.find_pending(scope, fingerprint)
        if request is not None and _parse_time(request.expires_at) <= now:
            request = replace(
                request,
                status=PermissionRequestStatus.EXPIRED,
                updated_at=now.isoformat(),
            )
            self.repository.save_request(request)
            request = None
        if request is None:
            request = PermissionRequest(
                request_id=new_permission_request_id(),
                fingerprint=fingerprint,
                scope=scope,
                action=action,
                status=PermissionRequestStatus.PENDING,
                created_at=now.isoformat(),
                updated_at=now.isoformat(),
                expires_at=(now + timedelta(seconds=self.REQUEST_TTL_SECONDS)).isoformat(),
            )
        else:
            request = replace(
                request,
                repeated_count=request.repeated_count + 1,
                updated_at=now.isoformat(),
            )
        self.repository.save_request(request)
        self._audit(
            scope,
            action,
            "approval_requested",
            "blocked_pending_approval",
            request_id=request.request_id,
            details={"repeated_count": request.repeated_count},
        )
        return PermissionDecision(
            allowed=False,
            reason="permission_approval_required",
            action=action,
            request_id=request.request_id,
        )

    def _normalize_request_status(
        self, request: PermissionRequest, *, now: datetime
    ) -> PermissionRequest:
        if request.status is PermissionRequestStatus.PENDING and _parse_time(request.expires_at) <= now:
            request = replace(request, status=PermissionRequestStatus.EXPIRED, updated_at=now.isoformat())
            self.repository.save_request(request)
        return request

    def _normalize_grant_status(
        self, grant: PermissionGrant, *, now: datetime
    ) -> PermissionGrant:
        if grant.status is PermissionGrantStatus.ACTIVE and _parse_time(grant.expires_at) <= now:
            grant = replace(grant, status=PermissionGrantStatus.EXPIRED)
            self.repository.save_grant(grant)
        return grant

    def _audit(
        self,
        scope: PermissionScope,
        action: PermissionAction,
        operation: str,
        decision: str,
        *,
        request_id: str | None = None,
        grant_id: str | None = None,
        details: dict[str, object] | None = None,
    ) -> None:
        self.repository.append_audit(
            PermissionAuditEvent(
                audit_id=new_permission_audit_id(),
                tenant_id=scope.tenant_id,
                actor_id=scope.actor_id,
                agent_id=scope.agent_id,
                task_id=scope.task_id,
                operation=operation,
                decision=decision,
                occurred_at=utc_now_iso(),
                request_id=request_id,
                grant_id=grant_id,
                tool_name=action.tool_name,
                capability=action.capability,
                resource_type=action.resource_type,
                resource=action.resource,
                arguments_sha256=action.arguments_sha256,
                details=dict(details or {}),
            )
        )


def _frozen_policy_allows(action: PermissionAction) -> bool:
    return (
        action.risk is PermissionRisk.LOW
        and not action.destructive
        and not action.externally_consequential
    )


def _grant_matches(
    grant: PermissionGrant, *, scope: PermissionScope, action: PermissionAction
) -> bool:
    if grant.scope.tenant_id != scope.tenant_id or grant.scope.actor_id != scope.actor_id:
        return False
    if grant.scope.agent_id != scope.agent_id:
        return False
    if grant.effect is PermissionEffect.ALLOW_TASK and grant.scope.task_id != scope.task_id:
        return False
    if grant.scope.task_id is not None and grant.scope.task_id != scope.task_id:
        return False
    expected = grant.action
    return (
        expected.tool_name == action.tool_name
        and expected.capability == action.capability
        and expected.side_effect is action.side_effect
        and expected.resource_type == action.resource_type
        and expected.resource == action.resource
        and expected.arguments_sha256 == action.arguments_sha256
        and _risk_rank(action.risk) <= _risk_rank(expected.risk)
        and (not action.destructive or expected.destructive)
        and (not action.externally_consequential or expected.externally_consequential)
    )


def _require_attenuation(parent: PermissionGrant, child: PermissionGrant) -> None:
    if parent.status is not PermissionGrantStatus.ACTIVE:
        raise PermissionValidationError("permission_parent_grant_not_active")
    if _parse_time(parent.expires_at) <= datetime.now(UTC):
        raise PermissionValidationError("permission_parent_grant_expired")
    if parent.effect in {PermissionEffect.DENY, PermissionEffect.ALLOW_ONCE}:
        raise PermissionValidationError("permission_parent_grant_not_delegable")
    if child.effect is PermissionEffect.ALLOW_STANDING and parent.effect is not PermissionEffect.ALLOW_STANDING:
        raise PermissionValidationError("permission_child_effect_exceeds_parent")
    if child.effect is PermissionEffect.DENY:
        raise PermissionValidationError("permission_child_deny_not_delegation")
    if child.scope.tenant_id != parent.scope.tenant_id or child.scope.actor_id != parent.scope.actor_id:
        raise PermissionValidationError("permission_child_identity_exceeds_parent")
    if parent.scope.task_id is not None and child.scope.task_id != parent.scope.task_id:
        raise PermissionValidationError("permission_child_task_exceeds_parent")
    if _parse_time(child.expires_at) > _parse_time(parent.expires_at):
        raise PermissionValidationError("permission_child_expiry_exceeds_parent")
    if child.action != parent.action:
        raise PermissionValidationError("permission_child_action_exceeds_parent")


def _grant_precedence(grant: PermissionGrant) -> tuple[int, str]:
    order = {
        PermissionEffect.ALLOW_ONCE: 0,
        PermissionEffect.ALLOW_TASK: 1,
        PermissionEffect.ALLOW_STANDING: 2,
        PermissionEffect.DENY: -1,
    }
    return order[grant.effect], grant.created_at


def _risk_rank(risk: PermissionRisk) -> int:
    return {
        PermissionRisk.LOW: 0,
        PermissionRisk.MEDIUM: 1,
        PermissionRisk.HIGH: 2,
        PermissionRisk.CRITICAL: 3,
    }[risk]


def _request_fingerprint(scope: PermissionScope, action: PermissionAction) -> str:
    value = {
        "scope": scope.to_public_dict(),
        "action": action.to_public_dict(),
    }
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
