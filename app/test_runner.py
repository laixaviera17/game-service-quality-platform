from __future__ import annotations

import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable

from sqlalchemy import text

from .database import connect, initialize_database
from .service import GrantError, GrantNotFoundError, grant_reward, inventory, serialize


@dataclass(frozen=True)
class CaseOutcome:
    request: dict[str, object]
    response: dict[str, object]
    assertions: dict[str, object]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def create_test_run(trigger: str = "api") -> int:
    """Create a queued service-test run before a worker (or local process) starts it."""
    initialize_database()
    with connect() as connection:
        cursor = connection.execute(
            text(
                """INSERT INTO test_runs (trigger, status, started_at, total_cases, passed_cases, failed_cases)
                VALUES (:trigger, 'queued', :started_at, 0, 0, 0)"""
            ),
            {"trigger": trigger, "started_at": _now()},
        )
        return int(cursor.lastrowid)


def _insert_fixture(prefix: str, *, activity_stock: int = 1, limit: int = 1, players_count: int = 1) -> tuple[list[str], str]:
    player_ids = [f"{prefix}_player_{index}" for index in range(1, players_count + 1)]
    activity_id = f"{prefix}_activity"
    with connect() as connection:
        connection.execute(
            text(
                """INSERT INTO activities
                (activity_id, name, reward_gems, stock, initial_stock, per_player_limit, status)
                VALUES (:activity_id, :name, 100, :stock, :initial_stock, :limit, 'active')"""
            ),
            {
                "activity_id": activity_id,
                "name": f"自动化测试活动-{prefix[-8:]}",
                "stock": activity_stock,
                "initial_stock": activity_stock,
                "limit": limit,
            },
        )
        connection.execute(
            text(
                """INSERT INTO players (player_id, nickname, gem_balance, account_status)
                VALUES (:player_id, :nickname, 0, 'active')"""
            ),
            [
                {"player_id": player_id, "nickname": f"自动化测试玩家-{index}"}
                for index, player_id in enumerate(player_ids, start=1)
            ],
        )
    return player_ids, activity_id


def _clean_fixture(prefix: str) -> None:
    with connect() as connection:
        connection.execute(text("DELETE FROM reward_grants WHERE player_id LIKE :prefix OR activity_id LIKE :prefix"), {"prefix": f"{prefix}%"})
        connection.execute(text("DELETE FROM players WHERE player_id LIKE :prefix"), {"prefix": f"{prefix}%"})
        connection.execute(text("DELETE FROM activities WHERE activity_id LIKE :prefix"), {"prefix": f"{prefix}%"})


def _normal_grant(prefix: str) -> CaseOutcome:
    players, activity = _insert_fixture(prefix)
    result = grant_reward(players[0], activity, f"{prefix}_normal")
    player = inventory(players[0])
    with connect() as connection:
        stock = int(connection.execute(text("SELECT stock FROM activities WHERE activity_id = :activity_id"), {"activity_id": activity}).scalar_one())
    assert result.status == "success"
    assert player["gem_balance"] == 100
    assert stock == 0
    return CaseOutcome(
        {"player_id": players[0], "activity_id": activity, "idempotency_key": f"{prefix}_normal"},
        {"grant": serialize(result), "inventory": player, "stock": stock},
        {"expected": {"status": "success", "balance": 100, "stock": 0}, "actual": {"status": result.status, "balance": player["gem_balance"], "stock": stock}},
    )


def _idempotent_retry(prefix: str) -> CaseOutcome:
    players, activity = _insert_fixture(prefix)
    key = f"{prefix}_retry"
    first = grant_reward(players[0], activity, key)
    retry = grant_reward(players[0], activity, key)
    player = inventory(players[0])
    assert retry.duplicated is True
    assert player["gem_balance"] == 100
    return CaseOutcome(
        {"player_id": players[0], "activity_id": activity, "idempotency_key": key, "attempts": 2},
        {"first": serialize(first), "retry": serialize(retry), "inventory": player},
        {"expected": {"retry_duplicated": True, "balance": 100}, "actual": {"retry_duplicated": retry.duplicated, "balance": player["gem_balance"]}},
    )


