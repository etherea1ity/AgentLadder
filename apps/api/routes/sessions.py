from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from apps.api.dependencies import get_run_service, get_store
from apps.api.schemas import (
    CreateSessionResponse,
    DeleteSessionResponse,
    ListSessionsResponse,
    RenameSessionRequest,
    SessionDetailResponse,
)
from apps.api.services.app_store import JsonlAppStore
from apps.api.services.run_service import RunService

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.post("", response_model=CreateSessionResponse)
def create_session(store: JsonlAppStore = Depends(get_store)):
    return store.create_session()


@router.get("", response_model=ListSessionsResponse)
def list_sessions(store: JsonlAppStore = Depends(get_store)):
    return ListSessionsResponse(sessions=store.list_sessions())


@router.get("/{session_id}", response_model=SessionDetailResponse)
def get_session(session_id: str, store: JsonlAppStore = Depends(get_store)):
    session = store.get_visible_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    return SessionDetailResponse(
        session=session,
        messages=store.list_messages(session_id),
        runs=store.list_runs(session_id),
    )


@router.patch("/{session_id}", response_model=CreateSessionResponse)
def rename_session(session_id: str, request: RenameSessionRequest, store: JsonlAppStore = Depends(get_store)):
    session = store.rename_session(session_id, request.title)
    if session is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    return session


@router.delete("/{session_id}", response_model=DeleteSessionResponse)
def delete_session(
    session_id: str,
    store: JsonlAppStore = Depends(get_store),
    run_service: RunService = Depends(get_run_service),
):
    run_service.cancel_active_runs_for_session(session_id)
    session = store.delete_session(session_id, run_service.trace_path)
    if session is None or session.deleted_at is None:
        raise HTTPException(status_code=404, detail="session_not_found")
    return DeleteSessionResponse(session_id=session_id, deleted=True, deleted_at=session.deleted_at)
