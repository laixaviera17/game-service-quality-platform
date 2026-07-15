from __future__ import annotations

from datetime import UTC, datetime

from .database import connect, initialize_database


QUALITY_RULES = {
    "duplicate_reward": "同一玩家在同一活动获得多次成功奖励",
    "orphan_grant": "发奖记录关联的玩家或活动不存在",
    "invalid_activity_status": "活动状态不在允许枚举范围内",
    "negative_balance": "玩家宝石余额为负数",
}


SAMPLE_LIMIT = 3


def _count(connection, statement: str) -> int:
    return int(connection.execute(statement).fetchone()[0])


def _samples(connection, statement: str) -> list[dict[str, object]]:
    return [dict(row) for row in connection.execute(statement).fetchmany(SAMPLE_LIMIT)]


def run_quality_check() -> dict[str, object]:
    initialize_database()
    with connect() as connection:
        findings = [
            {
                "rule": "duplicate_reward",
                "severity": "high",
                "count": _count(
                    connection,
                    """SELECT COUNT(*) FROM (
                        SELECT player_id, activity_id FROM reward_grants
                        WHERE status = 'success'
                        GROUP BY player_id, activity_id HAVING COUNT(*) > 1
                    )""",
                ),
                "samples": _samples(
                    connection,
                    """SELECT player_id, activity_id, COUNT(*) AS grant_count
                    FROM reward_grants WHERE status = 'success'
                    GROUP BY player_id, activity_id HAVING COUNT(*) > 1
                    ORDER BY grant_count DESC, player_id, activity_id""",
                ),
            },
            {
                "rule": "orphan_grant",
                "severity": "critical",
                "count": _count(
                    connection,
                    """SELECT COUNT(*) FROM reward_grants rg
                    LEFT JOIN players p ON p.player_id = rg.player_id
                    LEFT JOIN activities a ON a.activity_id = rg.activity_id
                    WHERE p.player_id IS NULL OR a.activity_id IS NULL""",
                ),
                "samples": _samples(
                    connection,
                    """SELECT rg.grant_id, rg.player_id, rg.activity_id
                    FROM reward_grants rg
                    LEFT JOIN players p ON p.player_id = rg.player_id
                    LEFT JOIN activities a ON a.activity_id = rg.activity_id
                    WHERE p.player_id IS NULL OR a.activity_id IS NULL
                    ORDER BY rg.grant_id""",
                ),
            },
            {
                "rule": "invalid_activity_status",
                "severity": "medium",
                "count": _count(
                    connection,
                    "SELECT COUNT(*) FROM activities WHERE status NOT IN ('active', 'inactive')",
                ),
                "samples": _samples(
                    connection,
                    """SELECT activity_id, status FROM activities
                    WHERE status NOT IN ('active', 'inactive') ORDER BY activity_id""",
                ),
            },
            {
                "rule": "negative_balance",
                "severity": "critical",
                "count": _count(
                    connection,
                    "SELECT COUNT(*) FROM players WHERE gem_balance < 0",
                ),
                "samples": _samples(
                    connection,
                    """SELECT player_id, gem_balance FROM players
                    WHERE gem_balance < 0 ORDER BY gem_balance, player_id""",
                ),
            },
        ]
    for finding in findings:
        finding["description"] = QUALITY_RULES[finding["rule"]]
        finding["passed"] = finding["count"] == 0
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": {
            "rules": len(findings),
            "failed_rules": sum(not item["passed"] for item in findings),
            "total_findings": sum(item["count"] for item in findings),
        },
        "findings": findings,
    }
