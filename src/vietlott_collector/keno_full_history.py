from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from . import keno_gap_repair, keno_history


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vietlott-keno-full-history",
        description="Run the complete two-stage Keno history recovery workflow.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data"))
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--request-delay", type=float, default=0.30)
    parser.add_argument("--jitter", type=float, default=0.08)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--contact-email", default="configure-your-email")
    parser.add_argument(
        "--full-range",
        action="store_true",
        help="Recheck every date from Keno launch through the latest stored date.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    status_path = args.output_dir / "keno-full-history-status.json"
    _write_json(
        status_path,
        {"phase": "history_by_date", "updated_at": _now()},
    )
    common = [
        "--output-dir",
        str(args.output_dir),
        "--workers",
        str(args.workers),
        "--request-delay",
        str(args.request_delay),
        "--jitter",
        str(args.jitter),
        "--timeout",
        str(args.timeout),
        "--retries",
        str(args.retries),
        "--contact-email",
        args.contact_email,
    ]
    history_args = [*common]
    if args.full_range:
        history_args.append("--full-range")

    try:
        keno_history.main(history_args)
    except SystemExit as exc:
        if exc.code != 2 or not _can_continue_to_gap_repair(args.output_dir):
            raise

    _write_json(
        status_path,
        {"phase": "gap_repair", "updated_at": _now()},
    )
    keno_gap_repair.main(common)
    write_completed_summary(args.output_dir)


def _can_continue_to_gap_repair(output_dir: Path) -> bool:
    report_path = output_dir / "keno-history-report.json"
    if not report_path.exists():
        return False
    report = json.loads(report_path.read_text(encoding="utf-8"))
    errors = report.get("errors", [])
    return bool(errors) and all(
        error.get("phase") == "official_confirmation"
        and "refusing excessive detail requests" in str(error.get("error", ""))
        for error in errors
    )


def write_completed_summary(output_dir: Path) -> None:
    history_report = _read_json(output_dir / "keno-history-report.json")
    repair_report = _read_json(output_dir / "keno-gap-repair-report.json")
    complete = bool(repair_report.get("complete"))
    summary = {
        "completed_at": _now(),
        "complete": complete,
        "history_report": "keno-history-report.json",
        "gap_repair_report": "keno-gap-repair-report.json",
        "dates_scanned": history_report.get("dates_total"),
        "history_rows_inserted": history_report.get("inserted_rows"),
        "gap_rows_inserted": repair_report.get("onbit_rows_inserted"),
        "confirmed_nonexistent_ids": repair_report.get(
            "confirmed_nonexistent_ids",
            [],
        ),
        "unresolved_missing_ids": repair_report.get("unresolved_missing_ids", []),
        "errors": repair_report.get("errors", []),
        "database_counts": repair_report.get("database_counts"),
    }
    _write_json(output_dir / "keno-full-history-report.json", summary)
    _write_json(
        output_dir / "keno-full-history-status.json",
        {
            "phase": "complete" if complete else "incomplete",
            "updated_at": _now(),
            "complete": complete,
            "report": "keno-full-history-report.json",
        },
    )


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict[str, object]) -> None:
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


if __name__ == "__main__":
    main()
