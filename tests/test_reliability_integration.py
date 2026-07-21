import os

import pytest

from app.reliability import create_reliability_run, wait_for_reliability_run
from app.task_queue import dispatch_reliability_run, uses_async_worker


pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def integration_ready():
    if os.getenv("RUN_INTEGRATION") != "1":
        pytest.skip("set RUN_INTEGRATION=1 to run MySQL/Redis/Celery integration tests")
    if not uses_async_worker():
        pytest.skip("integration tests require EXECUTION_MODE=celery")
    if not os.getenv("DATABASE_URL", "").startswith("mysql"):
        pytest.skip("integration tests require DATABASE_URL pointing to MySQL")


def test_concurrent_outbox_poll_via_celery_chord(integration_ready):
    run_id = create_reliability_run("concurrent_consume", trigger="integration")
    assert dispatch_reliability_run(run_id) == "queued"

    report = wait_for_reliability_run(run_id, timeout_seconds=45.0)

    assert report["status"] == "passed"
    assert report["summary"]["actual"]["ledger_entries"] == 1
    assert report["summary"]["actual"]["balance"] == 100
    assert any(event["kind"] == "schedule" for event in report["events"])

    poll_events = [event for event in report["events"] if event["kind"] == "poll"]
    assert len(poll_events) >= 2
    task_ids = {event["payload"].get("task_id") for event in poll_events if event["payload"].get("task_id")}
    assert len(task_ids) >= 2

    # Without artificial SLEEP, the second poller may either hit ledger dedupe or find no
    # pending event after the first consumer finished. Either path must leave balance=100.
    outcomes = {event["kind"] for event in report["events"]}
    assert "effect" in outcomes
    assert "dedupe" in outcomes or any(
        event["kind"] == "poll" and event["payload"].get("order_id") is None for event in poll_events
    ) or any(event["message"].startswith("Outbox 轮询未发现") for event in poll_events)
