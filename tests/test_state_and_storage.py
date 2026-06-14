import json
from datetime import date

from vietlott_collector.exclusions import apply_known_exclusions
from vietlott_collector.models import DrawRecord, PrizeRecord
from vietlott_collector.pipeline import Collector
from vietlott_collector.state import CollectorState, ProductState, StateStore
from vietlott_collector.storage import DatasetStore, SqliteDatasetStore


def draw(draw_id: str, number: int) -> DrawRecord:
    return DrawRecord(
        product="mega645",
        draw_id=draw_id,
        draw_date=date(2026, 6, 13),
        result={"numbers": [1, 2, 3, 4, 5, number], "special_numbers": []},
        source_url=f"https://vietlott.vn/detail?id={draw_id}",
        prize_status="complete",
        validation_status="valid",
    )


def test_state_round_trip(tmp_path) -> None:
    store = StateStore(tmp_path / ".collector-state.json")
    state = CollectorState()
    product = store.product(state, "mega645")
    product.newest_draw_id = "01522"
    product.backfill_next_page = 10
    product.known_history_incomplete = True
    product.history_gap_note = "Historical source gap"
    store.save(state)

    loaded = store.load()
    assert loaded.products["mega645"].newest_draw_id == "01522"
    assert loaded.products["mega645"].backfill_next_page == 10
    assert loaded.products["mega645"].known_history_incomplete is True
    assert loaded.products["mega645"].history_gap_note == "Historical source gap"


def test_incremental_state_update_does_not_reset_backfill_page() -> None:
    state = ProductState(backfill_next_page=100)

    Collector._update_product_state(
        state,
        [draw("01522", 6)],
        current_latest="01522",
        next_page=None,
    )

    assert state.backfill_next_page == 100


def test_csv_upsert_replaces_duplicate_draw(tmp_path) -> None:
    store = DatasetStore(tmp_path, "csv")
    store.upsert([draw("00001", 6)], [])
    store.upsert([draw("00001", 7), draw("00002", 8)], [])

    frame = store.load_draws()
    assert len(frame) == 2
    assert set(frame["draw_id"]) == {"00001", "00002"}
    updated = frame.loc[frame["draw_id"] == "00001", "result_json"].iloc[0]
    assert json.loads(updated)["numbers"][-1] == 7


def test_prize_rows_are_deduplicated(tmp_path) -> None:
    store = DatasetStore(tmp_path, "csv")
    prize = PrizeRecord(
        product="mega645",
        draw_id="00001",
        game_variant="Mega 6/45",
        prize_tier="Jackpot",
        winning_rule="O O O O O O",
        winner_count=0,
        prize_value_vnd=12_000_000_000,
        details={"source": "fixture"},
        source_url="https://vietlott.vn/detail?id=00001",
    )
    store.upsert([draw("00001", 6)], [prize, prize])

    assert len(store.load_prizes()) == 1


def test_sqlite_store_upsert_and_csv_export(tmp_path) -> None:
    store = SqliteDatasetStore(tmp_path)
    try:
        store.upsert([draw("00001", 6)], [])
        store.upsert([draw("00001", 7), draw("00002", 8)], [])
        paths = store.export_csv()

        assert store.counts() == (2, 0)
        assert len(paths) == 3
        assert all(path.exists() for path in paths)
        updated = store.load_draws().loc[lambda frame: frame["draw_id"] == "00001"]
        assert json.loads(updated["result_json"].iloc[0])["numbers"][-1] == 7
    finally:
        store.close()


def test_sqlite_store_reports_missing_numeric_ids(tmp_path) -> None:
    store = SqliteDatasetStore(tmp_path)
    try:
        store.insert_missing_draws(
            [
                draw("00001", 6),
                draw("00003", 7),
                draw("00005", 8),
            ]
        )

        assert store.missing_numeric_draw_ids("mega645", 1, 5) == [2, 4]
    finally:
        store.close()


def test_sqlite_reconciliation_prefers_official_result(tmp_path) -> None:
    store = SqliteDatasetStore(tmp_path)
    try:
        store.upsert([draw("00001", 6)], [])
        official = draw("00001", 9)
        report = store.reconcile_official_draws([official])

        assert report["changed"] == 1
        assert report["result_mismatches"] == 1
        updated = store.load_draws().iloc[0]
        assert json.loads(updated["result_json"])["numbers"][-1] == 9
        assert json.loads(updated["attributes_json"])["data_source"] == "official_vietlott"
    finally:
        store.close()


def test_known_exclusion_marks_draw_without_deleting_result(tmp_path) -> None:
    store = SqliteDatasetStore(tmp_path)
    try:
        record = DrawRecord(
            product="keno",
            draw_id="0275986",
            draw_date=date(2026, 4, 2),
            result={"numbers": list(range(1, 21))},
            source_url="https://vietlott.vn/example",
            prize_status="rules_available",
            validation_status="valid",
        )
        store.upsert([record], [])

        report = apply_known_exclusions(store)
        row = store.connection.execute(
            """
            SELECT draw_status, prize_status, result_json, attributes_json
            FROM draws
            WHERE product = 'keno' AND draw_id = '0275986'
            """
        ).fetchone()

        assert report["matched_rows"] == 1
        assert row[0] == "not_confirmed"
        assert row[1] == "not_applicable"
        assert json.loads(row[2])["numbers"] == list(range(1, 21))
        assert "official_notice_url" not in json.loads(row[3])
        assert json.loads(row[3])["exclusion"]["source_url"].startswith(
            "https://vietlott.vn/"
        )
    finally:
        store.close()
