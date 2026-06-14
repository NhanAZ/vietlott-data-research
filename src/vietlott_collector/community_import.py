from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

from .config import PRODUCT_SPECS
from .models import DrawRecord
from .storage import SqliteDatasetStore
from .validation import validate_draw

LOGGER = logging.getLogger(__name__)
UPSTREAM_URL = "https://github.com/vietvudanh/vietlott-data"

FILE_PRODUCTS = {
    "power645.jsonl": "mega645",
    "power655.jsonl": "power655",
    "power535.jsonl": "lotto535",
    "3d.jsonl": "max3d",
    "3d_pro.jsonl": "max3dpro",
    "keno.jsonl": "keno",
    "bingo18.jsonl": "bingo18",
}


def import_community_history(
    store: SqliteDatasetStore,
    data_dir: Path,
    *,
    batch_size: int = 5_000,
) -> dict[str, int]:
    imported: dict[str, int] = {}
    for filename, product in FILE_PRODUCTS.items():
        path = data_dir / filename
        if not path.exists():
            LOGGER.warning("Community data file is missing: %s", path)
            continue
        count = 0
        batch: list[DrawRecord] = []
        for record in _records(path, product):
            batch.append(record)
            if len(batch) >= batch_size:
                count += store.insert_missing_draws(batch)
                batch.clear()
        count += store.insert_missing_draws(batch)
        imported[product] = count
        LOGGER.info("Community import %s: %d new draws", product, count)
    return imported


def _records(path: Path, product: str) -> Iterator[DrawRecord]:
    spec = PRODUCT_SPECS[product]
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                raw = json.loads(line)
                draw_id = str(raw["id"]).removeprefix("#")
                result, attributes = _normalize_result(product, raw)
                record = DrawRecord(
                    product=product,
                    draw_id=draw_id,
                    draw_date=date.fromisoformat(str(raw["date"])),
                    result=result,
                    attributes={
                        **attributes,
                        "data_source": "community_mirror",
                        "secondary_source_url": UPSTREAM_URL,
                        "upstream_claimed_source": "vietlott.vn",
                    },
                    source_url=spec.detail_url(draw_id),
                    prize_status="not_requested",
                )
                validate_draw(record, spec)
                yield record
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                LOGGER.warning("%s:%d: skipped malformed row: %s", path, line_number, exc)


def _normalize_result(
    product: str,
    raw: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    value = raw["result"]
    if product == "mega645":
        return {"numbers": [int(number) for number in value], "special_numbers": []}, {}
    if product == "power655":
        numbers = [int(number) for number in value]
        return {"numbers": numbers[:6], "special_numbers": numbers[6:7]}, {}
    if product == "lotto535":
        numbers = [int(number) for number in value]
        return {"numbers": numbers[:5], "special_numbers": numbers[5:6]}, {}
    if product in {"max3d", "max3dpro"}:
        tiers = list(value.values())
        if len(tiers) < 4:
            raise ValueError("three-digit result has fewer than four tiers")
        return {
            "tiers": {
                "special": [str(number).zfill(3) for number in tiers[0]],
                "first": [str(number).zfill(3) for number in tiers[1]],
                "second": [str(number).zfill(3) for number in tiers[2]],
                "third": [str(number).zfill(3) for number in tiers[3]],
            }
        }, {}
    if product == "keno":
        numbers = [int(number) for number in value]
        even = sum(number % 2 == 0 for number in numbers)
        small = sum(number <= 40 for number in numbers)
        return {"numbers": numbers}, {
            "odd_even": {"even": even, "odd": len(numbers) - even},
            "big_small": {"big": len(numbers) - small, "small": small},
        }
    if product == "bingo18":
        digits = [int(number) for number in value]
        total = sum(digits)
        return {"digits": digits}, {
            "total": total,
            "big_small": "big" if total > 10 else "small" if total < 10 else "tie",
        }
    raise ValueError(f"Unsupported community product: {product}")
