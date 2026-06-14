from __future__ import annotations

import argparse
import json
import logging
import threading
import time
from collections.abc import Iterable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from .config import PRODUCT_SPECS
from .http import HttpClient, HttpSettings, RateLimiter
from .models import DrawRecord
from .parsers import parse_fast_draw_detail, parse_xoso_keno_archive_page
from .state import StateStore
from .storage import SqliteDatasetStore
from .validation import validate_draw

LOGGER = logging.getLogger(__name__)
ARCHIVE_BASE_URL = "https://xoso.com.vn"
ARCHIVE_ENDPOINT = f"{ARCHIVE_BASE_URL}/KeNo/GetMoreBydate"
DEFAULT_RANGES = (
    (date(2019, 8, 23), date(2022, 12, 4)),
    (date(2023, 3, 28), date(2025, 3, 3)),
)


@dataclass(slots=True)
class DateResult:
    draw_date: date
    records: list[DrawRecord]
    requests: int


class ArchiveClients:
    def __init__(self, settings: HttpSettings) -> None:
        self.settings = settings
        self.rate_limiter = RateLimiter(
            settings.request_delay_seconds,
            settings.jitter_seconds,
        )
        self.local = threading.local()
        self.clients: list[HttpClient] = []
        self.lock = threading.Lock()

    def get(self) -> HttpClient:
        client = getattr(self.local, "client", None)
        if client is None:
            client = HttpClient(self.settings, rate_limiter=self.rate_limiter)
            self.local.client = client
            with self.lock:
                self.clients.append(client)
        return client

    def close(self) -> None:
        for client in self.clients:
            client.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vietlott-keno-history",
        description="Fill the historical Keno ranges absent from Vietlott pagination.",
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
    if not 1 <= args.workers <= 6:
        raise SystemExit("--workers must be between 1 and 6")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _configure_logging(args.output_dir / "keno-history.log")

    store = SqliteDatasetStore(args.output_dir)
    checkpoint_path = args.output_dir / ".keno-history-checkpoint.json"
    progress_path = args.output_dir / "keno-history-status.json"
    report_path = args.output_dir / "keno-history-report.json"
    checkpoint = _load_checkpoint(checkpoint_path)
    completed_dates = set(checkpoint.get("completed_dates", []))
    latest_date = _latest_keno_date(store)
    ranges = (
        ((date(2019, 8, 23), latest_date),)
        if args.full_range
        else DEFAULT_RANGES
    )
    all_dates = list(_dates_for_ranges(ranges))
    pending_dates = [
        draw_date
        for draw_date in all_dates
        if draw_date.isoformat() not in completed_dates
    ]

    settings = HttpSettings(
        timeout_seconds=args.timeout,
        request_delay_seconds=args.request_delay,
        jitter_seconds=args.jitter,
        retry_total=args.retries,
        user_agent=(
            "vietlott-history-collector/0.1 "
            f"(Keno historical research; contact: {args.contact_email})"
        ),
    )
    clients = ArchiveClients(settings)
    existing = _existing_keno_rows(store)
    stats: dict[str, object] = {
        "started_at": _now(),
        "source": ARCHIVE_BASE_URL,
        "ranges": [
            {"start": start.isoformat(), "end": end.isoformat()}
            for start, end in ranges
        ],
        "dates_total": len(all_dates),
        "dates_previously_completed": len(all_dates) - len(pending_dates),
        "dates_completed_this_run": 0,
        "requests": 0,
        "archive_rows_seen": 0,
        "existing_rows_verified": 0,
        "inserted_rows": 0,
        "source_mismatches": 0,
        "mismatch_examples": [],
        "errors": [],
    }
    started = time.monotonic()

    try:
        _run_dates(
            pending_dates,
            workers=args.workers,
            clients=clients,
            store=store,
            existing=existing,
            completed_dates=completed_dates,
            checkpoint_path=checkpoint_path,
            progress_path=progress_path,
            stats=stats,
            started=started,
            total_dates=len(all_dates),
        )
        remaining = store.missing_numeric_draw_ids("keno", 1, _latest_keno_id(store))
        confirmed_nonexistent, confirmation_errors = _confirm_remaining_official(
            remaining,
            settings,
        )
        unresolved = sorted(set(remaining) - set(confirmed_nonexistent))
        errors = stats["errors"]
        assert isinstance(errors, list)
        errors.extend(confirmation_errors)
        stats["confirmed_nonexistent_ids"] = [
            str(draw_id).zfill(7) for draw_id in confirmed_nonexistent
        ]
        stats["unresolved_missing_ids"] = [
            str(draw_id).zfill(7) for draw_id in unresolved
        ]
        stats["database_counts"] = store.counts()
        stats["finished_at"] = _now()
        stats["complete"] = not errors and not unresolved

        _update_state(
            args.output_dir,
            complete=bool(stats["complete"]),
            unresolved=unresolved,
            confirmed_nonexistent=confirmed_nonexistent,
        )
        if stats["complete"]:
            store.export_csv()
        report_path.write_text(
            json.dumps(stats, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        _write_progress(
            progress_path,
            phase="complete" if stats["complete"] else "incomplete",
            details={
                "updated_at": _now(),
                "complete": stats["complete"],
                "draw_rows": stats["database_counts"][0],
                "prize_rows": stats["database_counts"][1],
                "inserted_rows": stats["inserted_rows"],
                "source_mismatches": stats["source_mismatches"],
                "unresolved_missing_ids": len(unresolved),
                "errors": len(errors),
                "report": report_path.name,
            },
        )
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        if not stats["complete"]:
            raise SystemExit(2)
    finally:
        clients.close()
        store.close()


def _run_dates(
    pending_dates: list[date],
    *,
    workers: int,
    clients: ArchiveClients,
    store: SqliteDatasetStore,
    existing: dict[str, tuple[str, str]],
    completed_dates: set[str],
    checkpoint_path: Path,
    progress_path: Path,
    stats: dict[str, object],
    started: float,
    total_dates: int,
) -> None:
    date_iterator = iter(pending_dates)
    futures: dict[Future[DateResult], date] = {}
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="keno-history") as executor:
        for _ in range(min(len(pending_dates), workers * 2)):
            _submit_next(executor, futures, date_iterator, clients)
        while futures:
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                draw_date = futures.pop(future)
                try:
                    result = future.result()
                    _process_date_result(store, existing, result, stats)
                    completed_dates.add(draw_date.isoformat())
                    stats["dates_completed_this_run"] = (
                        int(stats["dates_completed_this_run"]) + 1
                    )
                    _save_checkpoint(checkpoint_path, completed_dates)
                except Exception as exc:
                    LOGGER.exception("Keno archive date %s failed", draw_date)
                    errors = stats["errors"]
                    assert isinstance(errors, list)
                    errors.append({"date": draw_date.isoformat(), "error": str(exc)})
                _write_running_progress(
                    progress_path,
                    stats,
                    started,
                    total_dates,
                    len(completed_dates),
                    draw_date,
                )
                _submit_next(executor, futures, date_iterator, clients)


def _submit_next(
    executor: ThreadPoolExecutor,
    futures: dict[Future[DateResult], date],
    dates: Iterable[date],
    clients: ArchiveClients,
) -> None:
    try:
        draw_date = next(dates)  # type: ignore[arg-type]
    except StopIteration:
        return
    futures[executor.submit(_fetch_date, draw_date, clients)] = draw_date


def _fetch_date(draw_date: date, clients: ArchiveClients) -> DateResult:
    client = clients.get()
    source_url = _archive_date_url(draw_date)
    date_parameter = f"{draw_date.day}-{draw_date.month}-{draw_date.year}"
    records: list[DrawRecord] = []
    requests = 0
    page = 0
    while True:
        html = client.get_text(
            ARCHIVE_ENDPOINT,
            params={"pageIndex": page, "date": date_parameter},
        )
        requests += 1
        page_records = parse_xoso_keno_archive_page(
            html,
            source_url=source_url,
            archive_endpoint=ARCHIVE_ENDPOINT,
        )
        if not page_records:
            break
        for record in page_records:
            warnings = validate_draw(record, PRODUCT_SPECS["keno"])
            if warnings:
                raise ValueError(
                    f"invalid Keno row {record.draw_id}: {', '.join(warnings)}"
                )
            if record.draw_date != draw_date:
                raise ValueError(
                    f"archive date mismatch: requested {draw_date}, got {record.draw_date}"
                )
        records.extend(page_records)
        page += 1
        if page > 20:
            raise ValueError(f"archive returned more than 20 pages for {draw_date}")
    return DateResult(draw_date=draw_date, records=records, requests=requests)


def _process_date_result(
    store: SqliteDatasetStore,
    existing: dict[str, tuple[str, str]],
    result: DateResult,
    stats: dict[str, object],
) -> None:
    stats["requests"] = int(stats["requests"]) + result.requests
    stats["archive_rows_seen"] = int(stats["archive_rows_seen"]) + len(result.records)
    to_insert: list[DrawRecord] = []
    for record in result.records:
        row = record.to_row()
        known = existing.get(record.draw_id)
        if known is None:
            to_insert.append(record)
            existing[record.draw_id] = (
                row["draw_date"],
                row["result_json"],
            )
            continue
        stats["existing_rows_verified"] = int(stats["existing_rows_verified"]) + 1
        if known != (row["draw_date"], row["result_json"]):
            stats["source_mismatches"] = int(stats["source_mismatches"]) + 1
            examples = stats["mismatch_examples"]
            assert isinstance(examples, list)
            if len(examples) < 50:
                examples.append(
                    {
                        "draw_id": record.draw_id,
                        "stored_date": known[0],
                        "archive_date": row["draw_date"],
                        "stored_result_json": known[1],
                        "archive_result_json": row["result_json"],
                    }
                )
    inserted = store.insert_missing_draws(to_insert)
    if inserted != len(to_insert):
        LOGGER.info(
            "%s: planned %d inserts, SQLite inserted %d",
            result.draw_date,
            len(to_insert),
            inserted,
        )
    stats["inserted_rows"] = int(stats["inserted_rows"]) + inserted


def _existing_keno_rows(store: SqliteDatasetStore) -> dict[str, tuple[str, str]]:
    return {
        str(draw_id): (str(draw_date), str(result_json))
        for draw_id, draw_date, result_json in store.connection.execute(
            "SELECT draw_id, draw_date, result_json FROM draws WHERE product = 'keno'"
        )
    }


def _latest_keno_date(store: SqliteDatasetStore) -> date:
    value = store.connection.execute(
        "SELECT MAX(draw_date) FROM draws WHERE product = 'keno'"
    ).fetchone()[0]
    if not value:
        raise RuntimeError("Keno data is empty; run the primary collector first")
    return date.fromisoformat(str(value))


def _latest_keno_id(store: SqliteDatasetStore) -> int:
    return int(
        store.connection.execute(
            "SELECT MAX(CAST(draw_id AS INTEGER)) FROM draws WHERE product = 'keno'"
        ).fetchone()[0]
    )


def _confirm_remaining_official(
    missing_ids: list[int],
    settings: HttpSettings,
) -> tuple[list[int], list[dict[str, object]]]:
    if len(missing_ids) > 500:
        return [], [
            {
                "phase": "official_confirmation",
                "error": f"{len(missing_ids)} IDs remain; refusing excessive detail requests",
            }
        ]
    confirmed: list[int] = []
    errors: list[dict[str, object]] = []
    spec = PRODUCT_SPECS["keno"]
    with HttpClient(settings) as client:
        for numeric_id in missing_ids:
            draw_id = str(numeric_id).zfill(7)
            url = spec.detail_url(draw_id)
            try:
                record = parse_fast_draw_detail(spec, url, client.get_text(url))
                if record is None:
                    confirmed.append(numeric_id)
                else:
                    errors.append(
                        {
                            "draw_id": draw_id,
                            "phase": "official_confirmation",
                            "error": "official detail exists but archive did not return it",
                        }
                    )
            except Exception as exc:
                errors.append(
                    {
                        "draw_id": draw_id,
                        "phase": "official_confirmation",
                        "error": str(exc),
                    }
                )
    return confirmed, errors


def _update_state(
    output_dir: Path,
    *,
    complete: bool,
    unresolved: list[int],
    confirmed_nonexistent: list[int],
) -> None:
    state_store = StateStore(output_dir / ".collector-state.json")
    state = state_store.load()
    product = state_store.product(state, "keno")
    product.oldest_draw_id = "0000001"
    product.known_history_incomplete = not complete
    product.backfill_complete = complete
    if complete:
        product.history_gap_note = None
        product.last_error = None
    else:
        note = (
            f"Keno historical archive still has {len(unresolved)} unresolved IDs; "
            f"{len(confirmed_nonexistent)} IDs were confirmed nonexistent."
        )
        product.history_gap_note = note
        product.last_error = note
    state_store.save(state)


def _write_running_progress(
    path: Path,
    stats: dict[str, object],
    started: float,
    total_dates: int,
    completed_dates: int,
    current_date: date,
) -> None:
    elapsed = max(0.001, time.monotonic() - started)
    completed_this_run = int(stats["dates_completed_this_run"])
    rate = completed_this_run / elapsed
    remaining_dates = max(0, total_dates - completed_dates)
    remaining_seconds = remaining_dates / rate if rate else 0
    finish = datetime.now(UTC) + timedelta(seconds=remaining_seconds)
    _write_progress(
        path,
        phase="collecting",
        details={
            "updated_at": _now(),
            "current_date": current_date.isoformat(),
            "dates_completed": completed_dates,
            "dates_total": total_dates,
            "percent": round(completed_dates / max(1, total_dates) * 100, 2),
            "requests": stats["requests"],
            "archive_rows_seen": stats["archive_rows_seen"],
            "existing_rows_verified": stats["existing_rows_verified"],
            "inserted_rows": stats["inserted_rows"],
            "source_mismatches": stats["source_mismatches"],
            "errors": len(stats["errors"]),  # type: ignore[arg-type]
            "estimated_seconds_remaining": round(remaining_seconds),
            "estimated_finish_at": finish.isoformat(timespec="seconds"),
        },
    )


def _write_progress(path: Path, *, phase: str, details: dict[str, object]) -> None:
    payload = {"phase": phase, "details": details}
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def _load_checkpoint(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"version": 1, "completed_dates": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_checkpoint(path: Path, completed_dates: set[str]) -> None:
    payload = {
        "version": 1,
        "updated_at": _now(),
        "source": ARCHIVE_BASE_URL,
        "completed_dates": sorted(completed_dates),
    }
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def _dates_for_ranges(ranges: Iterable[tuple[date, date]]) -> Iterable[date]:
    seen: set[date] = set()
    for start, end in ranges:
        current = start
        while current <= end:
            if current not in seen:
                seen.add(current)
                yield current
            current += timedelta(days=1)


def _archive_date_url(draw_date: date) -> str:
    return (
        f"{ARCHIVE_BASE_URL}/ket-qua-keno-"
        f"{draw_date.day}-{draw_date.month}-{draw_date.year}.html"
    )


def _configure_logging(path: Path) -> None:
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(console)
    root.addHandler(file_handler)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


if __name__ == "__main__":
    main()
