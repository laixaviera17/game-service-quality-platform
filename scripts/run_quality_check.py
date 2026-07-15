import json
from pathlib import Path

from app.quality import run_quality_check


def main() -> None:
    report = run_quality_check(persist=True, trigger="script")
    output = Path(__file__).resolve().parents[1] / "reports" / "latest.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
