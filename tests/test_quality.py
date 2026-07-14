from app.database import connect
from app.quality import run_quality_check


def test_quality_check_reports_duplicate_reward():
    with connect() as connection:
        connection.execute("INSERT INTO players VALUES ('p1', 'Tester', 0)")
        connection.execute("INSERT INTO activities VALUES ('a1', 'Login', 100, 5, 'active')")
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
