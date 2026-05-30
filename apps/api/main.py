from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.api.routes.models import router as models_router
from apps.api.routes.runs import router as runs_router
from apps.api.routes.sessions import router as sessions_router

app = FastAPI(title="Agent Ladder API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sessions_router)
app.include_router(models_router)
app.include_router(runs_router)


@app.get("/api/health")
def health():
    return {"ok": True, "version": "0.2.0"}
