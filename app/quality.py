from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import text

from .database import connect, initialize_database


SAMPLE_LIMIT = 3
RULE_METADATA = {
    "duplicate_reward": {
        "title": "重复发奖",
        "description": "同一玩家在同一活动获得多次成功奖励",
        "severity": "high",
    },
    "orphan_grant": {
        "title": "孤儿发奖记录",
        "description": "发奖记录关联的玩家或活动不存在",
        "severity": "critical",
    },
    "invalid_activity_status": {
        "title": "非法活动状态",
        "description": "活动状态不在允许枚举范围内",
        "severity": "medium",
    },
    "negative_balance": {
        "title": "负余额",
        "description": "玩家宝石余额为负数",
        "severity": "critical",
    },
    "reward_amount_mismatch": {
        "title": "奖励金额不一致",
        "description": "成功发奖记录的奖励值与活动配置不一致",
        "severity": "high",
    },
    "stock_mismatch": {
        "title": "库存账实不一致",
        "description": "活动当前库存与初始库存减成功发奖次数不一致",
        "severity": "critical",
    },
}


def _count(connection, statement: str) -> int:
    return int(connection.execute(text(statement)).scalar_one())


def _samples(connection, statement: str) -> list[dict[str, object]]:
    return [dict(row) for row in connection.execute(text(statement)).mappings().fetchmany(SAMPLE_LIMIT)]


def _evaluate(connection) -> list[dict[str, object]]:
    results = [
        {
            "rule": "duplicate_reward",
            "count": _count(
                connection,
                """SELECT COUNT(*) FROM (
                    SELECT player_id, activity_id FROM reward_grants
                    WHERE status = 'success'
                    GROUP BY player_id, activity_id HAVING COUNT(*) > 1
                ) AS duplicate_groups""",
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
        {
            "rule": "reward_amount_mismatch",
            "count": _count(
                connection,
                """SELECT COUNT(*) FROM reward_grants rg
                JOIN activities a ON a.activity_id = rg.activity_id
                WHERE rg.status = 'success' AND rg.reward_gems != a.reward_gems""",
            ),
            "samples": _samples(
                connection,
                """SELECT rg.grant_id, rg.activity_id, rg.reward_gems AS grant_reward,
                a.reward_gems AS configured_reward
                FROM reward_grants rg JOIN activities a ON a.activity_id = rg.activity_id
                WHERE rg.status = 'success' AND rg.reward_gems != a.reward_gems
                ORDER BY rg.grant_id""",
            ),
        },
        {
            "rule": "stock_mismatch",
            "count": _count(
                connection,
                """SELECT COUNT(*) FROM (
                    SELECT a.activity_id FROM activities a
                    LEFT JOIN reward_grants rg
                    ON rg.activity_id = a.activity_id AND rg.status = 'success'
                    GROUP BY a.activity_id
                    HAVING a.stock != a.initial_stock - COUNT(rg.grant_id)
                ) AS stock_differences""",
            ),
            "samples": _samples(
                connection,
                """SELECT a.activity_id, a.initial_stock, a.stock,
                COUNT(rg.grant_id) AS successful_grants,
                a.initial_stock - COUNT(rg.grant_id) AS expected_stock
                FROM activities a LEFT JOIN reward_grants rg
                ON rg.activity_id = a.activity_id AND rg.status = 'success'
                GROUP BY a.activity_id
                HAVING a.stock != a.initial_stock - COUNT(rg.grant_id)
                ORDER BY a.activity_id""",
            ),
        },
    ]
    for finding in results:
        metadata = RULE_METADATA[finding["rule"]]
        finding.update(metadata)
        finding["passed"] = finding["count"] == 0
    return results


def _summary(findings: list[dict[str, object]]) -> dict[str, int]:
    return {
        "rules": len(findings),
        "failed_rules": sum(not item["passed"] for item in findings),
        "total_findings": sum(int(item["count"]) for item in findings),
    }


def _save_run(connection, report: dict[str, object]) -> int:
    summary = report["summary"]
    cursor = connection.execute(
        text("""INSERT INTO quality_runs
           (`trigger`, started_at, completed_at, status, rules, failed_rules, total_findings)
           VALUES (:trigger, :started_at, :completed_at, :status, :rules, :failed_rules, :total_findings)"""),
        {
            "trigger": report["trigger"], "started_at": report["generated_at"],
            "completed_at": report["generated_at"], "status": report["status"],
            "rules": summary["rules"], "failed_rules": summary["failed_rules"],
            "total_findings": summary["total_findings"],
        },
    )
    run_id = int(cursor.lastrowid)
    for finding in report["findings"]:
        connection.execute(
            text("""INSERT INTO quality_run_findings
               (run_id, rule, title, description, severity, finding_count, passed, samples_json)
               VALUES (:run_id, :rule, :title, :description, :severity, :finding_count, :passed, :samples_json)"""),
            {
                "run_id": run_id, "rule": finding["rule"], "title": finding["title"],
                "description": finding["description"], "severity": finding["severity"],
                "finding_count": finding["count"], "passed": int(finding["passed"]),
                "samples_json": json.dumps(finding["samples"], ensure_ascii=False),
            },
        )
    return run_id


def run_quality_check(*, persist: bool = False, trigger: str = "script") -> dict[str, object]:
    """Evaluate all rules and optionally persist a local execution snapshot."""
    initialize_database()
    generated_at = datetime.now(UTC).isoformat()
    with connect() as connection:
        findings = _evaluate(connection)
        summary = _summary(findings)
        report: dict[str, object] = {
            "run_id": None,
            "trigger": trigger,
            "generated_at": generated_at,
            "status": "failed" if summary["failed_rules"] else "passed",
            "summary": summary,
            "findings": findings,
        }
        if persist:
            report["run_id"] = _save_run(connection, report)
    return report


def get_quality_run(run_id: int) -> dict[str, object] | None:
    initialize_database()
    with connect() as connection:
        run = connection.execute(text("SELECT * FROM quality_runs WHERE run_id = :run_id"), {"run_id": run_id}).mappings().first()
        if not run:
            return None
        finding_rows = connection.execute(
            text("""SELECT rule, title, description, severity, finding_count, passed, samples_json
            FROM quality_run_findings WHERE run_id = :run_id ORDER BY rule"""),
            {"run_id": run_id},
        ).mappings().all()
    return {
        "run_id": run["run_id"],
        "trigger": run["trigger"],
        "generated_at": run["completed_at"],
        "status": run["status"],
        "summary": {
            "rules": run["rules"],
            "failed_rules": run["failed_rules"],
            "total_findings": run["total_findings"],
        },
        "findings": [
            {
                "rule": row["rule"],
                "title": row["title"],
                "description": row["description"],
                "severity": row["severity"],
                "count": row["finding_count"],
                "passed": bool(row["passed"]),
                "samples": json.loads(row["samples_json"]),
            }
            for row in finding_rows
        ],
    }


def list_quality_runs(limit: int = 12) -> list[dict[str, object]]:
    initialize_database()
    with connect() as connection:
        rows = connection.execute(
            text("""SELECT run_id, `trigger`, completed_at, status, rules, failed_rules, total_findings
            FROM quality_runs ORDER BY run_id DESC LIMIT :limit"""),
            {"limit": limit},
        ).mappings().all()
    return [
        {
            "run_id": row["run_id"],
            "trigger": row["trigger"],
            "generated_at": row["completed_at"],
            "status": row["status"],
            "summary": {
                "rules": row["rules"],
                "failed_rules": row["failed_rules"],
                "total_findings": row["total_findings"],
            },
        }
        for row in rows
    ]
