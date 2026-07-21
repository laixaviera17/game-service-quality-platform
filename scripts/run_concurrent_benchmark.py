from __future__ import annotations

import argparse
import json
import os
import sys
import time

from app.database import initialize_database
from app.reliability import create_reliability_run, get_reliability_run, wait_for_reliability_run
from app.task_queue import dispatch_reliability_run, uses_async_worker


def _run_once() -> dict[str, object]:
    run_id = create_reliability_run("concurrent_consume", trigger="benchmark")
    dispatch_reliability_run(run_id)
    return wait_for_reliability_run(run_id, timeout_seconds=45.0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark concurrent Outbox polling without artificial sleeps.")
    parser.add_argument("--runs", type=int, default=20, help="Number of concurrent_consume experiments to execute.")
    args = parser.parse_args()

    if not uses_async_worker():
        print("Set EXECUTION_MODE=celery before running the benchmark.", file=sys.stderr)
        return 2
    if not os.getenv("DATABASE_URL", "").startswith("mysql"):
        print("Benchmark requires DATABASE_URL pointing to MySQL.", file=sys.stderr)
        return 2

    initialize_database()
    passed = detected_dedupe = failed = 0
    samples: list[dict[str, object]] = []

    for index in range(args.runs):
        report = _run_once()
        status = str(report["status"])
        events = report.get("events") or []
        has_dedupe = any(event["kind"] == "dedupe" for event in events)
        poll_task_ids = {
            event["payload"].get("task_id")
            for event in events
            if event["kind"] == "poll" and event.get("payload", {}).get("task_id")
        }
        if status == "passed":
            passed += 1
        else:
            failed += 1
        if has_dedupe:
            detected_dedupe += 1
        samples.append(
            {
                "run_id": report["run_id"],
                "status": status,
                "dedupe_detected": has_dedupe,
                "poll_task_ids": sorted(poll_task_ids),
                "balance": (report.get("summary") or {}).get("actual", {}).get("balance"),
            }
        )
        time.sleep(0.2)

    summary = {
        "runs": args.runs,
        "passed": passed,
        "failed": failed,
        "dedupe_detected_runs": detected_dedupe,
        "dedupe_detection_rate": round(detected_dedupe / args.runs * 100, 1) if args.runs else 0,
        "samples": samples,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
