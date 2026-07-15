from app.quality import run_quality_check
from scripts.seed_demo import seed_demo_data
from scripts.seed_issue_demo import seed_issue_demo_data


def test_valid_demo_data_passes_all_quality_rules():
    seed_demo_data()
    report = run_quality_check()

    assert report["summary"] == {"rules": 4, "failed_rules": 0, "total_findings": 0}


def test_issue_demo_data_exercises_every_quality_rule():
    seed_issue_demo_data()
    report = run_quality_check()

    assert report["summary"] == {"rules": 4, "failed_rules": 4, "total_findings": 4}
    assert all(not item["passed"] for item in report["findings"])
