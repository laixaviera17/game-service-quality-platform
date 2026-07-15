from fastapi.testclient import TestClient
from sqlalchemy import text

from app.database import connect
from app.main import app


def seed() -> None:
    with connect() as connection:
        connection.execute(text("INSERT INTO players(player_id, nickname, gem_balance) VALUES ('p1', 'Tester', 0)"))
        connection.execute(text(
            """INSERT INTO activities
               (activity_id, name, reward_gems, stock, initial_stock, status)
               VALUES ('a1', 'Login', 100, 2, 2, 'active')"""
        ))


def test_grant_api_is_idempotent():
    seed()
    client = TestClient(app)
    headers = {"Idempotency-Key": "api-request-001"}

    first = client.post("/activities/a1/rewards/grant", json={"player_id": "p1"}, headers=headers)
    retry = client.post("/activities/a1/rewards/grant", json={"player_id": "p1"}, headers=headers)

    assert first.status_code == 201
    assert first.json()["duplicated"] is False
    assert retry.status_code == 201
    assert retry.json()["duplicated"] is True
    assert client.get("/players/p1/inventory").json()["gem_balance"] == 100


def test_grant_api_rejects_missing_idempotency_key():
    seed()
    response = TestClient(app).post("/activities/a1/rewards/grant", json={"player_id": "p1"})
    assert response.status_code == 422


def test_grant_api_returns_404_for_unknown_player_or_activity():
    seed()
    client = TestClient(app)
    headers = {"Idempotency-Key": "api-request-404"}

    unknown_player = client.post(
        "/activities/a1/rewards/grant", json={"player_id": "missing"}, headers=headers
    )
    unknown_activity = client.post(
        "/activities/missing/rewards/grant", json={"player_id": "p1"}, headers=headers
    )

    assert unknown_player.status_code == 404
    assert unknown_player.json() == {"detail": "玩家不存在"}
    assert unknown_activity.status_code == 404
    assert unknown_activity.json() == {"detail": "活动不存在"}


def test_grant_api_reports_claim_limit_without_changing_inventory():
    seed()
    client = TestClient(app)
    headers = {"Idempotency-Key": "api-request-conflict"}
    client.post("/activities/a1/rewards/grant", json={"player_id": "p1"}, headers=headers)
    limit_reached = client.post(
        "/activities/a1/rewards/grant",
        json={"player_id": "p1"},
        headers={"Idempotency-Key": "api-request-other"},
    )

    assert limit_reached.status_code == 409
    assert limit_reached.json() == {"detail": "玩家领取次数已达活动上限"}
    assert client.get("/players/p1/inventory").json()["gem_balance"] == 100


def test_health_quality_report_and_dashboard_are_available():
    client = TestClient(app)

    health = client.get("/health")
    report = client.get("/quality/check")
    dashboard = client.get("/dashboard")

    assert health.json() == {"status": "ok"}
    assert report.status_code == 200
    assert report.json()["summary"]["rules"] == 6
    assert dashboard.status_code == 200
    assert "Reward Reliability Lab" in dashboard.text


def test_quality_run_api_persists_and_reads_a_snapshot():
    seed()
    client = TestClient(app)

    created = client.post("/quality/runs")
    run_id = created.json()["run_id"]
    latest = client.get("/quality/runs/latest")
    detail = client.get(f"/quality/runs/{run_id}")
    history = client.get("/quality/runs?limit=5")

    assert created.status_code == 201
    assert created.json()["status"] == "passed"
    assert latest.json()["run_id"] == run_id
    assert detail.json()["findings"][0]["title"] == "重复发奖"
    assert history.json()["items"][0]["run_id"] == run_id


def test_quality_run_api_returns_404_for_missing_run():
    response = TestClient(app).get("/quality/runs/999")
    assert response.status_code == 404
    assert response.json() == {"detail": "质量检查记录不存在"}


def test_service_test_run_api_executes_and_persists_case_evidence():
    client = TestClient(app)
    created = client.post("/test-runs")

    assert created.status_code == 201
    assert created.json()["status"] == "passed"
    assert created.json()["summary"] == {"total_cases": 5, "passed_cases": 5, "failed_cases": 0}
    run_id = created.json()["run_id"]
    detail = client.get(f"/test-runs/{run_id}")
    history = client.get("/test-runs?limit=1")
    assert detail.json()["cases"][0]["request"]
    assert detail.json()["cases"][0]["assertions"]
    assert history.json()["items"][0]["run_id"] == run_id


def test_test_workbench_apis_accept_config_show_trend_and_rerun():
    client = TestClient(app)
    scenarios = client.get("/test-scenarios")
    created = client.post(
        "/test-runs",
        json={"case_codes": ["normal_grant"], "stock": 2, "per_player_limit": 2, "player_status": "active"},
    )

    assert scenarios.status_code == 200
    assert len(scenarios.json()["items"]) == 5
    assert created.status_code == 201
    run_id = created.json()["run_id"]
    detail = client.get(f"/test-runs/{run_id}")
    assert detail.json()["config"]["options"]["stock"] == 2
    assert detail.json()["summary"]["total_cases"] == 1
    trend = client.get("/test-runs/trend")
    assert trend.status_code == 200
    assert trend.json()["total_runs"] == 1
    rerun = client.post(f"/test-runs/{run_id}/rerun")
    assert rerun.status_code == 201
    assert rerun.json()["run_id"] != run_id


def test_fault_injection_can_be_checked_and_cleaned():
    client = TestClient(app)
    catalog = client.get("/demo/faults")
    created = client.post("/demo/faults", json={"fault_type": "duplicate_reward"})
    report = client.post("/quality/runs")
    cleared = client.delete("/demo/faults")
    recovered = client.post("/quality/runs")

    assert catalog.status_code == 200
    assert created.status_code == 201
    assert report.json()["status"] == "failed"
    assert next(item for item in report.json()["findings"] if item["rule"] == "duplicate_reward")["count"] == 1
    assert cleared.status_code == 200
    assert recovered.json()["status"] == "passed"


def test_api_validates_blank_player_and_missing_inventory():
    seed()
    client = TestClient(app)

    blank_player = client.post(
        "/activities/a1/rewards/grant",
        json={"player_id": ""},
        headers={"Idempotency-Key": "api-request-blank"},
    )
    missing_inventory = client.get("/players/missing/inventory")

    assert blank_player.status_code == 422
    assert missing_inventory.status_code == 404
    assert missing_inventory.json() == {"detail": "玩家不存在"}
