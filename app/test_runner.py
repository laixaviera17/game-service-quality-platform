from __future__ import annotations

import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable, Mapping

from sqlalchemy import text

from .database import connect, initialize_database
from .service import GrantError, GrantNotFoundError, grant_reward, inventory, serialize


@dataclass(frozen=True)
class CaseOutcome:
    request: dict[str, object]
    response: dict[str, object]
    assertions: dict[str, object]


Scenario = Callable[[str, dict[str, object]], CaseOutcome]
DEFAULT_OPTIONS: dict[str, object] = {
    "stock": 1,
    "per_player_limit": 1,
    "player_status": "suspended",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _insert_fixture(
    prefix: str, *, activity_stock: int = 1, limit: int = 1, players_count: int = 1
) -> tuple[list[str], str]:
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
        connection.execute(
            text("DELETE FROM reward_grants WHERE player_id LIKE :prefix OR activity_id LIKE :prefix"),
            {"prefix": f"{prefix}%"},
        )
        connection.execute(text("DELETE FROM players WHERE player_id LIKE :prefix"), {"prefix": f"{prefix}%"})
        connection.execute(text("DELETE FROM activities WHERE activity_id LIKE :prefix"), {"prefix": f"{prefix}%"})


def _normal_grant(prefix: str, options: dict[str, object]) -> CaseOutcome:
    stock_before = int(options["stock"])
    players, activity = _insert_fixture(prefix, activity_stock=stock_before)
    result = grant_reward(players[0], activity, f"{prefix}_normal")
    player = inventory(players[0])
    with connect() as connection:
        stock = int(
            connection.execute(
                text("SELECT stock FROM activities WHERE activity_id = :activity_id"),
                {"activity_id": activity},
            ).scalar_one()
        )
    assert result.status == "success"
    assert player["gem_balance"] == 100
    assert stock == stock_before - 1
    return CaseOutcome(
        {"player_id": players[0], "activity_id": activity, "idempotency_key": f"{prefix}_normal", "stock_before": stock_before},
        {"grant": serialize(result), "inventory": player, "stock": stock},
        {"expected": {"status": "success", "balance": 100, "stock": stock_before - 1}, "actual": {"status": result.status, "balance": player["gem_balance"], "stock": stock}},
    )


def _idempotent_retry(prefix: str, options: dict[str, object]) -> CaseOutcome:
    players, activity = _insert_fixture(prefix, activity_stock=int(options["stock"]))
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


def _claim_limit(prefix: str, options: dict[str, object]) -> CaseOutcome:
    limit = int(options["per_player_limit"])
    attempts = limit + 1
    players, activity = _insert_fixture(prefix, activity_stock=max(int(options["stock"]), attempts), limit=limit)
    for attempt in range(limit):
        grant_reward(players[0], activity, f"{prefix}_claim_{attempt}")
    try:
        grant_reward(players[0], activity, f"{prefix}_over_limit")
    except GrantError as error:
        error_message = str(error)
    else:
        raise AssertionError("超过单玩家领取上限的请求应被拒绝")
    player = inventory(players[0])
    expected_balance = 100 * limit
    assert error_message == "玩家领取次数已达活动上限"
    assert player["gem_balance"] == expected_balance
    return CaseOutcome(
        {"player_id": players[0], "activity_id": activity, "per_player_limit": limit, "attempts": attempts},
        {"over_limit_error": error_message, "inventory": player},
        {"expected": {"error": "玩家领取次数已达活动上限", "balance": expected_balance}, "actual": {"error": error_message, "balance": player["gem_balance"]}},
    )


def _account_status(prefix: str, options: dict[str, object]) -> CaseOutcome:
    status = str(options["player_status"])
    players, activity = _insert_fixture(prefix, activity_stock=int(options["stock"]))
    with connect() as connection:
        connection.execute(
            text("UPDATE players SET account_status = :status WHERE player_id = :player_id"),
            {"status": status, "player_id": players[0]},
        )
    if status == "suspended":
        try:
            grant_reward(players[0], activity, f"{prefix}_account")
        except GrantError as error:
            result: dict[str, object] = {"error": str(error)}
        else:
            raise AssertionError("冻结账号应被拒绝")
        expected = {"error": "玩家账号不可领取活动奖励", "balance": 0}
        actual_status = result["error"]
    else:
        grant = grant_reward(players[0], activity, f"{prefix}_account")
        result = {"grant": serialize(grant)}
        expected = {"status": "success", "balance": 100}
        actual_status = grant.status
    player = inventory(players[0])
    result["inventory"] = player
    assert actual_status == (expected.get("error") or expected["status"])
    assert player["gem_balance"] == expected["balance"]
    return CaseOutcome(
        {"player_id": players[0], "activity_id": activity, "account_status": status},
        result,
        {"expected": expected, "actual": {"outcome": actual_status, "balance": player["gem_balance"]}},
    )


def _stock_race(prefix: str, options: dict[str, object]) -> CaseOutcome:
    stock_before = int(options["stock"])
    players, activity = _insert_fixture(prefix, activity_stock=stock_before, players_count=2)

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
    expected_successes = min(stock_before, 2)
    expected_shortages = 2 - expected_successes
    success_count = sum("result" in item for item in outcomes)
    shortage_count = sum(item.get("error") == "奖励库存不足" for item in outcomes)
    assert success_count == expected_successes
    assert shortage_count == expected_shortages
    assert stock == stock_before - expected_successes
    assert total_balance == expected_successes * 100
    return CaseOutcome(
        {"activity_id": activity, "stock_before": stock_before, "parallel_requests": 2},
        {"outcomes": outcomes, "stock": stock, "total_balance": total_balance},
        {"expected": {"success_count": expected_successes, "stock_shortage_count": expected_shortages, "stock": stock_before - expected_successes, "total_balance": expected_successes * 100}, "actual": {"success_count": success_count, "stock_shortage_count": shortage_count, "stock": stock, "total_balance": total_balance}},
    )


SCENARIOS: tuple[tuple[str, str, Scenario], ...] = (
    ("normal_grant", "正常发奖后库存与余额一致", _normal_grant),
    ("idempotent_retry", "同一幂等键重试不重复发奖", _idempotent_retry),
    ("per_player_limit", "单玩家领取上限阻断且无副作用", _claim_limit),
    ("suspended_account", "账号状态与领奖权限一致", _account_status),
    ("stock_race", "并发请求不会超卖库存", _stock_race),
)
SCENARIO_MAP = {code: (title, scenario) for code, title, scenario in SCENARIOS}


def available_scenarios() -> list[dict[str, str]]:
    return [{"code": code, "title": title} for code, title, _ in SCENARIOS]


def _normalize_config(case_codes: list[str] | None, options: Mapping[str, object] | None) -> tuple[list[str], dict[str, object]]:
    selected = [code for code, _, _ in SCENARIOS] if case_codes is None else list(dict.fromkeys(case_codes))
    unknown = sorted(set(selected) - set(SCENARIO_MAP))
    if unknown:
        raise ValueError(f"未知测试场景：{', '.join(unknown)}")
    if not selected:
        raise ValueError("至少选择一个测试场景")
    merged = {**DEFAULT_OPTIONS, **(dict(options) if options else {})}
    try:
        merged["stock"] = int(merged["stock"])
        merged["per_player_limit"] = int(merged["per_player_limit"])
    except (TypeError, ValueError) as error:
        raise ValueError("库存和单玩家领取上限必须为整数") from error
    if not 1 <= int(merged["stock"]) <= 10:
        raise ValueError("库存参数范围为 1 到 10")
    if not 1 <= int(merged["per_player_limit"]) <= 3:
        raise ValueError("单玩家领取上限范围为 1 到 3")
    if merged["player_status"] not in {"active", "suspended"}:
        raise ValueError("玩家状态仅支持 active 或 suspended")
    return selected, merged


def create_test_run(
    trigger: str = "api", case_codes: list[str] | None = None, options: Mapping[str, object] | None = None
) -> int:
    """Create a queued service-test run and persist its selected scenarios and parameters."""
    initialize_database()
    selected, normalized_options = _normalize_config(case_codes, options)
    with connect() as connection:
        cursor = connection.execute(
            text("""INSERT INTO test_runs (`trigger`, status, started_at, total_cases, passed_cases, failed_cases)
                VALUES (:trigger, 'queued', :started_at, 0, 0, 0)"""),
            {"trigger": trigger, "started_at": _now()},
        )
        run_id = int(cursor.lastrowid)
        connection.execute(
            text("""INSERT INTO test_run_configs (run_id, scenario_codes_json, options_json)
                VALUES (:run_id, :scenario_codes_json, :options_json)"""),
            {"run_id": run_id, "scenario_codes_json": json.dumps(selected), "options_json": json.dumps(normalized_options)},
        )
    return run_id


def _run_config(connection, run_id: int) -> tuple[list[str], dict[str, object]]:
    row = connection.execute(text("SELECT scenario_codes_json, options_json FROM test_run_configs WHERE run_id = :run_id"), {"run_id": run_id}).mappings().first()
    if not row:
        return _normalize_config(None, None)
    return _normalize_config(json.loads(row["scenario_codes_json"]), json.loads(row["options_json"]))


def rerun_test_run(run_id: int) -> int:
    initialize_database()
    with connect() as connection:
        selected, options = _run_config(connection, run_id)
        exists = connection.execute(text("SELECT run_id FROM test_runs WHERE run_id = :run_id"), {"run_id": run_id}).scalar_one_or_none()
    if exists is None:
        raise GrantNotFoundError("测试运行不存在")
    return create_test_run(trigger="rerun", case_codes=selected, options=options)


def _save_case_result(run_id: int, code: str, title: str, status: str, duration_ms: int, outcome: CaseOutcome | None, error_message: str | None) -> None:
    payload = outcome or CaseOutcome({}, {}, {})
    with connect() as connection:
        connection.execute(
            text("""INSERT INTO test_case_results
                (run_id, case_code, title, status, duration_ms, request_json, response_json, assertion_json, error_message)
                VALUES (:run_id, :case_code, :title, :status, :duration_ms, :request_json, :response_json, :assertion_json, :error_message)"""),
            {"run_id": run_id, "case_code": code, "title": title, "status": status, "duration_ms": duration_ms, "request_json": json.dumps(payload.request, ensure_ascii=False), "response_json": json.dumps(payload.response, ensure_ascii=False), "assertion_json": json.dumps(payload.assertions, ensure_ascii=False), "error_message": error_message},
        )


def execute_test_run(run_id: int) -> dict[str, object]:
    """Execute configured service scenarios and persist each request, response and assertion."""
    initialize_database()
    with connect() as connection:
        selected, options = _run_config(connection, run_id)
        exists = connection.execute(text("SELECT run_id FROM test_runs WHERE run_id = :run_id"), {"run_id": run_id}).scalar_one_or_none()
        if exists is None:
            raise GrantNotFoundError("测试运行不存在")
        connection.execute(text("UPDATE test_runs SET status = 'running', started_at = :started_at, error_message = NULL WHERE run_id = :run_id"), {"run_id": run_id, "started_at": _now()})

    passed = failed = errors = 0
    for index, code in enumerate(selected, start=1):
        title, scenario = SCENARIO_MAP[code]
        prefix = f"qa_{run_id}_{index}_{uuid.uuid4().hex[:8]}"
        started = time.perf_counter()
        outcome: CaseOutcome | None = None
        status = "passed"
        error_message: str | None = None
        try:
            outcome = scenario(prefix, options)
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
            {"status": run_status, "completed_at": _now(), "total_cases": len(selected), "passed_cases": passed, "failed_cases": failed + errors, "error_message": None if errors == 0 else f"{errors} 个场景出现执行错误", "run_id": run_id},
        )
    return get_test_run(run_id) or {}


