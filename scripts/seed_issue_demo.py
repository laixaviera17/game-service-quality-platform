"""Seed local-only invalid records so every quality rule can be demonstrated."""

from sqlalchemy import text

from app.database import connect
from .seed_demo import seed_demo_data


def seed_issue_demo_data() -> None:
    """Reset demo data, then insert controlled records that quality rules should find.

    The invalid rows deliberately bypass SQLite constraints. This script is for the
    local SQLite presentation dataset only; it is not part of the MySQL service flow.
    """
    seed_demo_data()
    with connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys = OFF")
        connection.exec_driver_sql("PRAGMA ignore_check_constraints = TRUE")
        connection.execute(
            text(
                """INSERT INTO reward_grants
                (player_id, activity_id, idempotency_key, reward_gems, status)
                VALUES ('player_001', 'event_summer', :idempotency_key, 160, 'success')"""
            ),
            [
                {"idempotency_key": "demo-duplicate-001"},
                {"idempotency_key": "demo-duplicate-002"},
            ],
        )
        connection.execute(
            text(
                """INSERT INTO reward_grants
                (player_id, activity_id, idempotency_key, reward_gems, status)
                VALUES ('player_002', 'event_summer', 'demo-reward-mismatch-001', 99, 'success')"""
            )
        )
        connection.execute(
            text(
                """INSERT INTO reward_grants
                (player_id, activity_id, idempotency_key, reward_gems, status)
                VALUES ('missing-player', 'missing-activity', 'demo-orphan-001', 160, 'success')"""
            )
        )
        connection.execute(text("UPDATE activities SET status = 'archived' WHERE activity_id = 'event_closed'"))
        connection.execute(text("UPDATE players SET gem_balance = -10 WHERE player_id = 'player_002'"))
        connection.execute(text("UPDATE activities SET stock = 97 WHERE activity_id = 'event_summer'"))
        connection.execute(text("UPDATE activities SET stock = 27 WHERE activity_id = 'event_stock_check'"))


def main() -> None:
    seed_issue_demo_data()
    print("Issue demo data seeded. Run `python3 -m scripts.run_quality_check` or open /dashboard.")


if __name__ == "__main__":
    main()
