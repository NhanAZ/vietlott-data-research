from pathlib import Path

from vietlott_collector.config import PRODUCT_SPECS
from vietlott_collector.parsers import (
    parse_detail_page,
    parse_fast_draw_detail,
    parse_ketquaday_keno_detail,
    parse_list_page,
    parse_onbit_keno_page,
    parse_xoso_keno_archive_page,
)
from vietlott_collector.validation import validate_draw

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_lotto_535_matrix_with_special_number() -> None:
    spec = PRODUCT_SPECS["lotto535"]
    records = parse_list_page(spec, fixture("matrix.html"))

    assert len(records) == 1
    assert records[0].draw_id == "00700"
    assert records[0].result["numbers"] == [18, 20, 26, 29, 33]
    assert records[0].result["special_numbers"] == [2]
    assert validate_draw(records[0], spec) == []


def test_parse_max3d_tiers() -> None:
    spec = PRODUCT_SPECS["max3d"]
    record = parse_list_page(spec, fixture("three_digit.html"))[0]

    assert record.draw_id == "01092"
    assert record.result["tiers"]["special"] == ["350", "839"]
    assert len(record.result["tiers"]["third"]) == 8
    assert validate_draw(record, spec) == []


def test_parse_historical_max4d_tiers() -> None:
    spec = PRODUCT_SPECS["max4d"]
    record = parse_list_page(spec, fixture("max4d.html"))[0]

    assert record.draw_id == "00722"
    assert record.result["tiers"]["first"] == ["0023"]
    assert record.result["tiers"]["second"] == ["5815", "9073"]
    assert record.result["tiers"]["consolation_2"] == ["XX23"]
    assert validate_draw(record, spec) == []


def test_parse_keno_columns_in_correct_order() -> None:
    spec = PRODUCT_SPECS["keno"]
    record = parse_list_page(spec, fixture("keno.html"))[0]

    assert len(record.result["numbers"]) == 20
    assert record.attributes["odd_even"] == "Chẵn (11)"
    assert record.attributes["big_small"] == "Nhỏ (11)"
    assert validate_draw(record, spec) == []


def test_parse_bingo_result_and_total() -> None:
    spec = PRODUCT_SPECS["bingo18"]
    record = parse_list_page(spec, fixture("bingo.html"))[0]

    assert record.result["digits"] == [1, 5, 5]
    assert record.attributes["total"] == 11
    assert validate_draw(record, spec) == []


def test_parse_detail_prizes_jackpot_and_pdf() -> None:
    spec = PRODUCT_SPECS["mega645"]
    detail = parse_detail_page(
        spec,
        "01515",
        spec.detail_url("01515"),
        fixture("detail.html"),
    )

    assert detail.attributes["jackpots_vnd"]["Jackpot"] == 13_466_713_000
    assert len(detail.prizes) == 2
    assert detail.prizes[1].winner_count == 15
    assert detail.prizes[1].prize_value_vnd == 10_000_000
    assert detail.official_pdf_urls[0].endswith("01515_mega_a4_01515.pdf")


def test_parse_combined_prize_value_and_winner_count() -> None:
    spec = PRODUCT_SPECS["keno"]
    detail = parse_detail_page(
        spec,
        "0284668",
        spec.detail_url("0284668"),
        fixture("detail_combined.html"),
    )

    assert detail.prizes[0].prize_value_vnd == 1_200_000
    assert detail.prizes[0].winner_count == 12
    assert detail.prizes[1].prize_value_vnd == 450_000
    assert detail.prizes[1].winner_count == 0


def test_parse_bingo_detail_draw() -> None:
    spec = PRODUCT_SPECS["bingo18"]
    html = """
    <table class="table-result-info">
      <tr><th>Ngày quay</th><th>Kỳ quay</th><th>Kết quả</th></tr>
      <tr>
        <td>22/10/2025</td><td>#0134489</td>
        <td>
          <span class="bong_tron_bingo small">6</span>
          <span class="bong_tron_bingo small">4</span>
          <span class="bong_tron_bingo small">3</span>
        </td>
      </tr>
    </table>
    """

    record = parse_fast_draw_detail(spec, spec.detail_url("0134489"), html)

    assert record is not None
    assert record.draw_id == "0134489"
    assert record.result["digits"] == [6, 4, 3]
    assert record.attributes["total"] == 13


