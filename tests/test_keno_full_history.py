from __future__ import annotations

import json

from vietlott_collector.keno_full_history import _can_continue_to_gap_repair


def test_can_continue_after_expected_history_cap(tmp_path) -> None:
    report = {
        "errors": [
            {
                "phase": "official_confirmation",
                "error": "783 IDs remain; refusing excessive detail requests",
            }
        ]
    }
    (tmp_path / "keno-history-report.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )

    assert _can_continue_to_gap_repair(tmp_path)


def test_does_not_continue_after_collection_error(tmp_path) -> None:
    report = {"errors": [{"date": "2020-01-01", "error": "network failed"}]}
    (tmp_path / "keno-history-report.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )

    assert not _can_continue_to_gap_repair(tmp_path)
