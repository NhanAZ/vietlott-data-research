from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .community_import import import_community_history
from .config import ProductSpec, resolve_products
from .http import HttpClient, HttpSettings
from .models import utc_now_iso
from .sources import OfficialVietlottSource
from .state import StateStore
from .storage import SqliteDatasetStore
from .validation import validate_draw

LOGGER = logging.getLogger(__name__)
STATIC_RULE_PRODUCTS = {"keno", "bingo18"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vietlott-full-backfill",
        description="Run a resumable full-history collection until every product is complete.",
    )
    parser.add_argument("--products", nargs="+", default=["all"])
    parser.add_argument("--output-dir", type=Path, default=Path("data"))
    parser.add_argument("--batch-pages", type=int, default=100)
    parser.add_argument("--overlap-pages", type=int, default=2)
    parser.add_argument("--request-delay", type=float, default=1.0)
    parser.add_argument("--jitter", type=float, default=0.25)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--retry-wait", type=float, default=60.0)
    parser.add_argument("--contact-email", default="configure-your-email")
    parser.add_argument("--community-repo", type=Path)
    parser.add_argument("--skip-community", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--log-file", type=Path)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    log_file = args.log_file or args.output_dir / "full-backfill.log"
    _configure_logging(args.log_level, log_file)
    specs = resolve_products(args.products)
    store = SqliteDatasetStore(args.output_dir)
    state_store = StateStore(args.output_dir / ".collector-state.json")
    try:
        migrated = store.import_csv_if_empty()
        LOGGER.info("SQLite ready: migrated draws=%d prizes=%d", *migrated)
        if not args.skip_community:
            data_dir = _community_data_dir(args.community_repo)
            imported = import_community_history(store, data_dir)
            LOGGER.info("Community history imported: %s", imported)
            store.export_csv()

        settings = HttpSettings(
            timeout_seconds=args.timeout,
            request_delay_seconds=args.request_delay,
            jitter_seconds=args.jitter,
            retry_total=args.retries,
            user_agent=(
                f"vietlott-history-collector/0.1 (scientific data collection; contact: {args.contact_email})"
            ),
        )
        plans = _build_selective_plans(specs, store, settings)
        detail_work = sum(
            store.incomplete_prize_count(spec.slug) + len(plans[spec.slug].missing_ids)
            for spec in specs
            if spec.slug not in STATIC_RULE_PRODUCTS
        )
        tracker = WorkProgressTracker(
            output_dir=args.output_dir,
            store=store,
            total_units=sum(len(plan.pages) for plan in plans.values()) + detail_work,
            request_delay=args.request_delay + (args.jitter / 2),
        )
        _run_selective_official_backfill(
            specs,
            plans,
            store,
            state_store,
            settings,
            tracker=tracker,
            retry_wait=args.retry_wait,
        )
        store.mark_rules_available(spec.slug for spec in specs if spec.slug in STATIC_RULE_PRODUCTS)
        _repair_dynamic_prizes(
            specs,
            store,
            settings,
            tracker=tracker,
            retry_wait=args.retry_wait,
        )
        paths = store.export_csv()
        report = store.audit_counts()
        _write_status(args.output_dir, "complete", report)
        LOGGER.info("Full backfill complete: %s; files=%s", report, paths)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        store.close()


@dataclass(frozen=True, slots=True)
class SelectivePlan:
    newest_id: int
    oldest_id: int
    total_pages: int
    missing_ids: tuple[int, ...]
    pages: tuple[int, ...]


class WorkProgressTracker:
    def __init__(
        self,
        *,
        output_dir: Path,
        store: SqliteDatasetStore,
        total_units: int,
        request_delay: float,
    ) -> None:
        self.output_dir = output_dir
        self.store = store
        self.total_units = max(1, total_units)
        self.request_delay = request_delay
        self.completed_units = 0
        self.started_at = time.monotonic()
        self.errors = 0

    def tick(
        self,
        *,
        phase: str,
        product: str,
        product_current: int,
        product_total: int,
        completed: bool = True,
        error: bool = False,
    ) -> None:
        if completed:
            self.completed_units += 1
        if error:
            self.errors += 1
        elapsed = max(0.001, time.monotonic() - self.started_at)
        rate = self.completed_units / elapsed if self.completed_units else 0
        remaining = max(0, self.total_units - self.completed_units)
        eta_seconds = remaining / rate if rate else remaining * self.request_delay
        finish_at = datetime.now(UTC) + timedelta(seconds=eta_seconds)
        draws, prizes = self.store.counts()
        details = {
            "pid": os.getpid(),
            "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "current_product": product,
            "current_page": product_current,
            "estimated_product_pages": max(1, product_total),
            "product_percent": round(product_current / max(1, product_total) * 100, 2),
            "overall_percent": round(self.completed_units / self.total_units * 100, 2),
            "estimated_seconds_remaining": round(eta_seconds),
            "estimated_finish_at": finish_at.isoformat(timespec="seconds"),
            "draw_rows": draws,
            "prize_rows": prizes,
            "completed_requests": self.completed_units,
            "planned_requests": self.total_units,
            "errors_this_batch": self.errors,
        }
        _write_status(self.output_dir, phase, details)


def _build_selective_plans(
    specs: list[ProductSpec],
    store: SqliteDatasetStore,
    settings: HttpSettings,
) -> dict[str, SelectivePlan]:
    plans: dict[str, SelectivePlan] = {}
    with HttpClient(settings) as client:
        source = OfficialVietlottSource(client)
        for spec in specs:
            context = source.bootstrap(spec)
            records = source.fetch_page(spec, 0, context)
            newest_id = max(
                (int(record.draw_id) for record in records if record.draw_id.isdigit()),
                default=0,
            )
            row_count = context.total_rows or newest_id
            oldest_id = max(1, newest_id - row_count + 1)
            missing_ids = store.missing_numeric_draw_ids(
                spec.slug,
                oldest_id,
                newest_id,
            )
            pages = sorted({(newest_id - draw_id) // spec.page_size for draw_id in missing_ids})
            plans[spec.slug] = SelectivePlan(
                newest_id=newest_id,
                oldest_id=oldest_id,
                total_pages=(row_count + spec.page_size - 1) // spec.page_size,
                missing_ids=tuple(missing_ids),
                pages=tuple(pages),
            )
    LOGGER.info(
        "Selective official plan: %s",
        {
            slug: {
                "missing_ids": len(plan.missing_ids),
                "pages": len(plan.pages),
                "all_pages": plan.total_pages,
            }
            for slug, plan in plans.items()
        },
    )
    return plans


def _run_selective_official_backfill(
    specs: list[ProductSpec],
    plans: dict[str, SelectivePlan],
    store: SqliteDatasetStore,
    state_store: StateStore,
    settings: HttpSettings,
    *,
    tracker: WorkProgressTracker,
    retry_wait: float,
) -> None:
    for spec in specs:
        plan = plans[spec.slug]
        with HttpClient(settings) as client:
            source = OfficialVietlottSource(client)
            context = source.bootstrap(spec)
            for index, page in enumerate(plan.pages, start=1):
                while True:
                    try:
                        records = source.fetch_page(spec, page, context)
                        for record in records:
                            validate_draw(record, spec)
                        store.insert_missing_draws(records)
                        tracker.tick(
                            phase="selective_official_backfill",
                            product=spec.slug,
                            product_current=index,
                            product_total=len(plan.pages),
                        )
                        break
                    except Exception as exc:
                        LOGGER.warning(
                            "%s page %d failed, retrying in %.1fs: %s",
                            spec.slug,
                            page,
                            retry_wait,
                            exc,
                        )
                        tracker.tick(
                            phase="selective_official_backfill",
                            product=spec.slug,
                            product_current=index - 1,
                            product_total=len(plan.pages),
                            completed=False,
                            error=True,
                        )
                        time.sleep(retry_wait)
        remaining = store.missing_numeric_draw_ids(
            spec.slug,
            plan.oldest_id,
            plan.newest_id,
        )
        state = state_store.load()
        product_state = state_store.product(state, spec.slug)
        product_state.backfill_next_page = plan.total_pages
        product_state.backfill_complete = (
            not remaining and not product_state.known_history_incomplete
        )
        width = len(product_state.newest_draw_id or str(plan.newest_id))
        product_state.newest_draw_id = str(plan.newest_id).zfill(width)
        product_state.oldest_draw_id = str(plan.oldest_id).zfill(width)
        product_state.last_observed_latest_id = product_state.newest_draw_id
        product_state.last_success_at = utc_now_iso()
        if remaining:
            product_state.last_error = f"{len(remaining)} official IDs remain missing"
        elif product_state.known_history_incomplete:
            product_state.last_error = product_state.history_gap_note
        else:
            product_state.last_error = None
        state_store.save(state)
        LOGGER.info(
            "%s selective backfill complete: pages=%d inserted_ids=%d remaining=%d",
            spec.slug,
            len(plan.pages),
            len(plan.missing_ids) - len(remaining),
            len(remaining),
        )


def _repair_dynamic_prizes(
    specs: list[ProductSpec],
    store: SqliteDatasetStore,
    settings: HttpSettings,
    *,
    tracker: WorkProgressTracker,
    retry_wait: float,
) -> None:
    for spec in specs:
        if spec.slug in STATIC_RULE_PRODUCTS:
            continue
        product_total = store.incomplete_prize_count(spec.slug)
        product_completed = 0
        stalled_rounds = 0
        while records := store.incomplete_draw_records(spec.slug, limit=250):
            completed = 0
            with HttpClient(settings) as client:
                source = OfficialVietlottSource(client)
                for record in records:
                    try:
                        detail = source.fetch_detail(spec, record)
                        record.attributes.update(detail.attributes)
                        record.official_pdf_urls = detail.official_pdf_urls
                        if detail.prizes:
                            record.prize_status = "complete"
                            store.upsert([record], detail.prizes)
                            completed += 1
                        else:
                            record.prize_status = "empty"
                            record.validation_status = "warning"
                            record.validation_warnings.append(
                                "detail page contained no recognized prize rows"
                            )
                            store.upsert([record], [])
                        product_completed += 1
                        tracker.tick(
                            phase="prize_repair",
                            product=spec.slug,
                            product_current=product_completed,
                            product_total=product_total,
                        )
                    except Exception as exc:
                        LOGGER.warning("%s draw %s repair failed: %s", spec.slug, record.draw_id, exc)
                        tracker.tick(
                            phase="prize_repair",
                            product=spec.slug,
                            product_current=product_completed,
                            product_total=product_total,
                            completed=False,
                            error=True,
                        )
            if completed == 0:
                stalled_rounds += 1
                if stalled_rounds >= 3:
                    LOGGER.error("%s: prize repair stalled with %d rows", spec.slug, len(records))
                    break
                time.sleep(retry_wait)
            else:
                stalled_rounds = 0
            _write_status(
                store.output_dir,
                "prize_repair",
                {
                    "product": spec.slug,
                    "batch": len(records),
                    "completed": completed,
                    "remaining": len(store.incomplete_prize_ids(spec.slug)),
                },
            )


def _community_data_dir(repo: Path | None) -> Path:
    project_root = Path(__file__).resolve().parents[2]
    target = repo or project_root / "_sources" / "vietlott-data"
    if (target / ".git").exists():
        subprocess.run(
            ["git", "-C", str(target), "pull", "--ff-only"],
            check=False,
            timeout=180,
        )
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "https://github.com/vietvudanh/vietlott-data.git",
                str(target),
            ],
            check=True,
            timeout=300,
        )
    data_dir = target / "data"
    if not data_dir.exists():
        raise FileNotFoundError(f"Community data directory was not found: {data_dir}")
    return data_dir


def _write_status(output_dir: Path, phase: str, details: object) -> None:
    path = output_dir / "full-backfill-status.json"
    temp_path = path.with_suffix(".json.tmp")
    temp_path.write_text(
        json.dumps({"phase": phase, "details": details}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for attempt in range(20):
        try:
            temp_path.replace(path)
            return
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))
    LOGGER.warning("Could not update progress status because the file is temporarily locked")
    temp_path.unlink(missing_ok=True)


def _configure_logging(level: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(level.upper())
    root.handlers.clear()
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(console)
    root.addHandler(file_handler)


if __name__ == "__main__":
    main()