def _claim_limit(prefix: str) -> CaseOutcome:
    players, activity = _insert_fixture(prefix, activity_stock=2, limit=1)
    grant_reward(players[0], activity, f"{prefix}_first")
    try:
        grant_reward(players[0], activity, f"{prefix}_second")
    except GrantError as error:
        error_message = str(error)
    else:
        raise AssertionError("第二次领取应被单玩家领取上限拒绝")
    player = inventory(players[0])
    assert error_message == "玩家领取次数已达活动上限"
    assert player["gem_balance"] == 100
    return CaseOutcome(
        {"player_id": players[0], "activity_id": activity, "attempts": 2},
        {"second_attempt_error": error_message, "inventory": player},
        {"expected": {"error": "玩家领取次数已达活动上限", "balance": 100}, "actual": {"error": error_message, "balance": player["gem_balance"]}},
    )


def _suspended_account(prefix: str) -> CaseOutcome:
    players, activity = _insert_fixture(prefix)
    with connect() as connection:
        connection.execute(text("UPDATE players SET account_status = 'suspended' WHERE player_id = :player_id"), {"player_id": players[0]})
    try:
        grant_reward(players[0], activity, f"{prefix}_suspended")
    except GrantError as error:
        error_message = str(error)
    else:
        raise AssertionError("冻结账号应被拒绝")
    player = inventory(players[0])
    assert error_message == "玩家账号不可领取活动奖励"
    assert player["gem_balance"] == 0
    return CaseOutcome(
        {"player_id": players[0], "activity_id": activity, "account_status": "suspended"},
        {"error": error_message, "inventory": player},
        {"expected": {"error": "玩家账号不可领取活动奖励", "balance": 0}, "actual": {"error": error_message, "balance": player["gem_balance"]}},
    )


def _stock_race(prefix: str) -> CaseOutcome:
    players, activity = _insert_fixture(prefix, players_count=2)

    def attempt(player_id: str, key: str) -> dict[str, object]:
        try:
            return {"result": serialize(grant_reward(player_id, activity, key))}
        except GrantError as error:
            return {"error": str(error)}

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda item: attempt(*item), [(players[0], f"{prefix}_concurrent_1"), (players[1], f"{prefix}_concurrent_2")]))
    with connect() as connection:
        stock = int(connection.execute(text("SELECT stock FROM activities WHERE activity_id = :activity_id"), {"activity_id": activity}).scalar_one())
        total_balance = int(connection.execute(text("SELECT SUM(gem_balance) FROM players WHERE player_id LIKE :prefix"), {"prefix": f"{prefix}%"}).scalar_one())
    success_count = sum("result" in item for item in outcomes)
    shortage_count = sum(item.get("error") == "奖励库存不足" for item in outcomes)
    assert success_count == 1
    assert shortage_count == 1
    assert stock == 0
    assert total_balance == 100
    return CaseOutcome(
        {"activity_id": activity, "stock": 1, "parallel_requests": 2},
        {"outcomes": outcomes, "stock": stock, "total_balance": total_balance},
        {"expected": {"success_count": 1, "stock_shortage_count": 1, "stock": 0, "total_balance": 100}, "actual": {"success_count": success_count, "stock_shortage_count": shortage_count, "stock": stock, "total_balance": total_balance}},
    )


SCENARIOS: tuple[tuple[str, str, Callable[[str], CaseOutcome]], ...] = (
    ("normal_grant", "正常发奖后库存与余额一致", _normal_grant),
    ("idempotent_retry", "同一幂等键重试不重复发奖", _idempotent_retry),
    ("per_player_limit", "单玩家领取上限阻断且无副作用", _claim_limit),
    ("suspended_account", "冻结账号无法领取奖励", _suspended_account),
    ("stock_race", "并发请求不会超卖库存", _stock_race),
)


