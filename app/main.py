from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .database import initialize_database
from .quality import get_quality_run, list_quality_runs, run_quality_check
from .service import GrantError, GrantNotFoundError, grant_reward, inventory, serialize


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="Game Service Quality Platform", version="0.1.0", lifespan=lifespan
)
DASHBOARD = Path(__file__).resolve().parents[1] / "dashboard.html"


class GrantRequest(BaseModel):
    player_id: str = Field(min_length=1, examples=["player_001"])


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/activities/{activity_id}/rewards/grant", status_code=201)
def grant(activity_id: str, body: GrantRequest, idempotency_key: str = Header(min_length=8)):
    try:
        result = grant_reward(body.player_id, activity_id, idempotency_key)
    except GrantNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except GrantError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return serialize(result)


@app.get("/players/{player_id}/inventory")
def get_inventory(player_id: str):
    try:
        return inventory(player_id)
    except GrantNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@app.get("/quality/check")
def quality_check():
    return run_quality_check()


@app.post("/quality/runs", status_code=201)
def create_quality_run():
    return run_quality_check(persist=True, trigger="dashboard")


@app.get("/quality/runs")
def quality_runs(limit: int = 12):
    return {"items": list_quality_runs(limit=max(1, min(limit, 50)))}


@app.get("/quality/runs/latest")
def latest_quality_run():
    runs = list_quality_runs(limit=1)
    if not runs:
        raise HTTPException(status_code=404, detail="尚无质量检查记录")
    return get_quality_run(runs[0]["run_id"])


@app.get("/quality/runs/{run_id}")
def quality_run_detail(run_id: int):
    report = get_quality_run(run_id)
    if not report:
        raise HTTPException(status_code=404, detail="质量检查记录不存在")
    return report


@app.get("/dashboard")
def dashboard():
    return FileResponse(DASHBOARD)
