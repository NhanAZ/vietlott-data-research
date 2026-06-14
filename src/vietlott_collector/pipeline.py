from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass

from .config import ProductSpec
from .models import DrawRecord, PrizeRecord, utc_now_iso
from .sources import OfficialVietlottSource
from .state import ProductState, StateStore
from .storage import DatasetStore
from .validation import validate_draw

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CollectorOptions:
    backfill: bool = False
    include_prizes: bool = True
    max_pages: int | None = None
    overlap_pages: int = 2


@dataclass(slots=True)
class ProductSummary:
    product: str
    pages_fetched: int = 0
    current_page: int = 0
    estimated_total_pages: int = 0
    draws_seen: int = 0
    draws_written: int = 0
    prizes_written: int = 0
    errors: int = 0


class Collector:
    def __init__(
        self,
        source: OfficialVietlottSource,
        dataset_store: DatasetStore,
        state_store: StateStore,
        options: CollectorOptions,
        progress_callback: Callable[
            [ProductSpec, ProductSummary, ProductState],
            None,
        ]
        | None = None,
    ) -> None:
        self.source = source
        self.dataset_store = dataset_store
        self.state_store = state_store
        self.options = options
        self.progress_callback = progress_callback
        self.state = state_store.load()

    def collect(self, specs: list[ProductSpec]) -> list[ProductSummary]:
        summaries: list[ProductSummary] = []
        for spec in specs:
            try:
                summaries.append(self._collect_product(spec))
            except Exception as exc:
                product_state = self.state_store.product(self.state, spec.slug)
                product_state.last_error = str(exc)
                self.state_store.save(self.state)
                LOGGER.exception("Collection failed for %s", spec.slug)
                summaries.append(ProductSummary(product=spec.slug, errors=1))
        return summaries

    def _collect_product(self, spec: ProductSpec) -> ProductSummary:
        summary = ProductSummary(product=spec.slug)
        product_state = self.state_store.product(self.state, spec.slug)
        if self.options.backfill:
            product_state.backfill_complete = False
        existing_ids = self.dataset_store.existing_draw_ids(spec.slug)
        had_existing_draws = bool(existing_ids)
        incomplete_prize_ids = self.dataset_store.incomplete_prize_ids(spec.slug)
        context = self.source.bootstrap(spec)
        first_page = self.source.fetch_page(spec, 0, context)
        current_latest = _largest_id(record.draw_id for record in first_page)
        row_count = context.total_rows or (_numeric_id(current_latest) or 0)
        summary.estimated_total_pages = math.ceil(row_count / spec.page_size)
        start_page = self._start_page(spec, product_state, current_latest)
        LOGGER.info(
            "%s: start_page=%d, existing=%d, backfill=%s",
            spec.slug,
            start_page,
            len(existing_ids),
            self.options.backfill,
        )

        page = start_page
        while True:
            if self.options.max_pages is not None and summary.pages_fetched >= self.options.max_pages:
                break
            records = first_page if page == 0 else self.source.fetch_page(spec, page, context)
            summary.pages_fetched += 1
            summary.current_page = page + 1
            summary.draws_seen += len(records)
            if not records:
                if self.options.backfill:
                    product_state.backfill_complete = not product_state.known_history_incomplete
                break

            draw_batch: list[DrawRecord] = []
            prize_batch: list[PrizeRecord] = []
            new_ids_on_page = 0
            for record in records:
                is_new = record.draw_id not in existing_ids
                needs_prize_retry = record.draw_id in incomplete_prize_ids
                if not is_new and not needs_prize_retry:
                    continue
                validate_draw(record, spec)
                if is_new:
                    new_ids_on_page += 1
                if self.options.include_prizes:
                    try:
                        detail = self.source.fetch_detail(spec, record)
                        record.attributes.update(detail.attributes)
                        record.official_pdf_urls = detail.official_pdf_urls
                        record.prize_status = "complete" if detail.prizes else "empty"
                        if not detail.prizes:
                            record.validation_status = "warning"
                            record.validation_warnings.append(
                                "detail page contained no recognized prize rows"
                            )
                        prize_batch.extend(detail.prizes)
                        if detail.prizes:
                            incomplete_prize_ids.discard(record.draw_id)
                    except Exception as exc:
                        summary.errors += 1
                        record.prize_status = "fetch_failed"
                        record.validation_status = "warning"
                        record.validation_warnings.append(f"prize detail failed: {exc}")
                        LOGGER.warning(
                            "%s draw %s: detail request failed: %s",
                            spec.slug,
                            record.draw_id,
                            exc,
                        )
                draw_batch.append(record)
                existing_ids.add(record.draw_id)

            if draw_batch or prize_batch:
                self.dataset_store.upsert(draw_batch, prize_batch)
                summary.draws_written += len(draw_batch)
                summary.prizes_written += len(prize_batch)

            self._update_product_state(
                product_state,
                records,
                current_latest=current_latest,
                next_page=page + 1 if self.options.backfill else None,
            )
            self.state_store.save(self.state)
            if self.progress_callback is not None:
                self.progress_callback(spec, summary, product_state)

            if len(records) < spec.page_size:
                if self.options.backfill:
                    product_state.backfill_complete = not product_state.known_history_incomplete
                    self.state_store.save(self.state)
                break
            if not self.options.backfill:
                if not had_existing_draws:
                    break
                if new_ids_on_page == 0:
                    break
            page += 1

        product_state.last_success_at = utc_now_iso()
        product_state.last_error = (
            product_state.history_gap_note if product_state.known_history_incomplete else None
        )
        product_state.last_observed_latest_id = current_latest or product_state.last_observed_latest_id
        self.state_store.save(self.state)
        LOGGER.info(
            "%s: pages=%d, draws=%d, prizes=%d, errors=%d",
            spec.slug,
            summary.pages_fetched,
            summary.draws_written,
            summary.prizes_written,
            summary.errors,
        )
        return summary

    def _start_page(
        self,
        spec: ProductSpec,
        state: ProductState,
        current_latest: str | None,
    ) -> int:
        if not self.options.backfill:
            return 0
        page = max(0, state.backfill_next_page - self.options.overlap_pages)
        previous_latest = _numeric_id(state.last_observed_latest_id)
        latest = _numeric_id(current_latest)
        if previous_latest is not None and latest is not None and latest > previous_latest:
            shifted_rows = latest - previous_latest
            page += math.ceil(shifted_rows / spec.page_size)
        return max(0, page)

    @staticmethod
    def _update_product_state(
        state: ProductState,
        records: list[DrawRecord],
        *,
        current_latest: str | None,
        next_page: int | None,
    ) -> None:
        ids = [record.draw_id for record in records]
        state.newest_draw_id = _max_id(state.newest_draw_id, current_latest, *ids)
        state.oldest_draw_id = _min_id(state.oldest_draw_id, *ids)
        state.last_observed_latest_id = current_latest or state.last_observed_latest_id
        if next_page is not None:
            state.backfill_next_page = next_page


def _numeric_id(value: str | None) -> int | None:
    return int(value) if value and value.isdigit() else None


def _largest_id(values) -> str | None:
    numeric = [(int(value), value) for value in values if value and value.isdigit()]
    return max(numeric)[1] if numeric else None


def _max_id(*values: str | None) -> str | None:
    return _largest_id(value for value in values if value)


def _min_id(*values: str | None) -> str | None:
    numeric = [(int(value), value) for value in values if value and value.isdigit()]
    return min(numeric)[1] if numeric else None
