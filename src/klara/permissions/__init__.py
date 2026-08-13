"""Public permission-engine contracts."""

from klara.permissions.hook import PermissionEngineHook
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
)
from klara.permissions.repository import SQLitePermissionRepository
from klara.permissions.resolver import PermissionActionResolver, PermissionResolutionError
from klara.permissions.service import (
    PermissionNotFoundError,
    PermissionService,
    PermissionValidationError,
)

__all__ = [
    "PermissionAction",
    "PermissionActionResolver",
    "PermissionAuditEvent",
    "PermissionDecision",
    "PermissionEffect",
    "PermissionEngineHook",
    "PermissionGrant",
    "PermissionGrantStatus",
    "PermissionNotFoundError",
    "PermissionRequest",
    "PermissionRequestStatus",
    "PermissionResolutionError",
    "PermissionRisk",
    "PermissionScope",
    "PermissionService",
    "PermissionValidationError",
    "SQLitePermissionRepository",
]
