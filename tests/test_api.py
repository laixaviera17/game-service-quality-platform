from fastapi.testclient import TestClient

from app.database import connect
from app.main import app


def seed() -> None:
    with connect() as connection:
        connection.execute("INSERT INTO players VALUES ('p1', 'Tester', 0)")
        connection.execute("INSERT INTO activities VALUES ('a1', 'Login', 100, 2, 'active')")


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


def test_grant_api_reports_conflict_without_changing_inventory():
    seed()
    client = TestClient(app)
    headers = {"Idempotency-Key": "api-request-conflict"}
    client.post("/activities/a1/rewards/grant", json={"player_id": "p1"}, headers=headers)
    second = client.post(
        "/activities/a1/rewards/grant",
        json={"player_id": "p1"},
        headers={"Idempotency-Key": "api-request-other"},
    )
    conflict = client.post(
        "/activities/a1/rewards/grant",
        json={"player_id": "p1"},
        headers={"Idempotency-Key": "api-request-last"},
    )

    assert second.status_code == 201
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "奖励库存不足"}
    assert client.get("/players/p1/inventory").json()["gem_balance"] == 200


def test_health_quality_report_and_dashboard_are_available():
    client = TestClient(app)

    health = client.get("/health")
    report = client.get("/quality/check")
    dashboard = client.get("/dashboard")

    assert health.json() == {"status": "ok"}
    assert report.status_code == 200
    assert report.json()["summary"]["rules"] == 4
    assert dashboard.status_code == 200
    assert "Game QA Console" in dashboard.text


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
