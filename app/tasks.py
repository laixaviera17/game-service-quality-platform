from __future__ import annotations

from .task_queue import celery_app
from .test_runner import execute_test_run


@celery_app.task(name="app.tasks.execute_service_test_run")
def execute_service_test_run(run_id: int) -> dict[str, object]:
    return execute_test_run(run_id)
