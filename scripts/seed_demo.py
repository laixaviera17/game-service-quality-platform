from app.database import connect, initialize_database
from sqlalchemy import text


def seed_demo_data() -> None:
    """Reset the local database to a valid, passing demo dataset."""
    initialize_database()
    with connect() as connection:
        connection.execute(text("DELETE FROM reward_grants"))
        connection.execute(text("DELETE FROM players"))
        connection.execute(text("DELETE FROM activities"))
        connection.execute(text(
            """INSERT INTO players(player_id, nickname, gem_balance, account_status)
            VALUES (:player_id, :nickname, :gem_balance, :account_status)"""),
            [
                {"player_id": "player_001", "nickname": "测试账号A", "gem_balance": 0, "account_status": "active"},
                {"player_id": "player_002", "nickname": "测试账号B", "gem_balance": 20, "account_status": "active"},
                {"player_id": "player_suspended", "nickname": "冻结测试账号", "gem_balance": 0, "account_status": "suspended"},
            ],
        )
        connection.execute(text(
            """INSERT INTO activities
               (activity_id, name, reward_gems, stock, initial_stock, per_player_limit, status)
               VALUES (:activity_id, :name, :reward_gems, :stock, :initial_stock, :per_player_limit, :status)"""),
            [
                {"activity_id": "event_summer", "name": "夏日登录活动", "reward_gems": 160, "stock": 100, "initial_stock": 100, "per_player_limit": 1, "status": "active"},
                {"activity_id": "event_closed", "name": "已关闭活动", "reward_gems": 60, "stock": 0, "initial_stock": 0, "per_player_limit": 1, "status": "inactive"},
                {"activity_id": "event_stock_check", "name": "库存校验活动", "reward_gems": 30, "stock": 30, "initial_stock": 30, "per_player_limit": 3, "status": "active"},
            ],
        )


def main() -> None:
    seed_demo_data()
    print("Demo data seeded.")


if __name__ == "__main__":
    main()
