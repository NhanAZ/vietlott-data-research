from __future__ import annotations

import argparse
import json
import logging
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .config import PRODUCT_SPECS
from .http import HttpSettings
from .keno_history import ArchiveClients
from .models import DrawRecord
from .parsers import parse_ketquaday_keno_detail, parse_onbit_keno_page
from .state import StateStore
from .storage import SqliteDatasetStore
from .validation import validate_draw

LOGGER = logging.getLogger(__name__)
KETQUADAY_BASE = "https://ketquaday.vn"
ONBIT_LIST = "https://onbit.vn/ket-qua-xo-so/vietlott-keno"
ONBIT_LAST_PAGE = 54_015


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vietlott-keno-gap-repair",
        description="Recover Keno archive omissions and verify genuine ID jumps.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data"))
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--request-delay", type=float, default=0.30)
    parser.add_argument("--jitter", type=float, default=0.08)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--contact-email", default="configure-your-email")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _configure_logging(args.output_dir / "keno-gap-repair.log")
    store = SqliteDatasetStore(args.output_dir)
    progress_path = args.output_dir / "keno-gap-repair-status.json"
    report_path = args.output_dir / "keno-gap-repair-report.json"
    checkpoint_path = args.output_dir / ".keno-gap-repair-checkpoint.json"
    settings = HttpSettings(
        timeout_seconds=args.timeout,
        request_delay_seconds=args.request_delay,
        jitter_seconds=args.jitter,
        retry_total=args.retries,
        user_agent=(
            "vietlott-history-collector/0.1 "
            f"(Keno gap research; contact: {args.contact_email})"
        ),
    )
    clients = ArchiveClients(settings)
    checkpoint = _load_checkpoint(checkpoint_path)
    started = time.monotonic()
    stats: dict[str, object] = {
        "started_at": _now(),
        "initial_missing_ids": [],
        "ketquaday_checked": 0,
        "ketquaday_candidates": 0,
        "ketquaday_inserted": 0,
        "ketquaday_unavailable": 0,
        "secondary_conflicts": [],
        "mismatch_repairs": [],
        "onbit_pages_requested": 0,
        "onbit_rows_inserted": 0,
        "confirmed_nonexistent_ids": [],
        "errors": [],
    }
    try:
        latest = _latest_id(store)
        initial_missing = store.missing_numeric_draw_ids("keno", 1, latest)
        stats["initial_missing_ids"] = [str(value).zfill(7) for value in initial_missing]
        _repair_known_mismatches(store, clients, stats)
        candidates = _recover_ketquaday(
            store,
            clients,
            initial_missing,
            workers=args.workers,
            checkpoint=checkpoint,
            checkpoint_path=checkpoint_path,
            progress_path=progress_path,
            stats=stats,
            started=started,
        )
        remaining = store.missing_numeric_draw_ids("keno", 1, latest)
        confirmed = _recover_or_confirm_onbit(
            store,
            clients,
            remaining,
            progress_path=progress_path,
            stats=stats,
            started=started,
            ketquaday_candidates=candidates,
        )
        final_missing = store.missing_numeric_draw_ids("keno", 1, latest)
        unresolved = sorted(set(final_missing) - confirmed)
        stats["confirmed_nonexistent_ids"] = [
            str(value).zfill(7) for value in sorted(confirmed)
        ]
        stats["unresolved_missing_ids"] = [
            str(value).zfill(7) for value in unresolved
        ]
        stats["database_counts"] = store.counts()
        stats["finished_at"] = _now()
        stats["complete"] = not unresolved and not stats["errors"]
        _update_state(
            args.output_dir,
            complete=bool(stats["complete"]),
            unresolved=unresolved,
            confirmed=confirmed,
        )
        if stats["complete"]:
            store.export_csv()
        report_path.write_text(
            json.dumps(stats, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        _write_progress(
            progress_path,
            {
                "phase": "complete" if stats["complete"] else "incomplete",
                "details": {
                    "updated_at": _now(),
                    "complete": stats["complete"],
                    "ketquaday_inserted": stats["ketquaday_inserted"],
                    "onbit_rows_inserted": stats["onbit_rows_inserted"],
                    "confirmed_nonexistent": len(confirmed),
                    "unresolved": len(unresolved),
                    "errors": len(stats["errors"]),  # type: ignore[arg-type]
                    "report": report_path.name,
                },
            },
        )
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        if not stats["complete"]:
            raise SystemExit(2)
    finally:
        clients.close()
        store.close()


def _recover_ketquaday(
    store: SqliteDatasetStore,
    clients: ArchiveClients,
    missing_ids: list[int],
    *,
    workers: int,
    checkpoint: dict[str, object],
    checkpoint_path: Path,
    progress_path: Path,
    stats: dict[str, object],
    started: float,
) -> dict[int, DrawRecord]:
    checked = {int(value) for value in checkpoint.get("ketquaday_checked_ids", [])}
    candidates = {
        int(draw_id): _candidate_record(int(draw_id), value)
        for draw_id, value in checkpoint.get("ketquaday_candidates", {}).items()  # type: ignore[union-attr]
    }
    pending = [value for value in missing_ids if value not in checked]
    iterator = iter(pending)
    futures: dict[Future[tuple[int, DrawRecord | None]], int] = {}
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="keno-gap") as executor:
        for _ in range(min(len(pending), workers * 2)):
            _submit_detail(executor, futures, iterator, clients)
        while futures:
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                numeric_id = futures.pop(future)
                try:
                    _, record = future.result()
                    stats["ketquaday_checked"] = int(stats["ketquaday_checked"]) + 1
                    if record is None:
                        stats["ketquaday_unavailable"] = (
                            int(stats["ketquaday_unavailable"]) + 1
                        )
                    else:
                        validate_draw(record, PRODUCT_SPECS["keno"])
                        candidates[numeric_id] = record
                        stats["ketquaday_candidates"] = len(candidates)
                    checked.add(numeric_id)
                    checkpoint["ketquaday_checked_ids"] = sorted(checked)
                    checkpoint["ketquaday_candidates"] = {
                        str(draw_id): _candidate_payload(candidate)
                        for draw_id, candidate in candidates.items()
                    }
                    _save_checkpoint(checkpoint_path, checkpoint)
                except Exception as exc:
                    errors = stats["errors"]
                    assert isinstance(errors, list)
                    errors.append(
                        {
                            "source": "ketquaday",
                            "draw_id": str(numeric_id).zfill(7),
                            "error": str(exc),
                        }
                    )
                _write_recovery_progress(
                    progress_path,
                    phase="ketquaday",
                    completed=len(checked),
                    total=len(missing_ids),
                    stats=stats,
                    started=started,
                )
                _submit_detail(executor, futures, iterator, clients)
    return candidates


def _submit_detail(
    executor: ThreadPoolExecutor,
    futures: dict[Future[tuple[int, DrawRecord | None]], int],
    ids,
    clients: ArchiveClients,
) -> None:
    try:
        numeric_id = next(ids)
    except StopIteration:
        return
    futures[executor.submit(_fetch_ketquaday, numeric_id, clients)] = numeric_id


def _fetch_ketquaday(
    numeric_id: int,
    clients: ArchiveClients,
) -> tuple[int, DrawRecord | None]:
    url = f"{KETQUADAY_BASE}/ket-qua-keno-ky-{numeric_id}"
    html = clients.get().get_text(url)
    record = parse_ketquaday_keno_detail(html, source_url=url)
    if record is not None and int(record.draw_id) != numeric_id:
        raise ValueError(f"requested {numeric_id}, parsed {record.draw_id}")
    return numeric_id, record


def _repair_known_mismatches(
    store: SqliteDatasetStore,
    clients: ArchiveClients,
    stats: dict[str, object],
) -> None:
    report_path = store.output_dir / "keno-history-report.json"
    if not report_path.exists():
        return
    report = json.loads(report_path.read_text(encoding="utf-8"))
    repairs = stats["mismatch_repairs"]
    assert isinstance(repairs, list)
    for example in report.get("mismatch_examples", []):
        numeric_id = int(example["draw_id"])
        _, record = _fetch_ketquaday(numeric_id, clients)
        if record is None:
            continue
        validate_draw(record, PRODUCT_SPECS["keno"])
        row = record.to_row()
        stored = store.connection.execute(
            "SELECT draw_date, result_json FROM draws WHERE product='keno' AND draw_id=?",
            (record.draw_id,),
        ).fetchone()
        if stored is None:
            continue
        changed = (str(stored[0]), str(stored[1])) != (
            str(row["draw_date"]),
            str(row["result_json"]),
        )
        if changed:
            store.upsert([record], [])
        repairs.append(
            {
                "draw_id": record.draw_id,
                "changed": changed,
                "selected_source": KETQUADAY_BASE,
                "selected_date": row["draw_date"],
                "selected_result_json": row["result_json"],
            }
        )


def _recover_or_confirm_onbit(
    store: SqliteDatasetStore,
    clients: ArchiveClients,
    missing_ids: list[int],
    *,
    progress_path: Path,
    stats: dict[str, object],
    started: float,
    ketquaday_candidates: dict[int, DrawRecord],
) -> set[int]:
    unresolved = set(missing_ids)
    confirmed: set[int] = set()
    page_cache: dict[int, list[DrawRecord]] = {}
    total = len(unresolved)
    while unresolved:
        target = min(unresolved)
        records = _find_onbit_page(
            target,
            clients,
            page_cache,
            stats,
        )
        by_id = {int(record.draw_id): record for record in records}
        recovered = sorted(unresolved & by_id.keys())
        if recovered:
            batch: list[DrawRecord] = []
            disputed: set[int] = set()
            for value in recovered:
                onbit_record = by_id[value]
                candidate = ketquaday_candidates.get(value)
                if candidate is not None:
                    onbit_row = onbit_record.to_row()
                    candidate_row = candidate.to_row()
                    if (
                        onbit_row["draw_date"],
                        onbit_row["result_json"],
                    ) != (
                        candidate_row["draw_date"],
                        candidate_row["result_json"],
                    ):
                        conflicts = stats["secondary_conflicts"]
                        assert isinstance(conflicts, list)
                        conflicts.append(
                            {
                                "draw_id": str(value).zfill(7),
                                "resolution": "unresolved",
                                "ketquaday_date": candidate_row["draw_date"],
                                "onbit_date": onbit_row["draw_date"],
                                "ketquaday_result_json": candidate_row["result_json"],
                                "onbit_result_json": onbit_row["result_json"],
                            }
                        )
                        disputed.add(value)
                        continue
                    onbit_record.attributes["corroborated_by"] = candidate.source_url
                    stats["ketquaday_inserted"] = (
                        int(stats["ketquaday_inserted"]) + 1
                    )
                batch.append(onbit_record)
            for record in batch:
                validate_draw(record, PRODUCT_SPECS["keno"])
            inserted = store.insert_missing_draws(batch)
            stats["onbit_rows_inserted"] = int(stats["onbit_rows_inserted"]) + inserted
            unresolved.difference_update(recovered)
            if disputed:
                errors = stats["errors"]
                assert isinstance(errors, list)
                errors.extend(
                    {
                        "source": "secondary_consensus",
                        "draw_id": str(value).zfill(7),
                        "error": "Ketquaday and Onbit disagree",
                    }
                    for value in sorted(disputed)
                )
        else:
            ids = sorted(by_id)
            lower = max((value for value in ids if value < target), default=None)
            upper = min((value for value in ids if value > target), default=None)
            if lower is None or upper is None:
                errors = stats["errors"]
                assert isinstance(errors, list)
                errors.append(
                    {
                        "source": "onbit",
                        "draw_id": str(target).zfill(7),
                        "error": "could not bracket missing ID",
                    }
                )
                unresolved.remove(target)
                continue
            absent = {
                value
                for value in unresolved
                if lower < value < upper
            }
            if not absent:
                errors = stats["errors"]
                assert isinstance(errors, list)
                errors.append(
                    {
                        "source": "onbit",
                        "draw_id": str(target).zfill(7),
                        "error": f"no absence interval between {lower} and {upper}",
                    }
                )
                unresolved.remove(target)
                continue
            candidate_conflicts = sorted(absent & ketquaday_candidates.keys())
            if candidate_conflicts:
                conflicts = stats["secondary_conflicts"]
                assert isinstance(conflicts, list)
                conflicts.extend(
                    {
                        "draw_id": str(value).zfill(7),
                        "resolution": "not_issued",
                        "reason": (
                            f"Onbit jumps from {upper} to {lower}; "
                            "xoso.com.vn and Vietlott also omit this ID"
                        ),
                        "discarded_single_source": ketquaday_candidates[value].source_url,
                    }
                    for value in candidate_conflicts
                )
            confirmed.update(absent)
            unresolved.difference_update(absent)
        completed = total - len(unresolved)
        _write_recovery_progress(
            progress_path,
            phase="onbit",
            completed=completed,
            total=total,
            stats=stats,
            started=started,
        )
    return confirmed


def _candidate_payload(record: DrawRecord) -> dict[str, object]:
    return {
        "draw_date": record.draw_date.isoformat(),
        "numbers": record.result["numbers"],
        "source_url": record.source_url,
        "draw_time": record.attributes.get("draw_time"),
    }


def _candidate_record(numeric_id: int, value: object) -> DrawRecord:
    if not isinstance(value, dict):
        raise ValueError(f"invalid checkpoint candidate for {numeric_id}")
    numbers = [int(number) for number in value["numbers"]]
    even = sum(number % 2 == 0 for number in numbers)
    small = sum(number <= 40 for number in numbers)
    attributes: dict[str, object] = {
        "odd_even": {"even": even, "odd": len(numbers) - even},
        "big_small": {"big": len(numbers) - small, "small": small},
        "data_source": "ketquaday_detail",
    }
    if value.get("draw_time"):
        attributes["draw_time"] = value["draw_time"]
    return DrawRecord(
        product="keno",
        draw_id=str(numeric_id).zfill(7),
        draw_date=datetime.fromisoformat(str(value["draw_date"])).date(),
        result={"numbers": numbers},
        attributes=attributes,
        source_url=str(value["source_url"]),
        prize_status="rules_available",
    )


def _find_onbit_page(
    target: int,
    clients: ArchiveClients,
    cache: dict[int, list[DrawRecord]],
    stats: dict[str, object],
) -> list[DrawRecord]:
    low = 1
    high = ONBIT_LAST_PAGE
    while low <= high:
        page = (low + high) // 2
        records = _onbit_page(page, clients, cache, stats)
        ids = [int(record.draw_id) for record in records]
        if not ids:
            high = page - 1
            continue
        maximum = max(ids)
        minimum = min(ids)
        if target > maximum:
            high = page - 1
        elif target < minimum:
            low = page + 1
        else:
            return records
    page = min(max(low, 1), ONBIT_LAST_PAGE)
    return _onbit_page(page, clients, cache, stats)


def _onbit_page(
    page: int,
    clients: ArchiveClients,
    cache: dict[int, list[DrawRecord]],
    stats: dict[str, object],
) -> list[DrawRecord]:
    if page in cache:
        return cache[page]
    url = f"{ONBIT_LIST}?page={page}"
    html = clients.get().get_text(ONBIT_LIST, params={"page": page})
    records = parse_onbit_keno_page(html, source_url=url)
    cache[page] = records
    stats["onbit_pages_requested"] = int(stats["onbit_pages_requested"]) + 1
    return records


def _latest_id(store: SqliteDatasetStore) -> int:
    return int(
        store.connection.execute(
            "SELECT MAX(CAST(draw_id AS INTEGER)) FROM draws WHERE product='keno'"
        ).fetchone()[0]
    )


def _update_state(
    output_dir: Path,
    *,
    complete: bool,
    unresolved: list[int],
    confirmed: set[int],
) -> None:
    state_store = StateStore(output_dir / ".collector-state.json")
    state = state_store.load()
    product = state_store.product(state, "keno")
    product.oldest_draw_id = "0000001"
    product.backfill_complete = complete
    product.known_history_incomplete = not complete
    if complete:
        product.history_gap_note = None
        product.last_error = None
    else:
        note = (
            f"Keno still has {len(unresolved)} unresolved IDs after secondary repair; "
            f"{len(confirmed)} ID jumps were independently confirmed."
        )
        product.history_gap_note = note
        product.last_error = note
    state_store.save(state)


def _write_recovery_progress(
    path: Path,
    *,
    phase: str,
    completed: int,
    total: int,
    stats: dict[str, object],
    started: float,
) -> None:
    elapsed = max(0.001, time.monotonic() - started)
    rate = completed / elapsed
    remaining = (total - completed) / rate if rate else 0
    finish = datetime.now(UTC) + timedelta(seconds=remaining)
    _write_progress(
        path,
        {
            "phase": phase,
            "details": {
                "updated_at": _now(),
                "completed": completed,
                "total": total,
                "percent": round(completed / max(1, total) * 100, 2),
                "ketquaday_inserted": stats["ketquaday_inserted"],
                "ketquaday_unavailable": stats["ketquaday_unavailable"],
                "onbit_pages_requested": stats["onbit_pages_requested"],
                "onbit_rows_inserted": stats["onbit_rows_inserted"],
                "errors": len(stats["errors"]),  # type: ignore[arg-type]
                "estimated_seconds_remaining": round(remaining),
                "estimated_finish_at": finish.isoformat(timespec="seconds"),
            },
        },
    )


def _load_checkpoint(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"version": 1, "ketquaday_checked_ids": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_checkpoint(path: Path, checkpoint: dict[str, object]) -> None:
    checkpoint["version"] = 1
    checkpoint["updated_at"] = _now()
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(
        json.dumps(checkpoint, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def _write_progress(path: Path, payload: dict[str, object]) -> None:
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


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