def get_test_run(run_id: int) -> dict[str, object] | None:
    initialize_database()
    with connect() as connection:
        run = connection.execute(text("SELECT * FROM test_runs WHERE run_id = :run_id"), {"run_id": run_id}).mappings().first()
        if not run:
            return None
        selected, options = _run_config(connection, run_id)
        cases = connection.execute(text("SELECT * FROM test_case_results WHERE run_id = :run_id ORDER BY result_id"), {"run_id": run_id}).mappings().all()
    return {
        "run_id": run["run_id"], "trigger": run["trigger"], "status": run["status"], "started_at": run["started_at"], "completed_at": run["completed_at"], "error_message": run["error_message"],
        "config": {"case_codes": selected, "options": options},
        "summary": {"total_cases": run["total_cases"], "passed_cases": run["passed_cases"], "failed_cases": run["failed_cases"]},
        "cases": [{"case_code": case["case_code"], "title": case["title"], "status": case["status"], "duration_ms": case["duration_ms"], "request": json.loads(case["request_json"]), "response": json.loads(case["response_json"]), "assertions": json.loads(case["assertion_json"]), "error_message": case["error_message"]} for case in cases],
    }


def list_test_runs(limit: int = 12) -> list[dict[str, object]]:
    initialize_database()
    with connect() as connection:
        rows = connection.execute(text("SELECT * FROM test_runs ORDER BY run_id DESC LIMIT :limit"), {"limit": limit}).mappings().all()
    return [{"run_id": row["run_id"], "trigger": row["trigger"], "status": row["status"], "started_at": row["started_at"], "completed_at": row["completed_at"], "summary": {"total_cases": row["total_cases"], "passed_cases": row["passed_cases"], "failed_cases": row["failed_cases"]}} for row in rows]


def get_test_run_trend(limit: int = 12) -> dict[str, object]:
    runs = list_test_runs(limit)
    completed = [run for run in runs if run["status"] in {"passed", "failed"}]
    passed = sum(run["status"] == "passed" for run in completed)
    return {
        "total_runs": len(completed),
        "passed_runs": passed,
        "failed_runs": len(completed) - passed,
        "pass_rate": round(passed / len(completed) * 100, 1) if completed else 0,
        "points": list(reversed(completed)),
    }
