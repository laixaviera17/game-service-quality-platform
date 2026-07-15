from app.database import connect
from app.quality import run_quality_check


def test_quality_check_reports_duplicate_reward():
    with connect() as connection:
        connection.execute("INSERT INTO players(player_id, nickname, gem_balance) VALUES ('p1', 'Tester', 0)")
        connection.execute(
            """INSERT INTO activities
               (activity_id, name, reward_gems, stock, initial_stock, status)
               VALUES ('a1', 'Login', 100, 3, 5, 'active')"""
        )
        connection.executemany(
            """INSERT INTO reward_grants
               (player_id, activity_id, idempotency_key, reward_gems, status)
               VALUES ('p1', 'a1', ?, 100, 'success')""",
            [("key-1",), ("key-2",)],
        )

    report = run_quality_check()
    duplicate = next(item for item in report["findings"] if item["rule"] == "duplicate_reward")
    assert duplicate["count"] == 1
    assert duplicate["passed"] is False
    assert duplicate["samples"] == [
        {"player_id": "p1", "activity_id": "a1", "grant_count": 2}
    ]


def test_quality_check_returns_diagnostic_samples_for_invalid_data():
    with connect() as connection:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("PRAGMA ignore_check_constraints = TRUE")
        connection.execute("INSERT INTO players(player_id, nickname, gem_balance) VALUES ('p1', 'Tester', -1)")
        connection.execute(
            """INSERT INTO activities
               (activity_id, name, reward_gems, stock, initial_stock, status)
               VALUES ('a1', 'Login', 100, 5, 5, 'archived')"""
        )
        connection.execute(
            """INSERT INTO reward_grants
               (player_id, activity_id, idempotency_key, reward_gems, status)
               VALUES ('missing-player', 'missing-activity', 'orphan-key', 100, 'success')"""
        )

    report = run_quality_check()
    findings = {item["rule"]: item for item in report["findings"]}

    assert findings["orphan_grant"]["samples"] == [
        {"grant_id": 1, "player_id": "missing-player", "activity_id": "missing-activity"}
    ]
    assert findings["invalid_activity_status"]["samples"] == [
        {"activity_id": "a1", "status": "archived"}
    ]
    assert findings["negative_balance"]["samples"] == [
        {"player_id": "p1", "gem_balance": -1}
    ]


def test_quality_check_reports_reward_and_stock_mismatches():
    with connect() as connection:
        connection.execute("INSERT INTO players(player_id, nickname, gem_balance) VALUES ('p1', 'Tester', 0)")
        connection.execute(
            """INSERT INTO activities
               (activity_id, name, reward_gems, stock, initial_stock, status)
               VALUES ('a1', 'Login', 100, 8, 10, 'active')"""
        )
        connection.execute(
            """INSERT INTO reward_grants
               (player_id, activity_id, idempotency_key, reward_gems, status)
               VALUES ('p1', 'a1', 'bad-reward', 50, 'success')"""
        )

    findings = {item["rule"]: item for item in run_quality_check()["findings"]}

    assert findings["reward_amount_mismatch"]["samples"] == [
        {"grant_id": 1, "activity_id": "a1", "grant_reward": 50, "configured_reward": 100}
    ]
    assert findings["stock_mismatch"]["samples"] == [
        {
            "activity_id": "a1",
            "initial_stock": 10,
            "stock": 8,
            "successful_grants": 1,
            "expected_stock": 9,
        }
    ]
