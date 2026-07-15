import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.reliability import create_reliability_run, execute_reliability_run, get_reliability_run


@pytest.mark.parametrize("scenario", ["duplicate_request", "acknowledgement_loss", "concurrent_consume"])
def test_reliability_experiments_preserve_single_wallet_effect(scenario: str):
    run_id = create_reliability_run(scenario, trigger="test")
    report = execute_reliability_run(run_id)

    assert report["status"] == "passed"
    assert report["summary"]["passed"] is True
    assert report["summary"]["actual"]["ledger_entries"] == 1
    assert report["summary"]["actual"]["balance"] == 100
    assert report["summary"]["actual"]["delivery_statuses"] == ["delivered"]
    assert get_reliability_run(run_id) == report


def test_reliability_api_exposes_scenarios_run_history_and_timeline():
    client = TestClient(app)
    scenarios = client.get("/reliability/scenarios")
    created = client.post("/reliability/runs", json={"scenario": "acknowledgement_loss"})

    assert scenarios.status_code == 200
    assert len(scenarios.json()["items"]) == 3
    assert created.status_code == 201
    report = created.json()
    assert report["summary"]["actual"]["delivery_attempts"] >= 2
    assert any(event["kind"] == "retry" for event in report["events"])
    history = client.get("/reliability/runs")
    trend = client.get("/reliability/trend")
    assert history.json()["items"][0]["run_id"] == report["run_id"]
    assert trend.json()["total_runs"] == 1
