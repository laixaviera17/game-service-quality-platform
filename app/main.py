from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import text

from .database import connect, get_engine, initialize_database
from .reliability import available_reliability_scenarios, create_reliability_run, get_reliability_run, list_reliability_runs, reliability_trend
from .task_queue import dependency_health, dispatch_reliability_run


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="Reward Delivery Reliability Lab", version="1.0.0", lifespan=lifespan)
DASHBOARD = Path(__file__).resolve().parents[1] / "dashboard.html"


class ReliabilityRunRequest(BaseModel):
    scenario: str


@app.get("/health")
def health(response: Response):
    database_ok = False
    database_backend = "unavailable"
    try:
        with connect() as connection:
            connection.execute(text("SELECT 1"))
        database_ok = True
        database_backend = get_engine().dialect.name
    except Exception:
        database_ok = False
    dependencies = {"database": database_ok, **dependency_health()}
    status = "ok" if all(dependencies.values()) else "degraded"
    if status != "ok":
        response.status_code = 503
    return {"status": status, "dependencies": dependencies, "database_backend": database_backend}


@app.get("/reliability/scenarios")
def reliability_scenarios():
    return {"items": available_reliability_scenarios()}


@app.post("/reliability/runs", status_code=201)
def create_reliability_experiment(body: ReliabilityRunRequest):
    try:
        run_id = create_reliability_run(body.scenario)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if dispatch_reliability_run(run_id) == "queued":
        return {"run_id": run_id, "status": "queued", "message": "实验已提交至 Redis/Celery Worker"}
    return get_reliability_run(run_id)


@app.get("/reliability/runs")
def reliability_runs(limit: int = 12):
    return {"items": list_reliability_runs(limit=max(1, min(limit, 50)))}


@app.get("/reliability/trend")
def get_reliability_trend(limit: int = 12):
    return reliability_trend(limit=max(1, min(limit, 50)))


@app.get("/reliability/runs/{run_id}")
def reliability_run_detail(run_id: int):
    report = get_reliability_run(run_id)
    if not report:
        raise HTTPException(status_code=404, detail="可靠性实验不存在")
    return report


@app.get("/dashboard")
def dashboard():
    return FileResponse(DASHBOARD)
