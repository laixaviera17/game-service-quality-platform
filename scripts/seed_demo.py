from app.database import connect, initialize_database


def main() -> None:
    initialize_database()
    with connect() as connection:
        connection.execute("DELETE FROM reward_grants")
        connection.execute("DELETE FROM players")
        connection.execute("DELETE FROM activities")
        connection.executemany(
            "INSERT INTO players(player_id, nickname, gem_balance) VALUES (?, ?, ?)",
            [("player_001", "测试账号A", 0), ("player_002", "测试账号B", 20)],
        )
        connection.executemany(
            """INSERT INTO activities(activity_id, name, reward_gems, stock, status)
               VALUES (?, ?, ?, ?, ?)""",
            [
                ("event_summer", "夏日登录活动", 160, 100, "active"),
                ("event_closed", "已关闭活动", 60, 0, "inactive"),
            ],
        )
    print("Demo data seeded.")


if __name__ == "__main__":
    main()
