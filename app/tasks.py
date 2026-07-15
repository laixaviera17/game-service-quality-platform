from __future__ import annotations

from .task_queue import celery_app
from .reliability import execute_reliability_run
from .test_runner import execute_test_run


@celery_app.task(name="app.tasks.execute_service_test_run")
def execute_service_test_run(run_id: int) -> dict[str, object]:
    return execute_test_run(run_id)


@celery_app.task(name="app.tasks.execute_reliability_run")
def execute_reliability_experiment(run_id: int) -> dict[str, object]:
    return execute_reliability_run(run_id)
