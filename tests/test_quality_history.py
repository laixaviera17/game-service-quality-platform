from app.quality import get_quality_run, list_quality_runs, run_quality_check
from scripts.seed_demo import seed_demo_data
from scripts.seed_issue_demo import seed_issue_demo_data


def test_quality_run_snapshot_is_unchanged_after_local_data_resets():
    seed_issue_demo_data()
    failed_run = run_quality_check(persist=True, trigger="test")
    seed_demo_data()
    passed_run = run_quality_check(persist=True, trigger="test")

    failed_snapshot = get_quality_run(failed_run["run_id"])
    passed_snapshot = get_quality_run(passed_run["run_id"])

    assert failed_snapshot["status"] == "failed"
    assert failed_snapshot["summary"]["failed_rules"] == 4
    assert passed_snapshot["status"] == "passed"
    assert passed_snapshot["summary"]["failed_rules"] == 0


def test_quality_run_history_returns_newest_run_first_and_respects_limit():
    seed_demo_data()
    first = run_quality_check(persist=True, trigger="test")
    second = run_quality_check(persist=True, trigger="test")

    history = list_quality_runs(limit=1)

    assert history == [
        {
            "run_id": second["run_id"],
            "trigger": "test",
            "generated_at": second["generated_at"],
            "status": "passed",
            "summary": {"rules": 4, "failed_rules": 0, "total_findings": 0},
        }
    ]
    assert first["run_id"] < second["run_id"]
