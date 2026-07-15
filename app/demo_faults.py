from __future__ import annotations

import uuid

from sqlalchemy import text

from .database import connect, initialize_database


FAULT_TYPES = {
    "duplicate_reward": "重复发奖与库存账实不一致",
    "reward_amount_mismatch": "奖励金额与活动配置不一致",
    "stock_mismatch": "活动库存账实不一致",
    "invalid_activity_status": "活动状态不在允许范围内",
}


def fault_catalog() -> list[dict[str, str]]:
    return [{"code": code, "title": title} for code, title in FAULT_TYPES.items()]


def inject_fault(fault_type: str) -> dict[str, str]:
    """Insert local demo data that intentionally violates one quality rule."""
    if fault_type not in FAULT_TYPES:
        raise ValueError("不支持的故障类型")
    initialize_database()
    prefix = f"fault_{fault_type}_{uuid.uuid4().hex[:8]}"
    activity_id = f"{prefix}_activity"
    player_id = f"{prefix}_player"
    with connect() as connection:
        if fault_type == "invalid_activity_status":
            connection.execute(
                text("""INSERT INTO activities
                    (activity_id, name, reward_gems, stock, initial_stock, per_player_limit, status)
                    VALUES (:activity_id, :name, 100, 1, 1, 1, 'draft')"""),
                {"activity_id": activity_id, "name": "故障注入：非法活动状态"},
            )
        else:
            connection.execute(
                text("INSERT INTO players (player_id, nickname, gem_balance, account_status) VALUES (:player_id, :nickname, 0, 'active')"),
                {"player_id": player_id, "nickname": "故障注入测试玩家"},
            )
            if fault_type == "stock_mismatch":
                stock, initial_stock = 2, 5
            else:
                stock, initial_stock = 0, 1
            connection.execute(
                text("""INSERT INTO activities
                    (activity_id, name, reward_gems, stock, initial_stock, per_player_limit, status)
                    VALUES (:activity_id, :name, 100, :stock, :initial_stock, 3, 'active')"""),
                {"activity_id": activity_id, "name": f"故障注入：{FAULT_TYPES[fault_type]}", "stock": stock, "initial_stock": initial_stock},
            )
            if fault_type == "duplicate_reward":
                rows = [
                    {"key": f"{prefix}_grant_1", "reward": 100},
                    {"key": f"{prefix}_grant_2", "reward": 100},
                ]
            elif fault_type == "reward_amount_mismatch":
                rows = [{"key": f"{prefix}_grant_1", "reward": 50}]
            else:
                rows = []
            if rows:
                connection.execute(
                    text("""INSERT INTO reward_grants
                        (player_id, activity_id, idempotency_key, reward_gems, status)
                        VALUES (:player_id, :activity_id, :key, :reward, 'success')"""),
                    [{**row, "player_id": player_id, "activity_id": activity_id} for row in rows],
                )
    return {"fault_type": fault_type, "title": FAULT_TYPES[fault_type], "activity_id": activity_id}


def clear_faults() -> int:
    """Remove only records created by the local fault-injection controls."""
    initialize_database()
    with connect() as connection:
        result = connection.execute(
            text("DELETE FROM reward_grants WHERE player_id LIKE 'fault_%' OR activity_id LIKE 'fault_%'")
        )
        grants = result.rowcount or 0
        connection.execute(text("DELETE FROM players WHERE player_id LIKE 'fault_%'"))
        connection.execute(text("DELETE FROM activities WHERE activity_id LIKE 'fault_%'"))
    return grants
