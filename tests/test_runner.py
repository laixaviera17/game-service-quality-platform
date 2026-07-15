from app.test_runner import create_test_run, execute_test_run, get_test_run, list_test_runs


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
