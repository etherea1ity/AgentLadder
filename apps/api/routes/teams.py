from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from apps.api.dependencies import get_permission_scope, get_team_scope, get_team_service
from apps.api.schemas import CreateTeammateRequest, CreateWorktreeRequest, DelegateAuthorityRequest, SpawnSubagentRequest, TeamMessageRequest, TeamTaskClaimNextRequest, TeamTaskClaimRequest
from klara.permissions import PermissionEffect, PermissionScope
from klara.teams import MessageKind, OneShotRequest, TeamNotFoundError, TeamPermissionRequired, TeamScope, TeamService, TeamValidationError


router = APIRouter(prefix="/api/teams", tags=["teams"])


@router.get("")
def team_state(service: TeamService = Depends(get_team_service), scope: TeamScope = Depends(get_team_scope)):
    return service.list_state(scope=scope)


@router.post("/teammates")
def create_teammate(request: CreateTeammateRequest, service: TeamService = Depends(get_team_service), scope: TeamScope = Depends(get_team_scope), permission_scope: PermissionScope = Depends(get_permission_scope)):
    return _guarded(lambda: {"schema_version": "klara.team-agent.v1", "agent": service.create_teammate(scope=scope, permission_scope=permission_scope, name=request.name, role=request.role, capability_names=tuple(request.capability_names)).to_public_dict()})


@router.post("/subagents")
def spawn_subagent(request: SpawnSubagentRequest, service: TeamService = Depends(get_team_service), scope: TeamScope = Depends(get_team_scope), permission_scope: PermissionScope = Depends(get_permission_scope)):
    value = OneShotRequest(title=request.title, instructions=request.instructions, capability_names=tuple(request.capability_names), parent_task_id=request.parent_task_id, model=request.model)
    return _guarded(lambda: {"schema_version": "klara.team-agent.v1", "agent": service.spawn_one_shot(scope=scope, permission_scope=permission_scope, request=value).to_public_dict()})


@router.post("/messages")
def send_message(request: TeamMessageRequest, service: TeamService = Depends(get_team_service), scope: TeamScope = Depends(get_team_scope)):
    return _plain(lambda: {"schema_version": "klara.team-message.v1", "message": service.send_message(scope=scope, sender_id=request.sender_id, recipient_id=request.recipient_id, kind=MessageKind(request.kind), body=request.body, task_id=request.task_id).to_public_dict()})


@router.get("/inbox/{recipient_id}")
def read_inbox(recipient_id: str, after_sequence: int = Query(default=0, ge=0), service: TeamService = Depends(get_team_service), scope: TeamScope = Depends(get_team_scope)):
    return _plain(lambda: {"schema_version": "klara.team-inbox.v1", "messages": [item.to_public_dict() for item in service.inbox(scope=scope, recipient_id=recipient_id, after_sequence=after_sequence)]})


@router.post("/inbox/{recipient_id}/{message_id}/acknowledge")
def acknowledge_message(recipient_id: str, message_id: str, service: TeamService = Depends(get_team_service), scope: TeamScope = Depends(get_team_scope)):
    return _plain(lambda: {"schema_version": "klara.team-message.v1", "message": service.acknowledge(scope=scope, recipient_id=recipient_id, message_id=message_id).to_public_dict()})


@router.post("/agents/{agent_id}/claim")
def claim_team_task(agent_id: str, request: TeamTaskClaimRequest, service: TeamService = Depends(get_team_service), scope: TeamScope = Depends(get_team_scope)):
    return _plain(lambda: {"schema_version": "klara.team-task-claim.v1", **service.claim_task(scope=scope, agent_id=agent_id, task_id=request.task_id, lease_seconds=request.lease_seconds).to_owner_dict()})


@router.post("/agents/{agent_id}/claim-next")
def claim_next_team_task(agent_id: str, request: TeamTaskClaimNextRequest, service: TeamService = Depends(get_team_service), scope: TeamScope = Depends(get_team_scope)):
    return _plain(lambda: {"schema_version": "klara.team-task-claim.v1", **service.claim_next_task(scope=scope, agent_id=agent_id, lease_seconds=request.lease_seconds).to_owner_dict()})


@router.post("/agents/{agent_id}/delegate-authority")
def delegate_team_authority(agent_id: str, request: DelegateAuthorityRequest, service: TeamService = Depends(get_team_service), scope: TeamScope = Depends(get_team_scope), permission_scope: PermissionScope = Depends(get_permission_scope)):
    return _plain(lambda: {"schema_version": "klara.permission-grant.v1", "grant": service.delegate_authority(scope=scope, permission_scope=permission_scope, agent_id=agent_id, parent_grant_id=request.parent_grant_id, effect=PermissionEffect(request.effect), expires_seconds=request.expires_seconds).to_owner_dict()})


@router.post("/agents/{agent_id}/stop")
def stop_agent(agent_id: str, service: TeamService = Depends(get_team_service), scope: TeamScope = Depends(get_team_scope)):
    return _plain(lambda: {"schema_version": "klara.team-agent.v1", "agent": service.stop_agent(scope=scope, agent_id=agent_id).to_public_dict()})


@router.post("/worktrees")
def create_worktree(request: CreateWorktreeRequest, service: TeamService = Depends(get_team_service), scope: TeamScope = Depends(get_team_scope), permission_scope: PermissionScope = Depends(get_permission_scope)):
    return _guarded(lambda: {"schema_version": "klara.team-worktree.v1", "worktree": service.create_worktree(scope=scope, permission_scope=permission_scope, agent_id=request.agent_id, task_id=request.task_id, branch_name=request.branch_name, base_ref=request.base_ref).to_public_dict()})


@router.post("/worktrees/{worktree_id}/remove")
def remove_worktree(worktree_id: str, service: TeamService = Depends(get_team_service), scope: TeamScope = Depends(get_team_scope), permission_scope: PermissionScope = Depends(get_permission_scope)):
    return _guarded(lambda: {"schema_version": "klara.team-worktree.v1", "worktree": service.remove_worktree(scope=scope, permission_scope=permission_scope, worktree_id=worktree_id).to_public_dict()})


def _guarded(call):
    try:
        return call()
    except TeamPermissionRequired as exc:
        raise HTTPException(status_code=409, detail={"code": "permission_approval_required", "decision": exc.decision.to_public_dict()}) from None
    except TeamNotFoundError:
        raise HTTPException(status_code=404, detail="team_record_not_found") from None
    except TeamValidationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


def _plain(call):
    try:
        return call()
    except TeamNotFoundError:
        raise HTTPException(status_code=404, detail="team_record_not_found") from None
    except (TeamValidationError, ValueError, PermissionError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
