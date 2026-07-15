import pytest
from concurrent.futures import ThreadPoolExecutor

from app.database import connect
from app.service import GrantError, grant_reward, inventory


def seed() -> None:
    with connect() as connection:
        connection.execute("INSERT INTO players(player_id, nickname, gem_balance) VALUES ('p1', 'Tester', 0)")
        connection.execute(
            """INSERT INTO activities
               (activity_id, name, reward_gems, stock, initial_stock, status)
               VALUES ('a1', 'Login', 100, 1, 1, 'active')"""
        )


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
    with connect() as connection:
        connection.execute("INSERT INTO players(player_id, nickname, gem_balance) VALUES ('p2', 'Tester 2', 0)")
    with pytest.raises(GrantError, match="库存不足"):
        grant_reward("p2", "a1", "request-002")
    assert inventory("p1")["gem_balance"] == 100


def test_inactive_activity_is_rejected_without_mutating_balance():
    with connect() as connection:
        connection.execute("INSERT INTO players(player_id, nickname, gem_balance) VALUES ('p1', 'Tester', 0)")
        connection.execute(
            """INSERT INTO activities
               (activity_id, name, reward_gems, stock, initial_stock, status)
               VALUES ('a1', 'Login', 100, 1, 1, 'inactive')"""
        )

    with pytest.raises(GrantError, match="活动未开启"):
        grant_reward("p1", "a1", "request-inactive")
    assert inventory("p1")["gem_balance"] == 0


def test_suspended_player_and_claim_limit_are_rejected_without_mutation():
    seed()
    with connect() as connection:
        connection.execute("UPDATE activities SET stock = 2, initial_stock = 2 WHERE activity_id = 'a1'")
        connection.execute(
            """INSERT INTO players(player_id, nickname, gem_balance, account_status)
            VALUES ('p2', 'Suspended', 0, 'suspended')"""
        )

    with pytest.raises(GrantError, match="账号不可领取"):
        grant_reward("p2", "a1", "request-suspended")
    grant_reward("p1", "a1", "request-first")
    with pytest.raises(GrantError, match="领取次数已达"):
        grant_reward("p1", "a1", "request-limit")
    assert inventory("p2")["gem_balance"] == 0
    assert inventory("p1")["gem_balance"] == 100


def test_concurrent_grants_do_not_oversell_single_stock():
    seed()
    with connect() as connection:
        connection.execute("INSERT INTO players(player_id, nickname, gem_balance) VALUES ('p2', 'Tester 2', 0)")

    def attempt(player_id: str, request_id: str) -> str:
        try:
            grant_reward(player_id, "a1", request_id)
            return "success"
        except GrantError as error:
            return str(error)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(
            executor.map(
                lambda item: attempt(*item),
                [("p1", "concurrent-001"), ("p2", "concurrent-002")],
            )
        )

    assert outcomes.count("success") == 1
    assert outcomes.count("奖励库存不足") == 1
    with connect() as connection:
        stock = connection.execute("SELECT stock FROM activities WHERE activity_id = 'a1'").fetchone()[0]
        total_balance = connection.execute("SELECT SUM(gem_balance) FROM players").fetchone()[0]
    assert stock == 0
    assert total_balance == 100
