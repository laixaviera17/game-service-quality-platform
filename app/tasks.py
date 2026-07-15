from __future__ import annotations

from .reliability import consume_delivery_attempt, execute_reliability_run, finalize_concurrent_reliability_run
from .task_queue import celery_app


@celery_app.task(name="app.tasks.execute_reliability_run")
def execute_reliability_experiment(run_id: int) -> dict[str, object]:
    return execute_reliability_run(run_id)


@celery_app.task(name="app.tasks.consume_delivery_attempt")
def consume_delivery_attempt_task(run_id: int, order_id: str, synchronize: bool = False) -> str:
    return consume_delivery_attempt(run_id, order_id, synchronize=synchronize, task_id=consume_delivery_attempt_task.request.id)


@celery_app.task(name="app.tasks.finalize_concurrent_reliability_run")
def finalize_concurrent_reliability_run_task(_consumer_results: list[str], run_id: int, player_id: str) -> dict[str, object]:
    return finalize_concurrent_reliability_run(run_id, player_id)
