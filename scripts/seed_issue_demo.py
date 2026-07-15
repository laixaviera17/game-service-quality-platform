"""Seed local-only invalid records so every quality rule can be demonstrated."""

from app.database import connect
from .seed_demo import seed_demo_data


def seed_issue_demo_data() -> None:
    """Reset demo data, then insert controlled records that quality rules should find."""
    seed_demo_data()
    with connect() as connection:
        # These switches are used only for locally constructed demo records.
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("PRAGMA ignore_check_constraints = TRUE")
        connection.executemany(
            """INSERT INTO reward_grants
               (player_id, activity_id, idempotency_key, reward_gems, status)
               VALUES ('player_001', 'event_summer', ?, 160, 'success')""",
            [("demo-duplicate-001",), ("demo-duplicate-002",)],
        )
        connection.execute(
            """INSERT INTO reward_grants
               (player_id, activity_id, idempotency_key, reward_gems, status)
               VALUES ('missing-player', 'missing-activity', 'demo-orphan-001', 160, 'success')"""
        )
        connection.execute(
            "UPDATE activities SET status = 'archived' WHERE activity_id = 'event_closed'"
        )
        connection.execute(
            "UPDATE players SET gem_balance = -10 WHERE player_id = 'player_002'"
        )


def main() -> None:
    seed_issue_demo_data()
    print("Issue demo data seeded. Run `python3 -m scripts.run_quality_check` or open /dashboard.")


if __name__ == "__main__":
    main()
