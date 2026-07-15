from app.test_runner import (
    create_test_run,
    execute_test_run,
    get_test_run,
    list_test_runs,
    rerun_test_run,
    get_test_run_trend,
)
from app.task_queue import celery_app


def test_celery_worker_registers_service_test_task():
    celery_app.loader.import_default_modules()
    assert "app.tasks.execute_service_test_run" in celery_app.tasks


def test_service_test_run_persists_five_isolated_scenarios():
    run_id = create_test_run(trigger="test")
    report = execute_test_run(run_id)

    assert report["status"] == "passed"
    assert report["summary"] == {"total_cases": 5, "passed_cases": 5, "failed_cases": 0}
    assert [item["case_code"] for item in report["cases"]] == [
        "normal_grant", "idempotent_retry", "per_player_limit", "suspended_account", "stock_race",
    ]
    assert all(item["status"] == "passed" for item in report["cases"])
    assert all(item["assertions"] for item in report["cases"])
    assert get_test_run(run_id) == report


def test_service_test_run_history_returns_newest_first():
    first = create_test_run(trigger="test")
    second = create_test_run(trigger="test")
    items = list_test_runs(limit=1)

    assert first < second
    assert items[0]["run_id"] == second
    assert items[0]["status"] == "queued"


def test_selected_scenarios_and_parameters_are_persisted_and_reused():
    run_id = create_test_run(
        trigger="test",
        case_codes=["normal_grant", "stock_race"],
        options={"stock": 2, "per_player_limit": 2, "player_status": "active"},
    )
    report = execute_test_run(run_id)

    assert report["summary"] == {"total_cases": 2, "passed_cases": 2, "failed_cases": 0}
    assert report["config"] == {
        "case_codes": ["normal_grant", "stock_race"],
        "options": {"stock": 2, "per_player_limit": 2, "player_status": "active"},
    }
    rerun_id = rerun_test_run(run_id)
    assert get_test_run(rerun_id)["config"] == report["config"]


def test_trend_aggregates_completed_runs():
    run_id = create_test_run(trigger="test", case_codes=["normal_grant"])
    execute_test_run(run_id)
    trend = get_test_run_trend(limit=5)

    assert trend["total_runs"] == 1
    assert trend["passed_runs"] == 1
    assert trend["pass_rate"] == 100.0
