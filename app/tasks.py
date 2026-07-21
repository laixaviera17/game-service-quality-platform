from __future__ import annotations

from .reliability import execute_reliability_run, finalize_concurrent_reliability_run, poll_outbox_event
from .task_queue import celery_app


@celery_app.task(name="app.tasks.execute_reliability_run")
def execute_reliability_experiment(run_id: int) -> dict[str, object]:
    return execute_reliability_run(run_id)


@celery_app.task(name="app.tasks.poll_outbox_event")
def poll_outbox_event_task(run_id: int) -> str:
    return poll_outbox_event(run_id, task_id=poll_outbox_event_task.request.id)


@celery_app.task(name="app.tasks.finalize_concurrent_reliability_run")
def finalize_concurrent_reliability_run_task(_poller_results: list[str], run_id: int, player_id: str) -> dict[str, object]:
    return finalize_concurrent_reliability_run(run_id, player_id)
