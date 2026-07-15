from __future__ import annotations

import os

from celery import Celery


def _redis_url() -> str:
    return os.getenv("CELERY_BROKER_URL", "redis://127.0.0.1:6379/0")


celery_app = Celery(
    "game_quality_platform",
    broker=_redis_url(),
    backend=os.getenv("CELERY_RESULT_BACKEND", _redis_url()),
    include=["app.tasks"],
)
celery_app.conf.update(task_serializer="json", result_serializer="json", accept_content=["json"], timezone="UTC")


def uses_async_worker() -> bool:
    return os.getenv("EXECUTION_MODE", "sync").lower() == "celery"


def dispatch_test_run(run_id: int) -> str:
    """Local execution stays simple; Docker sends the run through Redis/Celery."""
    if uses_async_worker():
        celery_app.send_task("app.tasks.execute_service_test_run", args=[run_id])
        return "queued"
    from .test_runner import execute_test_run
    execute_test_run(run_id)
    return "completed"
