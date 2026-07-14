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