def _save_case_result(run_id: int, code: str, title: str, status: str, duration_ms: int, outcome: CaseOutcome | None, error_message: str | None) -> None:
    payload = outcome or CaseOutcome({}, {}, {})
    with connect() as connection:
        connection.execute(
            text(
                """INSERT INTO test_case_results
                (run_id, case_code, title, status, duration_ms, request_json, response_json, assertion_json, error_message)
                VALUES (:run_id, :case_code, :title, :status, :duration_ms, :request_json, :response_json, :assertion_json, :error_message)"""
            ),
            {"run_id": run_id, "case_code": code, "title": title, "status": status, "duration_ms": duration_ms, "request_json": json.dumps(payload.request, ensure_ascii=False), "response_json": json.dumps(payload.response, ensure_ascii=False), "assertion_json": json.dumps(payload.assertions, ensure_ascii=False), "error_message": error_message},
        )


def execute_test_run(run_id: int) -> dict[str, object]:
    """Execute isolated service-level scenarios and persist each request, result and assertion."""
    initialize_database()
    with connect() as connection:
        exists = connection.execute(text("SELECT run_id FROM test_runs WHERE run_id = :run_id"), {"run_id": run_id}).scalar_one_or_none()
        if exists is None:
            raise GrantNotFoundError("测试运行不存在")
        connection.execute(text("UPDATE test_runs SET status = 'running', started_at = :started_at, error_message = NULL WHERE run_id = :run_id"), {"run_id": run_id, "started_at": _now()})

    passed = failed = errors = 0
    for index, (code, title, scenario) in enumerate(SCENARIOS, start=1):
        prefix = f"qa_{run_id}_{index}_{uuid.uuid4().hex[:8]}"
        started = time.perf_counter()
        outcome: CaseOutcome | None = None
        status = "passed"
        error_message: str | None = None
        try:
            outcome = scenario(prefix)
            passed += 1
        except AssertionError as error:
            status = "failed"
            failed += 1
            error_message = str(error)
        except Exception as error:
            status = "error"
            errors += 1
            error_message = f"{type(error).__name__}: {error}"
        finally:
            _clean_fixture(prefix)
        _save_case_result(run_id, code, title, status, int((time.perf_counter() - started) * 1000), outcome, error_message)

    run_status = "passed" if failed == 0 and errors == 0 else "failed"
    with connect() as connection:
        connection.execute(
            text("""UPDATE test_runs SET status = :status, completed_at = :completed_at, total_cases = :total_cases, passed_cases = :passed_cases, failed_cases = :failed_cases, error_message = :error_message WHERE run_id = :run_id"""),
            {"status": run_status, "completed_at": _now(), "total_cases": len(SCENARIOS), "passed_cases": passed, "failed_cases": failed + errors, "error_message": None if errors == 0 else f"{errors} 个场景出现执行错误", "run_id": run_id},
        )
    return get_test_run(run_id) or {}


def get_test_run(run_id: int) -> dict[str, object] | None:
    initialize_database()
    with connect() as connection:
        run = connection.execute(text("SELECT * FROM test_runs WHERE run_id = :run_id"), {"run_id": run_id}).mappings().first()
        if not run:
            return None
        cases = connection.execute(text("SELECT * FROM test_case_results WHERE run_id = :run_id ORDER BY result_id"), {"run_id": run_id}).mappings().all()
    return {
        "run_id": run["run_id"], "trigger": run["trigger"], "status": run["status"], "started_at": run["started_at"], "completed_at": run["completed_at"], "error_message": run["error_message"],
        "summary": {"total_cases": run["total_cases"], "passed_cases": run["passed_cases"], "failed_cases": run["failed_cases"]},
        "cases": [{"case_code": case["case_code"], "title": case["title"], "status": case["status"], "duration_ms": case["duration_ms"], "request": json.loads(case["request_json"]), "response": json.loads(case["response_json"]), "assertions": json.loads(case["assertion_json"]), "error_message": case["error_message"]} for case in cases],
    }


def list_test_runs(limit: int = 12) -> list[dict[str, object]]:
    initialize_database()
    with connect() as connection:
        rows = connection.execute(text("SELECT * FROM test_runs ORDER BY run_id DESC LIMIT :limit"), {"limit": limit}).mappings().all()
    return [{"run_id": row["run_id"], "trigger": row["trigger"], "status": row["status"], "started_at": row["started_at"], "completed_at": row["completed_at"], "summary": {"total_cases": row["total_cases"], "passed_cases": row["passed_cases"], "failed_cases": row["failed_cases"]}} for row in rows]
