import pytest

from app.database import connect
from app.service import GrantError, grant_reward, inventory


def seed() -> None:
    with connect() as connection:
        connection.execute("INSERT INTO players VALUES ('p1', 'Tester', 0)")
        connection.execute("INSERT INTO activities VALUES ('a1', 'Login', 100, 1, 'active')")


def test_grant_updates_stock_and_balance_once():
    seed()
    first = grant_reward("p1", "a1", "request-001")
    retry = grant_reward("p1", "a1", "request-001")

    assert first.status == "success"
    assert retry.duplicated is True
    assert inventory("p1")["gem_balance"] == 100
    with connect() as connection:
        assert connection.execute("SELECT stock FROM activities WHERE activity_id = 'a1'").fetchone()[0] == 0


def test_reused_key_with_different_request_is_rejected():
    seed()
    grant_reward("p1", "a1", "request-001")
    with pytest.raises(GrantError, match="其他请求"):
        grant_reward("p1", "not-the-same", "request-001")


def test_stock_shortage_is_rejected_without_mutating_balance():
    seed()
    grant_reward("p1", "a1", "request-001")
    with pytest.raises(GrantError, match="库存不足"):
        grant_reward("p1", "a1", "request-002")
    assert inventory("p1")["gem_balance"] == 100
