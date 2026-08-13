"""Owner-scoped permission request, grant, revocation, and audit API."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from apps.api.dependencies import get_permission_scope, get_permission_service
from apps.api.schemas import (
    PermissionDecisionRequest,
    PermissionGrantResponse,
    PermissionStateResponse,
)
from klara.permissions import (
    PermissionEffect,
    PermissionNotFoundError,
    PermissionScope,
    PermissionService,
    PermissionValidationError,
)


router = APIRouter(prefix="/api/permissions", tags=["permissions"])


@router.get("", response_model=PermissionStateResponse)
def list_permissions(
    service: PermissionService = Depends(get_permission_service),
    scope: PermissionScope = Depends(get_permission_scope),
) -> dict[str, object]:
    return service.list_state(scope=scope)


@router.post("/requests/{request_id}/decision", response_model=PermissionGrantResponse)
def decide_permission_request(
    request_id: str,
    request: PermissionDecisionRequest,
    service: PermissionService = Depends(get_permission_service),
    scope: PermissionScope = Depends(get_permission_scope),
) -> dict[str, object]:
    try:
        grant = service.decide_request(
            scope=scope,
            request_id=request_id,
            effect=PermissionEffect(request.effect),
            expires_seconds=request.expires_seconds,
            parent_grant_id=request.parent_grant_id,
        )
    except PermissionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="permission_request_not_found") from exc
    except PermissionValidationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return grant.to_owner_dict()


@router.post("/grants/{grant_id}/revoke", response_model=PermissionGrantResponse)
def revoke_permission_grant(
    grant_id: str,
    service: PermissionService = Depends(get_permission_service),
    scope: PermissionScope = Depends(get_permission_scope),
) -> dict[str, object]:
    try:
        grant = service.revoke_grant(scope=scope, grant_id=grant_id)
    except PermissionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="permission_grant_not_found") from exc
    except PermissionValidationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return grant.to_owner_dict()
