from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass

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


def grant_reward(player_id: str, activity_id: str, idempotency_key: str) -> GrantResult:
    """Grant one activity reward atomically and make retries safe."""
    initialize_database()
    with connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        prior = connection.execute(
            """SELECT player_id, activity_id, idempotency_key, status, reward_gems
               FROM reward_grants WHERE idempotency_key = ?""",
            (idempotency_key,),
        ).fetchone()
        if prior:
            if prior["player_id"] != player_id or prior["activity_id"] != activity_id:
                raise GrantError("idempotency_key 已被其他请求使用")
            return GrantResult(**dict(prior), duplicated=True)

        player = connection.execute(
            "SELECT player_id FROM players WHERE player_id = ?", (player_id,)
        ).fetchone()
        if not player:
            raise GrantNotFoundError("玩家不存在")

        activity = connection.execute(
            """SELECT activity_id, reward_gems, stock, status FROM activities
               WHERE activity_id = ?""",
            (activity_id,),
        ).fetchone()
        if not activity:
            raise GrantNotFoundError("活动不存在")
        if activity["status"] != "active":
            raise GrantError("活动未开启")
        if activity["stock"] <= 0:
            raise GrantError("奖励库存不足")

        connection.execute(
            "UPDATE activities SET stock = stock - 1 WHERE activity_id = ?", (activity_id,)
        )
        connection.execute(
            "UPDATE players SET gem_balance = gem_balance + ? WHERE player_id = ?",
            (activity["reward_gems"], player_id),
        )
        connection.execute(
            """INSERT INTO reward_grants
               (player_id, activity_id, idempotency_key, reward_gems, status)
               VALUES (?, ?, ?, ?, 'success')""",
            (player_id, activity_id, idempotency_key, activity["reward_gems"]),
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
        player = connection.execute(
            "SELECT player_id, nickname, gem_balance FROM players WHERE player_id = ?",
            (player_id,),
        ).fetchone()
    if not player:
        raise GrantNotFoundError("玩家不存在")
    return dict(player)


def serialize(result: GrantResult) -> dict[str, object]:
    return asdict(result)
