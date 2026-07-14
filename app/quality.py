from __future__ import annotations

from datetime import UTC, datetime

from .database import connect, initialize_database


QUALITY_RULES = {
    "duplicate_reward": "同一玩家在同一活动获得多次成功奖励",
    "orphan_grant": "发奖记录关联的玩家或活动不存在",
    "invalid_activity_status": "活动状态不在允许枚举范围内",
    "negative_balance": "玩家宝石余额为负数",
}


def _count(connection, statement: str) -> int:
    return int(connection.execute(statement).fetchone()[0])


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
            },
            {
                "rule": "invalid_activity_status",
                "severity": "medium",
                "count": _count(
                    connection,
                    "SELECT COUNT(*) FROM activities WHERE status NOT IN ('active', 'inactive')",
                ),
            },
            {
                "rule": "negative_balance",
                "severity": "critical",
                "count": _count(
                    connection,
                    "SELECT COUNT(*) FROM players WHERE gem_balance < 0",
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
