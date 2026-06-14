from __future__ import annotations

import json
from dataclasses import dataclass

import pandas as pd

from .storage import DatasetStore


@dataclass(frozen=True, slots=True)
class AuditReport:
    draw_rows: int
    prize_rows: int
    duplicate_draws: int
    duplicate_prizes: int
    missing_draw_fields: dict[str, int]
    warning_draws: int
    incomplete_prize_draws: int

    def as_dict(self) -> dict[str, object]:
        return {
            "draw_rows": self.draw_rows,
            "prize_rows": self.prize_rows,
            "duplicate_draws": self.duplicate_draws,
            "duplicate_prizes": self.duplicate_prizes,
            "missing_draw_fields": self.missing_draw_fields,
            "warning_draws": self.warning_draws,
            "incomplete_prize_draws": self.incomplete_prize_draws,
        }

    def as_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False, indent=2)


def audit_store(store: DatasetStore) -> AuditReport:
    draws = store.load_draws()
    prizes = store.load_prizes()
    required = ["product", "draw_id", "draw_date", "result_json", "source_url"]
    missing = {
        column: int(draws[column].isna().sum() + draws[column].astype(str).str.strip().eq("").sum())
        for column in required
    }
    duplicate_draws = int(draws.duplicated(["product", "draw_id"]).sum()) if not draws.empty else 0
    prize_key = [
        "product",
        "draw_id",
        "game_variant",
        "prize_tier",
        "winning_rule",
        "prize_value_vnd",
    ]
    duplicate_prizes = int(prizes.duplicated(prize_key).sum()) if not prizes.empty else 0
    warning_draws = _count_equal(draws, "validation_status", "warning")
    incomplete = 0
    if not draws.empty and "prize_status" in draws:
        complete_statuses = {"complete", "rules_available", "empty", "not_applicable"}
        incomplete = int((~draws["prize_status"].isin(complete_statuses)).sum())
    return AuditReport(
        draw_rows=len(draws),
        prize_rows=len(prizes),
        duplicate_draws=duplicate_draws,
        duplicate_prizes=duplicate_prizes,
        missing_draw_fields=missing,
        warning_draws=warning_draws,
        incomplete_prize_draws=incomplete,
    )


def _count_equal(frame: pd.DataFrame, column: str, value: str) -> int:
    if frame.empty or column not in frame:
        return 0
    return int(frame[column].eq(value).sum())
