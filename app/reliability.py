from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from .database import connect, get_engine, initialize_database


REWARD_GEMS = 100
SCENARIOS = {
    "duplicate_request": {
        "title": "重复请求",
        "description": "同一幂等键连续提交两次，只应创建一张订单、一条 Outbox 事件和一笔账本流水。",
    },
    "acknowledgement_loss": {
        "title": "确认丢失后重试",
        "description": "首次消费已写入账本但确认丢失；重试消费不得再次增加余额。",
    },
    "concurrent_consume": {
        "title": "并发重复消费",
        "description": "同一事件被两个消费者同时处理；账本唯一约束保证最终只产生一笔入账。",
    },
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _event(run_id: int, kind: str, message: str, **payload: object) -> None:
    with connect() as connection:
        connection.execute(
            text("""INSERT INTO reliability_events (run_id, kind, message, payload_json, created_at)
                VALUES (:run_id, :kind, :message, :payload_json, :created_at)"""),
            {
                "run_id": run_id,
                "kind": kind,
                "message": message,
                "payload_json": json.dumps(payload, ensure_ascii=False),
                "created_at": _now(),
            },
        )


def available_reliability_scenarios() -> list[dict[str, str]]:
    return [{"code": code, **metadata} for code, metadata in SCENARIOS.items()]


def create_reliability_run(scenario: str, trigger: str = "dashboard") -> int:
    if scenario not in SCENARIOS:
        raise ValueError("不支持的可靠性实验场景")
    initialize_database()
    with connect() as connection:
        cursor = connection.execute(
            text("""INSERT INTO reliability_runs (scenario, `trigger`, status, started_at)
                VALUES (:scenario, :trigger, 'queued', :started_at)"""),
            {"scenario": scenario, "trigger": trigger, "started_at": _now()},
        )
        return int(cursor.lastrowid)


def _create_player(run_id: int) -> str:
    player_id = f"reliability_{run_id}_player"
    with connect() as connection:
        connection.execute(
            text("""INSERT INTO players (player_id, nickname, gem_balance, account_status)
                VALUES (:player_id, :nickname, 0, 'active')"""),
            {"player_id": player_id, "nickname": f"可靠性实验玩家-{run_id}"},
        )
    return player_id


def _request_reward(run_id: int, player_id: str, idempotency_key: str) -> tuple[str, bool]:
    """Persist the business order and its outbox event in one database transaction."""
    with connect() as connection:
        existing = connection.execute(
            text("SELECT order_id FROM delivery_orders WHERE idempotency_key = :key"),
            {"key": idempotency_key},
        ).scalar_one_or_none()
        if existing:
            order_id = str(existing)
            duplicate = True
        else:
            order_id = f"order_{run_id}_{uuid.uuid4().hex[:10]}"
            connection.execute(
                text("""INSERT INTO delivery_orders
                    (order_id, run_id, player_id, idempotency_key, reward_gems, status, created_at)
                    VALUES (:order_id, :run_id, :player_id, :idempotency_key, :reward_gems, 'pending', :created_at)"""),
                {"order_id": order_id, "run_id": run_id, "player_id": player_id, "idempotency_key": idempotency_key, "reward_gems": REWARD_GEMS, "created_at": _now()},
            )
            connection.execute(
                text("""INSERT INTO delivery_outbox_events (order_id, status, attempt_count, created_at)
                    VALUES (:order_id, 'pending', 0, :created_at)"""),
                {"order_id": order_id, "created_at": _now()},
            )
            duplicate = False
    _event(run_id, "request", "重复请求命中已有订单" if duplicate else "订单与 Outbox 事件在同一事务中创建", order_id=order_id, idempotency_key=idempotency_key, duplicate=duplicate)
    return order_id, duplicate


def _complete_delivery(connection, order_id: str) -> None:
    now = _now()
    connection.execute(
        text("UPDATE delivery_orders SET status = 'delivered', delivered_at = :now WHERE order_id = :order_id"),
        {"now": now, "order_id": order_id},
    )
    connection.execute(
        text("UPDATE delivery_outbox_events SET status = 'consumed', consumed_at = :now WHERE order_id = :order_id"),
        {"now": now, "order_id": order_id},
    )


def _deliver_once(run_id: int, order_id: str, *, lose_acknowledgement: bool = False) -> str:
    """Apply a delivery effect. A unique ledger row is the idempotency boundary for consumers."""
    _event(run_id, "consume", "消费者开始处理 Outbox 事件", order_id=order_id, lose_acknowledgement=lose_acknowledgement)
    try:
        with connect() as connection:
            order = connection.execute(
                text("SELECT player_id, reward_gems FROM delivery_orders WHERE order_id = :order_id"),
                {"order_id": order_id},
            ).mappings().one()
            ledger_exists = connection.execute(
                text("SELECT entry_id FROM delivery_wallet_ledger WHERE order_id = :order_id"),
                {"order_id": order_id},
            ).scalar_one_or_none()
            connection.execute(
                text("UPDATE delivery_outbox_events SET attempt_count = attempt_count + 1 WHERE order_id = :order_id"),
                {"order_id": order_id},
            )
            if ledger_exists:
                _complete_delivery(connection, order_id)
                outcome = "duplicate_consumer"
            else:
                connection.execute(
                    text("""INSERT INTO delivery_wallet_ledger (order_id, player_id, reward_gems, created_at)
                        VALUES (:order_id, :player_id, :reward_gems, :created_at)"""),
                    {"order_id": order_id, "player_id": order["player_id"], "reward_gems": order["reward_gems"], "created_at": _now()},
                )
                connection.execute(
                    text("UPDATE players SET gem_balance = gem_balance + :reward_gems WHERE player_id = :player_id"),
                    {"reward_gems": order["reward_gems"], "player_id": order["player_id"]},
                )
                if lose_acknowledgement:
                    outcome = "acknowledgement_lost"
                else:
                    _complete_delivery(connection, order_id)
                    outcome = "effect_applied"
    except IntegrityError:
        # Another consumer committed its ledger entry first. This attempt must not touch the balance.
        with connect() as connection:
            connection.execute(
                text("UPDATE delivery_outbox_events SET attempt_count = attempt_count + 1 WHERE order_id = :order_id"),
                {"order_id": order_id},
            )
            _complete_delivery(connection, order_id)
        outcome = "duplicate_consumer"
    if outcome == "acknowledgement_lost":
        _event(run_id, "retry", "账本已提交，但模拟确认丢失；消息保持待消费并触发重试", order_id=order_id)
    elif outcome == "duplicate_consumer":
        _event(run_id, "dedupe", "检测到已存在账本流水，跳过余额变更并完成事件", order_id=order_id)
    else:
        _event(run_id, "effect", "账本流水与余额变更已提交，事件标记为已消费", order_id=order_id)
    return outcome


def _snapshot(run_id: int, player_id: str) -> dict[str, object]:
    with connect() as connection:
        orders = int(connection.execute(text("SELECT COUNT(*) FROM delivery_orders WHERE run_id = :run_id"), {"run_id": run_id}).scalar_one())
        outbox = connection.execute(
            text("SELECT COUNT(*) AS count, MAX(attempt_count) AS attempts FROM delivery_outbox_events o JOIN delivery_orders d ON d.order_id = o.order_id WHERE d.run_id = :run_id"),
            {"run_id": run_id},
        ).mappings().one()
        ledger = int(connection.execute(text("SELECT COUNT(*) FROM delivery_wallet_ledger l JOIN delivery_orders d ON d.order_id = l.order_id WHERE d.run_id = :run_id"), {"run_id": run_id}).scalar_one())
        balance = int(connection.execute(text("SELECT gem_balance FROM players WHERE player_id = :player_id"), {"player_id": player_id}).scalar_one())
        statuses = connection.execute(text("SELECT status FROM delivery_orders WHERE run_id = :run_id"), {"run_id": run_id}).scalars().all()
    return {"orders": orders, "outbox_events": int(outbox["count"]), "delivery_attempts": int(outbox["attempts"] or 0), "ledger_entries": ledger, "balance": balance, "delivery_statuses": list(statuses)}


def _assert_invariants(run_id: int, player_id: str, scenario: str) -> dict[str, object]:
    actual = _snapshot(run_id, player_id)
    expected = {"orders": 1, "outbox_events": 1, "ledger_entries": 1, "balance": REWARD_GEMS, "delivery_statuses": ["delivered"]}
    if scenario == "duplicate_request":
        expected["delivery_attempts_at_least"] = 1
    else:
        expected["delivery_attempts_at_least"] = 2
    passed = (
        actual["orders"] == expected["orders"]
        and actual["outbox_events"] == expected["outbox_events"]
        and actual["ledger_entries"] == expected["ledger_entries"]
        and actual["balance"] == expected["balance"]
        and actual["delivery_statuses"] == expected["delivery_statuses"]
        and actual["delivery_attempts"] >= expected["delivery_attempts_at_least"]
    )
    return {"passed": passed, "expected": expected, "actual": actual}


def execute_reliability_run(run_id: int) -> dict[str, object]:
    initialize_database()
    with connect() as connection:
        run = connection.execute(text("SELECT scenario FROM reliability_runs WHERE run_id = :run_id"), {"run_id": run_id}).mappings().first()
        if not run:
            raise ValueError("可靠性实验不存在")
        scenario = str(run["scenario"])
        connection.execute(text("UPDATE reliability_runs SET status = 'running', started_at = :started_at, error_message = NULL WHERE run_id = :run_id"), {"started_at": _now(), "run_id": run_id})
    try:
        player_id = _create_player(run_id)
        _event(run_id, "setup", "创建实验玩家，初始余额为 0", player_id=player_id, initial_balance=0)
        key = f"reliability_{run_id}_request"
        order_id, duplicate = _request_reward(run_id, player_id, key)
        if scenario == "duplicate_request":
            repeated_order, repeated_duplicate = _request_reward(run_id, player_id, key)
            if repeated_order != order_id or not repeated_duplicate or duplicate:
                raise AssertionError("重复请求没有稳定命中同一张订单")
            _deliver_once(run_id, order_id)
        elif scenario == "acknowledgement_loss":
            _deliver_once(run_id, order_id, lose_acknowledgement=True)
            _deliver_once(run_id, order_id)
        elif scenario == "concurrent_consume":
            # SQLite is a local fallback and serializes writers at database level; MySQL executes both consumers concurrently.
            if get_engine().dialect.name == "sqlite":
                _deliver_once(run_id, order_id)
                _deliver_once(run_id, order_id)
            else:
                with ThreadPoolExecutor(max_workers=2) as executor:
                    list(executor.map(lambda _: _deliver_once(run_id, order_id), range(2)))
        else:
            raise ValueError("不支持的可靠性实验场景")
        assertion = _assert_invariants(run_id, player_id, scenario)
        status = "passed" if assertion["passed"] else "failed"
        _event(run_id, "assertion", "最终不变量校验通过" if assertion["passed"] else "最终不变量校验失败", **assertion)
        error_message = None
    except Exception as error:
        assertion = {"passed": False, "expected": {}, "actual": {}}
        status = "failed"
        error_message = f"{type(error).__name__}: {error}"
        _event(run_id, "error", "实验执行出现异常", error_message=error_message)
    with connect() as connection:
        connection.execute(
            text("""UPDATE reliability_runs SET status = :status, completed_at = :completed_at, passed = :passed,
                summary_json = :summary_json, error_message = :error_message WHERE run_id = :run_id"""),
            {"status": status, "completed_at": _now(), "passed": int(assertion["passed"]), "summary_json": json.dumps(assertion, ensure_ascii=False), "error_message": error_message, "run_id": run_id},
        )
    return get_reliability_run(run_id) or {}


def get_reliability_run(run_id: int) -> dict[str, object] | None:
    initialize_database()
    with connect() as connection:
        run = connection.execute(text("SELECT * FROM reliability_runs WHERE run_id = :run_id"), {"run_id": run_id}).mappings().first()
        if not run:
            return None
        events = connection.execute(text("SELECT kind, message, payload_json, created_at FROM reliability_events WHERE run_id = :run_id ORDER BY event_id"), {"run_id": run_id}).mappings().all()
    return {
        "run_id": run["run_id"], "scenario": run["scenario"], "scenario_title": SCENARIOS[run["scenario"]]["title"], "trigger": run["trigger"], "status": run["status"], "started_at": run["started_at"], "completed_at": run["completed_at"], "passed": bool(run["passed"]) if run["passed"] is not None else None, "summary": json.loads(run["summary_json"]) if run["summary_json"] else None, "error_message": run["error_message"],
        "events": [{"kind": event["kind"], "message": event["message"], "payload": json.loads(event["payload_json"]), "created_at": event["created_at"]} for event in events],
    }


def list_reliability_runs(limit: int = 12) -> list[dict[str, object]]:
    initialize_database()
    with connect() as connection:
        rows = connection.execute(text("SELECT * FROM reliability_runs ORDER BY run_id DESC LIMIT :limit"), {"limit": limit}).mappings().all()
    return [{"run_id": row["run_id"], "scenario": row["scenario"], "scenario_title": SCENARIOS[row["scenario"]]["title"], "status": row["status"], "passed": bool(row["passed"]) if row["passed"] is not None else None, "completed_at": row["completed_at"], "summary": json.loads(row["summary_json"]) if row["summary_json"] else None} for row in rows]


def reliability_trend(limit: int = 12) -> dict[str, object]:
    runs = list_reliability_runs(limit)
    finished = [run for run in runs if run["status"] in {"passed", "failed"}]
    passed = sum(run["status"] == "passed" for run in finished)
    return {"total_runs": len(finished), "passed_runs": passed, "failed_runs": len(finished) - passed, "pass_rate": round(passed / len(finished) * 100, 1) if finished else 0, "points": list(reversed(finished))}
