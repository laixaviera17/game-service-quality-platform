from app.database import connect, initialize_database


def seed_demo_data() -> None:
    """Reset the local database to a valid, passing demo dataset."""
    initialize_database()
    with connect() as connection:
        connection.execute("DELETE FROM reward_grants")
        connection.execute("DELETE FROM players")
        connection.execute("DELETE FROM activities")
        connection.executemany(
            """INSERT INTO players(player_id, nickname, gem_balance, account_status)
            VALUES (?, ?, ?, ?)""",
            [
                ("player_001", "测试账号A", 0, "active"),
                ("player_002", "测试账号B", 20, "active"),
                ("player_suspended", "冻结测试账号", 0, "suspended"),
            ],
        )
        connection.executemany(
            """INSERT INTO activities
               (activity_id, name, reward_gems, stock, initial_stock, per_player_limit, status)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [
                ("event_summer", "夏日登录活动", 160, 100, 100, 1, "active"),
                ("event_closed", "已关闭活动", 60, 0, 0, 1, "inactive"),
                ("event_stock_check", "库存校验活动", 30, 30, 30, 3, "active"),
            ],
        )


def main() -> None:
    seed_demo_data()
    print("Demo data seeded.")


if __name__ == "__main__":
    main()
