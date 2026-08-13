from __future__ import annotations

from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routes.assets import router as assets_router
from apps.api.routes.evaluations import router as evaluations_router
from apps.api.routes.models import router as models_router
from apps.api.routes.memory import router as memory_router
from apps.api.routes.permissions import router as permissions_router
from apps.api.routes.runs import router as runs_router
from apps.api.routes.sessions import router as sessions_router
from apps.api.routes.skills import router as skills_router
from apps.api.routes.tasks import router as tasks_router
from apps.api.routes.scheduler import router as scheduler_router
from apps.api.routes.mcp import router as mcp_router
from apps.api.routes.teams import router as teams_router
from apps.api.routes.production import router as production_router
from apps.api.dependencies import get_mcp_service, get_production_metrics, get_scheduler_runner, get_team_service


@asynccontextmanager
async def lifespan(_app: FastAPI):
    runner = get_scheduler_runner()
    runner.start()
    try:
        yield
    finally:
        runner.stop()
        get_team_service().shutdown()
        get_mcp_service().shutdown()


app = FastAPI(title="Klara API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5123", "http://127.0.0.1:5123"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def production_request_boundary(request, call_next):
    """Attach correlation/security headers and payload-free aggregate metrics."""

    request_id = request.headers.get("X-Request-ID", "").strip()[:128] or f"req_{uuid4().hex}"
    request.state.request_id = request_id
    started = perf_counter()
    if (
        request.url.path.startswith("/api/production")
        and request.method not in {"GET", "HEAD", "OPTIONS"}
        and request.headers.get("Sec-Fetch-Site", "").lower() == "cross-site"
    ):
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=403,
            content={"detail": "cross_site_mutation_rejected"},
            headers={
                "X-Request-ID": request_id,
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store",
            },
        )
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/production") else response.headers.get("Cache-Control", "no-cache")
    if request.url.path.startswith("/api/production"):
        route = getattr(request.scope.get("route"), "path", "/api/production/unknown")
        get_production_metrics().observe(
            method=request.method,
            route=route,
            status_code=response.status_code,
            latency_ms=int((perf_counter() - started) * 1000),
        )
    return response

app.include_router(sessions_router)
app.include_router(models_router)
app.include_router(runs_router)
app.include_router(assets_router)
app.include_router(evaluations_router)
app.include_router(skills_router)
app.include_router(memory_router)
app.include_router(permissions_router)
app.include_router(tasks_router)
app.include_router(scheduler_router)
app.include_router(mcp_router)
app.include_router(teams_router)
app.include_router(production_router)


@app.get("/api/health")
def health():
    return {"ok": True}
