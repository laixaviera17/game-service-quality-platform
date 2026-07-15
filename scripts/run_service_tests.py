"""Run the isolated service scenarios without starting the FastAPI server."""

import json

from app.test_runner import create_test_run, execute_test_run


def main() -> None:
    run_id = create_test_run(trigger="script")
    report = execute_test_run(run_id)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
