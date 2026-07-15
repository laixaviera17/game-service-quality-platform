from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .database import initialize_database
from .quality import run_quality_check
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


@app.get("/dashboard")
def dashboard():
    return FileResponse(DASHBOARD)
