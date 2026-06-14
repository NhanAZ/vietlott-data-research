from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@dataclass(slots=True)
class DrawRecord:
    product: str
    draw_id: str
    draw_date: date
    result: dict[str, Any]
    source_url: str
    draw_status: str = "confirmed"
    attributes: dict[str, Any] = field(default_factory=dict)
    official_pdf_urls: list[str] = field(default_factory=list)
    prize_status: str = "not_requested"
    validation_status: str = "unchecked"
    validation_warnings: list[str] = field(default_factory=list)
    fetched_at: str = field(default_factory=utc_now_iso)

    @property
    def key(self) -> tuple[str, str]:
        return self.product, self.draw_id

    def to_row(self) -> dict[str, Any]:
        return {
            "product": self.product,
            "draw_id": self.draw_id,
            "draw_date": self.draw_date.isoformat(),
            "draw_status": self.draw_status,
            "result_json": canonical_json(self.result),
            "attributes_json": canonical_json(self.attributes),
            "official_pdf_urls_json": canonical_json(self.official_pdf_urls),
            "source_url": self.source_url,
            "prize_status": self.prize_status,
            "validation_status": self.validation_status,
            "validation_warnings_json": canonical_json(self.validation_warnings),
            "fetched_at": self.fetched_at,
        }


@dataclass(slots=True)
class PrizeRecord:
    product: str
    draw_id: str
    game_variant: str
    prize_tier: str
    winning_rule: str | None
    winner_count: int | None
    prize_value_vnd: int | None
    details: dict[str, Any]
    source_url: str
    fetched_at: str = field(default_factory=utc_now_iso)

    @property
    def key(self) -> tuple[Any, ...]:
        return (
            self.product,
            self.draw_id,
            self.game_variant,
            self.prize_tier,
            self.winning_rule or "",
            self.prize_value_vnd,
        )

    def to_row(self) -> dict[str, Any]:
        return {
            "product": self.product,
            "draw_id": self.draw_id,
            "game_variant": self.game_variant,
            "prize_tier": self.prize_tier,
            "winning_rule": self.winning_rule,
            "winner_count": self.winner_count,
            "prize_value_vnd": self.prize_value_vnd,
            "details_json": canonical_json(self.details),
            "source_url": self.source_url,
            "fetched_at": self.fetched_at,
        }


@dataclass(slots=True)
class DetailResult:
    prizes: list[PrizeRecord] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)
    official_pdf_urls: list[str] = field(default_factory=list)
