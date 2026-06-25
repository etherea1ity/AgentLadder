from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from apps.api.dependencies import get_bus, get_run_service, get_store
from apps.api.schemas import CancelRunResponse, CreateRunRequest, CreateRunResponse, RunDetailResponse, RunEventsResponse
from apps.api.services.app_store import JsonlAppStore
from apps.api.services.run_service import RunService
from apps.api.services.sse_bus import SSEBus, TERMINAL_EVENTS

router = APIRouter(prefix="/api/runs", tags=["runs"])


@router.post("", response_model=CreateRunResponse)
def create_run(request: CreateRunRequest, run_service: RunService = Depends(get_run_service)):
    try:
        return run_service.create_run(
            session_id=request.session_id,
            question=request.question,
            model=request.model,
            thinking_enabled=request.thinking_enabled,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="session_not_found") from None
    except ValueError as exc:
        if str(exc) == "model_not_allowed":
            raise HTTPException(status_code=400, detail="model_not_allowed") from None
        if str(exc) == "thinking_not_supported":
            raise HTTPException(status_code=400, detail="thinking_not_supported") from None
        raise


@router.get("/{run_id}", response_model=RunDetailResponse)
def get_run(
    run_id: str,
    store: JsonlAppStore = Depends(get_store),
    run_service: RunService = Depends(get_run_service),
):
    run = store.get_visible_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run_not_found")
    trace = store.latest_trace_for_run(run_id, run_service.trace_path)
    return RunDetailResponse(run=run, events=store.list_events(run_id), trace=trace)


@router.get("/{run_id}/events", response_model=RunEventsResponse)
def get_events(run_id: str, store: JsonlAppStore = Depends(get_store)):
    if store.get_visible_run(run_id) is None:
        raise HTTPException(status_code=404, detail="run_not_found")
    return RunEventsResponse(events=store.list_events(run_id))


@router.get("/{run_id}/events/stream")
def stream_events(
    run_id: str,
    store: JsonlAppStore = Depends(get_store),
    bus: SSEBus = Depends(get_bus),
):
    if store.get_visible_run(run_id) is None:
        raise HTTPException(status_code=404, detail="run_not_found")

    async def event_generator():
        subscriber = bus.subscribe(run_id)
        seen: set[str] = set()
        try:
            for event in store.list_events(run_id):
                seen.add(event.event_id)
                yield _format_sse(event.event_type, event.model_dump(mode="json"))
                if event.event_type in TERMINAL_EVENTS:
                    return
            while True:
                event = await subscriber.queue.get()
                if event.event_id in seen:
                    continue
                seen.add(event.event_id)
                yield _format_sse(event.event_type, event.model_dump(mode="json"))
                if event.event_type in TERMINAL_EVENTS:
                    return
        finally:
            bus.unsubscribe(run_id, subscriber)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/{run_id}/cancel", response_model=CancelRunResponse)
def cancel_run(run_id: str, run_service: RunService = Depends(get_run_service)):
    run = run_service.cancel_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run_not_found")
    return CancelRunResponse(run_id=run_id, status=run.status)


def _format_sse(event_name: str, data: dict) -> str:
    return f"event: {event_name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
