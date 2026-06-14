from vietlott_collector.config import PRODUCT_SPECS
from vietlott_collector.sources.vietlott import AjaxContext, OfficialVietlottSource


def test_matrix_payload_uses_discovered_key() -> None:
    payload = OfficialVietlottSource._payload(
        PRODUCT_SPECS["mega645"],
        3,
        AjaxContext(first_page_html="", dynamic_key="e5d3a96f"),
    )

    assert payload["Key"] == "e5d3a96f"
    assert payload["PageIndex"] == 3
    assert len(payload["ArrayNumbers"]) == 6


def test_keno_payload_uses_current_total_rows() -> None:
    payload = OfficialVietlottSource._payload(
        PRODUCT_SPECS["keno"],
        4,
        AjaxContext(first_page_html="", total_rows=38_429),
    )

    assert payload["GameId"] == "6"
    assert payload["TotalRow"] == 38_429
    assert payload["PageIndex"] == 4


def test_max4d_payload_uses_historical_game_id() -> None:
    payload = OfficialVietlottSource._payload(
        PRODUCT_SPECS["max4d"],
        2,
        AjaxContext(first_page_html=""),
    )

    assert payload["GameId"] == "2"
    assert payload["number"] == "1234"
    assert payload["PageIndex"] == 2
