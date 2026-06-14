from __future__ import annotations

import argparse
import json
import logging
import math
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .config import ProductSpec, resolve_products
from .http import HttpClient, HttpSettings
from .sources import OfficialVietlottSource
from .storage import SqliteDatasetStore
from .validation import validate_draw

LOGGER = logging.getLogger(__name__)
DEFAULT_PRODUCTS = ["mega645", "power655", "lotto535", "max3d", "max3dpro", "max4d"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vietlott-official-reconcile",
        description="Compare every official list row with the local database and correct mismatches.",
    )
    parser.add_argument("--products", nargs="+", default=DEFAULT_PRODUCTS)
    parser.add_argument("--output-dir", type=Path, default=Path("data"))
    parser.add_argument("--request-delay", type=float, default=0.65)
    parser.add_argument("--jitter", type=float, default=0.15)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--contact-email", default="configure-your-email")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    specs = resolve_products(args.products)
    settings = HttpSettings(
        timeout_seconds=args.timeout,
        request_delay_seconds=args.request_delay,
        jitter_seconds=args.jitter,
        retry_total=args.retries,
        user_agent=(
            f"vietlott-history-collector/0.1 (scientific data verification; contact: {args.contact_email})"
        ),
    )
    log_path = args.output_dir / "official-reconcile.log"
    _configure_logging(log_path)
    store = SqliteDatasetStore(args.output_dir)
    report: dict[str, object] = {"started_at": _now(), "products": {}}
    try:
        total_pages = _estimate_pages(specs, settings)
        completed_pages = 0
        started = time.monotonic()
        with HttpClient(settings) as client:
            source = OfficialVietlottSource(client)
            for spec in specs:
                product_report: dict[str, object] = {
                    "checked": 0,
                    "inserted": 0,
                    "changed": 0,
                    "date_mismatches": 0,
                    "result_mismatches": 0,
                    "examples": [],
                }
                context = source.bootstrap(spec)
                first_page = source.fetch_page(spec, 0, context)
                latest_id = max(int(record.draw_id) for record in first_page)
                product_pages = math.ceil(latest_id / spec.page_size)
                for page in range(product_pages):
                    records = first_page if page == 0 else source.fetch_page(spec, page, context)
                    for record in records:
                        validate_draw(record, spec)
                    batch = store.reconcile_official_draws(records)
                    _merge_stats(product_report, batch)
                    completed_pages += 1
                    _write_progress(
                        args.output_dir,
                        spec,
                        page + 1,
                        product_pages,
                        completed_pages,
                        total_pages,
                        started,
                        store,
                    )
                report["products"][spec.slug] = product_report  # type: ignore[index]
                LOGGER.info("%s reconciliation: %s", spec.slug, product_report)
        report["finished_at"] = _now()
        report["database_counts"] = store.counts()
        report_path = args.output_dir / "official-reconcile-report.json"
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        store.export_csv()
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        store.close()


def _estimate_pages(specs: list[ProductSpec], settings: HttpSettings) -> int:
    total = 0
    with HttpClient(settings) as client:
        source = OfficialVietlottSource(client)
        for spec in specs:
            context = source.bootstrap(spec)
            records = source.fetch_page(spec, 0, context)
            latest_id = max(int(record.draw_id) for record in records)
            total += math.ceil(latest_id / spec.page_size)
    return total


def _merge_stats(target: dict[str, object], batch: dict[str, object]) -> None:
    for key in ("checked", "inserted", "changed", "date_mismatches", "result_mismatches"):
        target[key] = int(target[key]) + int(batch[key])
    examples: list = target["examples"]  # type: ignore[assignment]
    examples.extend(batch["examples"])
    del examples[50:]


def _write_progress(
    output_dir: Path,
    spec: ProductSpec,
    product_page: int,
    product_pages: int,
    completed_pages: int,
    total_pages: int,
    started: float,
    store: SqliteDatasetStore,
) -> None:
    elapsed = max(0.001, time.monotonic() - started)
    rate = completed_pages / elapsed
    remaining_seconds = (total_pages - completed_pages) / rate
    finish = datetime.now(UTC) + timedelta(seconds=remaining_seconds)
    draws, prizes = store.counts()
    payload = {
        "phase": "official_reconcile",
        "details": {
            "pid": os.getpid(),
            "updated_at": _now(),
            "current_product": spec.slug,
            "current_page": product_page,
            "estimated_product_pages": product_pages,
            "product_percent": round(product_page / product_pages * 100, 2),
            "overall_percent": round(completed_pages / total_pages * 100, 2),
            "estimated_seconds_remaining": round(remaining_seconds),
            "estimated_finish_at": finish.isoformat(timespec="seconds"),
            "draw_rows": draws,
            "prize_rows": prizes,
            "completed_requests": completed_pages,
            "planned_requests": total_pages,
            "errors_this_batch": 0,
        },
    }
    _atomic_json(output_dir / "final-audit-status.json", payload)


def _atomic_json(path: Path, payload: object) -> None:
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
