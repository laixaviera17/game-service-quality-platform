from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .database import initialize_database
from .demo_faults import clear_faults, fault_catalog, inject_fault
from .quality import get_quality_run, list_quality_runs, run_quality_check
from .reliability import (
    available_reliability_scenarios,
    create_reliability_run,
    get_reliability_run,
    list_reliability_runs,
    reliability_trend,
)
from .service import GrantError, GrantNotFoundError, grant_reward, inventory, serialize
from .task_queue import dispatch_reliability_run, dispatch_test_run
from .test_runner import (
    available_scenarios,
    create_test_run,
    get_test_run,
    list_test_runs,
    rerun_test_run,
    get_test_run_trend,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="Game Service Quality Platform", version="0.2.0", lifespan=lifespan
)
DASHBOARD = Path(__file__).resolve().parents[1] / "dashboard.html"


class GrantRequest(BaseModel):
    player_id: str = Field(min_length=1, examples=["player_001"])


class TestRunRequest(BaseModel):
    case_codes: list[str] | None = None
    stock: int = Field(default=1, ge=1, le=10)
    per_player_limit: int = Field(default=1, ge=1, le=3)
    player_status: str = Field(default="suspended", pattern="^(active|suspended)$")


class FaultRequest(BaseModel):
    fault_type: str


class ReliabilityRunRequest(BaseModel):
    scenario: str


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


@app.get("/test-scenarios")
def test_scenarios():
    return {"items": available_scenarios()}


@app.post("/test-runs", status_code=201)
def create_service_test_run(body: TestRunRequest | None = None):
    body = body or TestRunRequest()
    try:
        run_id = create_test_run(
            trigger="api",
            case_codes=body.case_codes,
            options={"stock": body.stock, "per_player_limit": body.per_player_limit, "player_status": body.player_status},
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    dispatch_status = dispatch_test_run(run_id)
    report = get_test_run(run_id)
    if not report:
        raise HTTPException(status_code=500, detail="测试运行创建失败")
    if dispatch_status == "queued":
        return {"run_id": run_id, "status": "queued", "message": "任务已提交至 Redis/Celery Worker"}
    return report


@app.get("/test-runs")
def service_test_runs(limit: int = 12):
    return {"items": list_test_runs(limit=max(1, min(limit, 50)))}


@app.get("/test-runs/trend")
def service_test_trend(limit: int = 12):
    return get_test_run_trend(limit=max(1, min(limit, 50)))


@app.get("/test-runs/{run_id}")
def service_test_run_detail(run_id: int):
    report = get_test_run(run_id)
    if not report:
        raise HTTPException(status_code=404, detail="测试运行不存在")
    return report


@app.post("/test-runs/{run_id}/rerun", status_code=201)
def rerun_service_test(run_id: int):
    try:
        new_run_id = rerun_test_run(run_id)
    except GrantNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    dispatch_status = dispatch_test_run(new_run_id)
    if dispatch_status == "queued":
        return {"run_id": new_run_id, "status": "queued", "message": f"已按运行 #{run_id} 的配置重新提交"}
    return get_test_run(new_run_id)


@app.get("/demo/faults")
def demo_fault_types():
    return {"items": fault_catalog()}


@app.post("/demo/faults", status_code=201)
def create_demo_fault(body: FaultRequest):
    try:
        return inject_fault(body.fault_type)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.delete("/demo/faults")
def delete_demo_faults():
    return {"deleted_grants": clear_faults()}


@app.get("/reliability/scenarios")
def reliability_scenarios():
    return {"items": available_reliability_scenarios()}


@app.post("/reliability/runs", status_code=201)
def create_reliability_experiment(body: ReliabilityRunRequest):
    try:
        run_id = create_reliability_run(body.scenario)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    dispatch_status = dispatch_reliability_run(run_id)
    report = get_reliability_run(run_id)
    if dispatch_status == "queued":
        return {"run_id": run_id, "status": "queued", "message": "实验已提交至 Redis/Celery Worker"}
    return report


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
