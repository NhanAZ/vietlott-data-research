from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .config import PRODUCT_SPECS
from .http import HttpClient, HttpSettings
from .parsers import parse_fast_draw_detail
from .state import StateStore
from .storage import SqliteDatasetStore
from .validation import validate_draw

LOGGER = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vietlott-fast-gap-reconcile",
        description="Resolve missing Keno and Bingo18 IDs through official detail pages.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("data"))
    parser.add_argument("--request-delay", type=float, default=0.55)
    parser.add_argument("--jitter", type=float, default=0.15)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--contact-email", default="configure-your-email")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    _configure_logging(args.output_dir / "fast-gap-reconcile.log")
    store = SqliteDatasetStore(args.output_dir)
    state_store = StateStore(args.output_dir / ".collector-state.json")
    state = state_store.load()
    settings = HttpSettings(
        timeout_seconds=args.timeout,
        request_delay_seconds=args.request_delay,
        jitter_seconds=args.jitter,
        retry_total=args.retries,
        user_agent=(
            f"vietlott-history-collector/0.1 (scientific gap verification; contact: {args.contact_email})"
        ),
    )
    candidates: list[tuple[str, int]] = []
    for product in ("keno", "bingo18"):
        product_state = state_store.product(state, product)
        if not product_state.oldest_draw_id or not product_state.newest_draw_id:
            continue
        missing = store.missing_numeric_draw_ids(
            product,
            int(product_state.oldest_draw_id),
            int(product_state.newest_draw_id),
        )
        candidates.extend((product, draw_id) for draw_id in missing)
    report: dict[str, object] = {
        "started_at": _now(),
        "candidate_ids": len(candidates),
        "found_and_inserted": [],
        "confirmed_nonexistent": [],
        "errors": [],
    }
    started = time.monotonic()
    try:
        with HttpClient(settings) as client:
            for index, (product, numeric_id) in enumerate(candidates, start=1):
                spec = PRODUCT_SPECS[product]
                draw_id = str(numeric_id).zfill(7)
                url = spec.detail_url(draw_id)
                try:
                    html = client.get_text(url)
                    record = parse_fast_draw_detail(spec, url, html)
                    if record is None:
                        report["confirmed_nonexistent"].append(  # type: ignore[union-attr]
                            {"product": product, "draw_id": draw_id}
                        )
                    else:
                        validate_draw(record, spec)
                        store.reconcile_official_draws([record])
                        report["found_and_inserted"].append(  # type: ignore[union-attr]
                            {
                                "product": product,
                                "draw_id": record.draw_id,
                                "draw_date": record.draw_date.isoformat(),
                                "result": record.result,
                            }
                        )
                except Exception as exc:
                    LOGGER.warning("%s %s failed: %s", product, draw_id, exc)
                    report["errors"].append(  # type: ignore[union-attr]
                        {"product": product, "draw_id": draw_id, "error": str(exc)}
                    )
                _write_progress(
                    args.output_dir,
                    index,
                    len(candidates),
                    product,
                    draw_id,
                    started,
                    store,
                    report,
                )
        for product in ("keno", "bingo18"):
            product_state = state_store.product(state, product)
            product_errors = [
                row
                for row in report["errors"]  # type: ignore[union-attr]
                if row["product"] == product
            ]
            product_state.backfill_complete = (
                not product_errors and not product_state.known_history_incomplete
            )
            if product_errors:
                product_state.last_error = (
                    f"{len(product_errors)} detail gap checks failed"
                )
            elif product_state.known_history_incomplete:
                product_state.last_error = product_state.history_gap_note
            else:
                product_state.last_error = None
        state_store.save(state)
        report["finished_at"] = _now()
        report["database_counts"] = store.counts()
        report_path = args.output_dir / "fast-gap-reconcile-report.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        store.export_csv()
        print(
            json.dumps(
                {
                    "candidate_ids": len(candidates),
                    "found_and_inserted": len(report["found_and_inserted"]),
                    "confirmed_nonexistent": len(report["confirmed_nonexistent"]),
                    "errors": len(report["errors"]),
                    "database_counts": report["database_counts"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        store.close()


def _write_progress(
    output_dir: Path,
    completed: int,
    total: int,
    product: str,
    draw_id: str,
    started: float,
    store: SqliteDatasetStore,
    report: dict[str, object],
) -> None:
    elapsed = max(0.001, time.monotonic() - started)
    rate = completed / elapsed
    remaining = (total - completed) / rate
    finish = datetime.now(UTC) + timedelta(seconds=remaining)
    draws, prizes = store.counts()
    payload = {
        "phase": "fast_gap_reconcile",
        "details": {
            "updated_at": _now(),
            "current_product": product,
            "current_draw_id": draw_id,
            "current_page": completed,
            "estimated_product_pages": total,
            "product_percent": round(completed / max(1, total) * 100, 2),
            "overall_percent": round(completed / max(1, total) * 100, 2),
            "estimated_seconds_remaining": round(remaining),
            "estimated_finish_at": finish.isoformat(timespec="seconds"),
            "draw_rows": draws,
            "prize_rows": prizes,
            "found": len(report["found_and_inserted"]),  # type: ignore[arg-type]
            "nonexistent": len(report["confirmed_nonexistent"]),  # type: ignore[arg-type]
            "errors_this_batch": len(report["errors"]),  # type: ignore[arg-type]
        },
    }
    path = output_dir / "final-audit-status.json"
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for attempt in range(20):
        try:
            temp_path.replace(path)
            return
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))
    temp_path.unlink(missing_ok=True)


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
