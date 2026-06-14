from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .models import utc_now_iso


@dataclass(slots=True)
class ProductState:
    newest_draw_id: str | None = None
    oldest_draw_id: str | None = None
    last_observed_latest_id: str | None = None
    backfill_next_page: int = 0
    backfill_complete: bool = False
    known_history_incomplete: bool = False
    history_gap_note: str | None = None
    last_success_at: str | None = None
    last_error: str | None = None


@dataclass(slots=True)
class CollectorState:
    version: int = 1
    updated_at: str = field(default_factory=utc_now_iso)
    products: dict[str, ProductState] = field(default_factory=dict)


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> CollectorState:
        if not self.path.exists():
            return CollectorState()
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        products = {slug: ProductState(**value) for slug, value in raw.get("products", {}).items()}
        return CollectorState(
            version=int(raw.get("version", 1)),
            updated_at=raw.get("updated_at", utc_now_iso()),
            products=products,
        )

    def save(self, state: CollectorState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        state.updated_at = utc_now_iso()
        payload: dict[str, Any] = asdict(state)
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temp_path, self.path)

    @staticmethod
    def product(state: CollectorState, slug: str) -> ProductState:
        return state.products.setdefault(slug, ProductState())
