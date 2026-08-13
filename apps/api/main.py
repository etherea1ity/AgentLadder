from __future__ import annotations

from contextlib import asynccontextmanager

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
from apps.api.dependencies import get_mcp_service, get_scheduler_runner


@asynccontextmanager
async def lifespan(_app: FastAPI):
    runner = get_scheduler_runner()
    runner.start()
    try:
        yield
    finally:
        runner.stop()
        get_mcp_service().shutdown()


app = FastAPI(title="Klara API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5123", "http://127.0.0.1:5123"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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


@app.get("/api/health")
def health():
    return {"ok": True}