def test_parse_fast_detail_not_found() -> None:
    spec = PRODUCT_SPECS["keno"]

    record = parse_fast_draw_detail(
        spec,
        spec.detail_url("0282796"),
        "<main>Không tìm thấy kết quả [0282796]</main>",
    )

    assert record is None


def test_parse_xoso_keno_archive_page() -> None:
    html = """
    <div class="keno-row1">
      <div class="keno-content">
        <div class="keno-col1">
          <a>Kỳ: <strong>#128269</strong></a>
          <span>28/03/2023 06:35</span>
        </div>
        <div class="keno-col2"><div class="kenno-btn-kq">
          <span class="btn-number-kq">03</span>
          <span class="btn-number-kq">06</span>
          <span class="btn-number-kq">12</span>
          <span class="btn-number-kq">16</span>
          <span class="btn-number-kq">18</span>
          <span class="btn-number-kq">25</span>
          <span class="btn-number-kq">27</span>
          <span class="btn-number-kq">28</span>
          <span class="btn-number-kq">31</span>
          <span class="btn-number-kq">33</span>
          <span class="btn-number-kq">34</span>
          <span class="btn-number-kq">38</span>
          <span class="btn-number-kq">48</span>
          <span class="btn-number-kq">53</span>
          <span class="btn-number-kq">61</span>
          <span class="btn-number-kq">63</span>
          <span class="btn-number-kq">72</span>
          <span class="btn-number-kq">74</span>
          <span class="btn-number-kq">77</span>
          <span class="btn-number-kq">80</span>
        </div></div>
      </div>
    </div>
    """

    records = parse_xoso_keno_archive_page(
        html,
        source_url="https://xoso.com.vn/ket-qua-keno-28-3-2023.html",
        archive_endpoint="https://xoso.com.vn/KeNo/GetMoreBydate",
    )

    assert len(records) == 1
    assert records[0].draw_id == "0128269"
    assert records[0].draw_date.isoformat() == "2023-03-28"
    assert len(records[0].result["numbers"]) == 20
    assert records[0].attributes["data_source"] == "xoso_com_vn_archive"
    assert validate_draw(records[0], PRODUCT_SPECS["keno"]) == []


def test_parse_empty_xoso_keno_archive_page() -> None:
    assert (
        parse_xoso_keno_archive_page(
            "\r\n",
            source_url="https://xoso.com.vn/ket-qua-keno-1-1-2020.html",
            archive_endpoint="https://xoso.com.vn/KeNo/GetMoreBydate",
        )
        == []
    )


def test_parse_ketquaday_keno_detail() -> None:
    numbers = "".join(
        f'<span class="btn-number-live">{number:02d}</span>'
        for number in range(1, 21)
    )
    html = f"""
    <div class="table-bkn">
      <div class="table-colxs1"><strong>#115204</strong></div>
      <div class="table-colxs2">18/1/2023 16:04</div>
      <div class="table-colxs3">{numbers}</div>
    </div>
    """
    record = parse_ketquaday_keno_detail(
        html,
        source_url="https://ketquaday.vn/ket-qua-keno-ky-115204",
    )

    assert record is not None
    assert record.draw_id == "0115204"
    assert record.draw_date.isoformat() == "2023-01-18"
    assert record.result["numbers"] == list(range(1, 21))


def test_parse_onbit_keno_page() -> None:
    numbers = "".join(
        f'<div class="red_number">{number}</div>'
        for number in range(1, 21)
    )
    html = f"""
    <table>
      <tr><th>Kỳ & Ngày</th><th>Kết quả</th></tr>
      <tr>
        <td>Kỳ #33061<br>01/09/2020<br>06:05:00</td>
        <td>{numbers}</td>
      </tr>
    </table>
    """
    records = parse_onbit_keno_page(
        html,
        source_url="https://onbit.vn/ket-qua-xo-so/vietlott-keno?page=47424",
    )

    assert len(records) == 1
    assert records[0].draw_id == "0033061"
    assert records[0].draw_date.isoformat() == "2020-09-01"
    assert records[0].result["numbers"] == list(range(1, 21))
