from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .audit import audit_store
from .config import PRODUCT_SPECS, resolve_products
from .http import HttpClient, HttpSettings
from .pipeline import Collector, CollectorOptions
from .sources import OfficialVietlottSource
from .state import StateStore
from .storage import DatasetStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vietlott-collector",
        description="Collect public Vietlott draw history for data research.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    collect = subparsers.add_parser("collect", help="Collect new draws or resume a historical backfill.")
    collect.add_argument(
        "--products",
        nargs="+",
        default=["all"],
        help=f"Products to collect: all, {', '.join(PRODUCT_SPECS)}",
    )
    collect.add_argument("--output-dir", type=Path, default=Path("data"))
    collect.add_argument("--format", choices=("csv", "parquet"), default="parquet")
    collect.add_argument(
        "--backfill",
        action="store_true",
        help="Resume walking older pages. Without this flag, only new pages are checked.",
    )
    collect.add_argument(
        "--without-prizes",
        action="store_true",
        help="Skip detail pages and prize tables.",
    )
    collect.add_argument("--max-pages", type=_positive_int)
    collect.add_argument("--overlap-pages", type=_non_negative_int, default=2)
    collect.add_argument("--request-delay", type=_non_negative_float, default=1.0)
    collect.add_argument("--jitter", type=_non_negative_float, default=0.25)
    collect.add_argument("--timeout", type=_positive_float, default=30.0)
    collect.add_argument("--retries", type=_non_negative_int, default=5)
    collect.add_argument(
        "--contact-email",
        default="configure-your-email",
        help="Contact address included in the HTTP User-Agent.",
    )
    collect.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO")
    collect.add_argument("--log-file", type=Path, default=Path("logs/collector.log"))

    validate = subparsers.add_parser("validate", help="Audit saved files for duplicates and missing fields.")
    validate.add_argument("--output-dir", type=Path, default=Path("data"))
    validate.add_argument("--format", choices=("csv", "parquet"), default="parquet")

    subparsers.add_parser("products", help="List supported products.")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command == "products":
        for slug, spec in PRODUCT_SPECS.items():
            print(f"{slug:10} {spec.display_name}")
        return
    if args.command == "validate":
        report = audit_store(DatasetStore(args.output_dir, args.format))
        print(report.as_json())
        return

    _configure_logging(args.log_level, args.log_file)
    try:
        specs = resolve_products(args.products)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    settings = HttpSettings(
        timeout_seconds=args.timeout,
        request_delay_seconds=args.request_delay,
        jitter_seconds=args.jitter,
        retry_total=args.retries,
        user_agent=(
            f"vietlott-history-collector/0.1 (scientific data collection; contact: {args.contact_email})"
        ),
    )
    options = CollectorOptions(
        backfill=args.backfill,
        include_prizes=not args.without_prizes,
        max_pages=args.max_pages,
        overlap_pages=args.overlap_pages,
    )
    dataset_store = DatasetStore(args.output_dir, args.format)
    state_store = StateStore(args.output_dir / ".collector-state.json")

    with HttpClient(settings) as client:
        collector = Collector(
            OfficialVietlottSource(client),
            dataset_store,
            state_store,
            options,
        )
        summaries = collector.collect(specs)

    print("product,pages_fetched,draws_seen,draws_written,prizes_written,errors")
    for summary in summaries:
        print(
            f"{summary.product},{summary.pages_fetched},{summary.draws_seen},"
            f"{summary.draws_written},{summary.prizes_written},{summary.errors}"
        )
    if any(summary.errors for summary in summaries):
        sys.exit(2)


def _configure_logging(level: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(console)
    root.addHandler(file_handler)


def _positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def _non_negative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return number


def _positive_float(value: str) -> float:
    number = float(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def _non_negative_float(value: str) -> float:
    number = float(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return number
