"""PreToolUse integration for the durable permission engine."""

from __future__ import annotations

from dataclasses import replace

from klara.core.hooks import HookDecision, PreToolUseContext
from klara.permissions.models import PermissionDecision, PermissionScope
from klara.permissions.resolver import PermissionActionResolver, PermissionResolutionError
from klara.permissions.service import PermissionService


class PermissionEngineHook:
    """Fail closed before any selected tool crosses the execution boundary."""

    def __init__(
        self,
        *,
        service: PermissionService,
        resolver: PermissionActionResolver,
        scope: PermissionScope,
    ) -> None:
        self.service = service
        self.resolver = resolver
        self.scope = scope

    def on_pre_tool_use(self, context: PreToolUseContext) -> HookDecision:
        scope = self.scope
        if scope.task_id is None:
            scope = replace(scope, task_id=context.run_id)
        try:
            action = self.resolver.resolve(context.tool_call)
            decision = self.service.evaluate(scope=scope, action=action)
        except PermissionResolutionError as exc:
            decision = self.service.record_resolution_failure(
                scope=scope,
                tool_name=context.tool_call.name,
                reason=str(exc),
            )
        except Exception:
            # A permission component failure must never become authority.
            try:
                decision = self.service.record_resolution_failure(
                    scope=scope,
                    tool_name=context.tool_call.name,
                    reason="permission_engine_failure",
                )
            except Exception:
                decision = PermissionDecision(
                    allowed=False,
                    reason="permission_engine_failure",
                )
        return HookDecision(
            allowed=decision.allowed,
            reason=decision.reason,
            public_metadata={"permission": decision.to_public_dict()},
        )
