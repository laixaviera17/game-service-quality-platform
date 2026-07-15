from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from sqlalchemy import text

from .database import connect, initialize_database


@dataclass(frozen=True)
class GrantResult:
    player_id: str
    activity_id: str
    idempotency_key: str
    status: str
    reward_gems: int
    duplicated: bool = False


class GrantError(Exception):
    pass


class GrantNotFoundError(GrantError):
    """Raised when the requested player or activity does not exist."""


def _row(connection, statement: str, **params):
    return connection.execute(text(statement), params).mappings().first()


def grant_reward(player_id: str, activity_id: str, idempotency_key: str) -> GrantResult:
    """Grant one reward atomically across SQLite and MySQL-backed environments."""
    initialize_database()
    with connect() as connection:
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        prior = _row(
            connection,
            """SELECT player_id, activity_id, idempotency_key, status, reward_gems
            FROM reward_grants WHERE idempotency_key = :idempotency_key""",
            idempotency_key=idempotency_key,
        )
        if prior:
            if prior["player_id"] != player_id or prior["activity_id"] != activity_id:
                raise GrantError("idempotency_key 已被其他请求使用")
            return GrantResult(**dict(prior), duplicated=True)

        player = _row(
            connection,
            "SELECT player_id, account_status FROM players WHERE player_id = :player_id",
            player_id=player_id,
        )
        if not player:
            raise GrantNotFoundError("玩家不存在")
        if player["account_status"] != "active":
            raise GrantError("玩家账号不可领取活动奖励")

        lock = " FOR UPDATE" if connection.dialect.name != "sqlite" else ""
        activity = _row(
            connection,
            """SELECT activity_id, reward_gems, stock, per_player_limit, status
            FROM activities WHERE activity_id = :activity_id""" + lock,
            activity_id=activity_id,
        )
        if not activity:
            raise GrantNotFoundError("活动不存在")
        if activity["status"] != "active":
            raise GrantError("活动未开启")

        claim_count = connection.execute(
            text(
                """SELECT COUNT(*) FROM reward_grants
                WHERE player_id = :player_id AND activity_id = :activity_id AND status = 'success'"""
            ),
            {"player_id": player_id, "activity_id": activity_id},
        ).scalar_one()
        if claim_count >= activity["per_player_limit"]:
            raise GrantError("玩家领取次数已达活动上限")
        if activity["stock"] <= 0:
            raise GrantError("奖励库存不足")

        stock_update = connection.execute(
            text(
                """UPDATE activities SET stock = stock - 1
                WHERE activity_id = :activity_id AND stock > 0"""
            ),
            {"activity_id": activity_id},
        )
        if stock_update.rowcount != 1:
            raise GrantError("奖励库存不足")
        connection.execute(
            text("UPDATE players SET gem_balance = gem_balance + :reward WHERE player_id = :player_id"),
            {"reward": activity["reward_gems"], "player_id": player_id},
        )
        connection.execute(
            text(
                """INSERT INTO reward_grants
                (player_id, activity_id, idempotency_key, reward_gems, status, created_at)
                VALUES (:player_id, :activity_id, :idempotency_key, :reward_gems, 'success', :created_at)"""
            ),
            {
                "player_id": player_id,
                "activity_id": activity_id,
                "idempotency_key": idempotency_key,
                "reward_gems": activity["reward_gems"],
                "created_at": datetime.now(UTC).isoformat(),
            },
        )
        return GrantResult(
            player_id=player_id,
            activity_id=activity_id,
            idempotency_key=idempotency_key,
            status="success",
            reward_gems=activity["reward_gems"],
        )


def inventory(player_id: str) -> dict[str, object]:
    initialize_database()
    with connect() as connection:
        player = _row(
            connection,
            """SELECT player_id, nickname, gem_balance, account_status
            FROM players WHERE player_id = :player_id""",
            player_id=player_id,
        )
    if not player:
        raise GrantNotFoundError("玩家不存在")
    return dict(player)


def serialize(result: GrantResult) -> dict[str, object]:
    return asdict(result)
