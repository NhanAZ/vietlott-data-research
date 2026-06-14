from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from ..config import BASE_URL, ParserKind, ProductSpec
from ..models import DetailResult, DrawRecord, PrizeRecord


def parse_detail_page(
    spec: ProductSpec,
    draw_id: str,
    source_url: str,
    html: str,
) -> DetailResult:
    soup = BeautifulSoup(html, "html.parser")
    result = DetailResult(
        attributes=_parse_summary_attributes(soup),
        official_pdf_urls=_parse_pdf_urls(soup),
    )
    for table_index, table in enumerate(soup.find_all("table")):
        headers, rows = _table_data(table)
        if not headers or not rows or not _looks_like_prize_table(headers):
            continue
        normalized = [_normalize(header) for header in headers]
        tier_index = _column_index(normalized, ("giai thuong", "hang giai", "giai", "cua dat"))
        rule_index = _column_index(
            normalized,
            ("ket qua", "cach trung", "noi dung", "bo so", "tong ket qua", "trung"),
        )
        winner_index = _column_index(
            normalized,
            ("so luong giai", "sl giai", "so luong", "so lan trung", "sl"),
        )
        value_index = _column_index(
            normalized,
            ("gia tri giai", "gia tri", "muc thuong", "tien thuong"),
        )
        variant = _context_label(table, spec.display_name)
        for row_index, cells in enumerate(rows):
            if not any(cells):
                continue
            details = {
                "table_index": table_index,
                "row_index": row_index,
                "columns": {
                    headers[index] if index < len(headers) else f"column_{index + 1}": value
                    for index, value in enumerate(cells)
                },
            }
            tier = _cell(cells, tier_index) or _cell(cells, 0) or f"row_{row_index + 1}"
            winning_rule = _cell(cells, rule_index)
            winner_value = _cell(cells, winner_index)
            combined_value_and_count = winner_index is not None and winner_index == value_index
            winner_count = _parse_winner_count(
                winner_value,
                combined_value_and_count=combined_value_and_count,
            )
            prize_value = _parse_currency(_cell(cells, value_index))
            result.prizes.append(
                PrizeRecord(
                    product=spec.slug,
                    draw_id=draw_id,
                    game_variant=variant,
                    prize_tier=tier,
                    winning_rule=winning_rule,
                    winner_count=winner_count,
                    prize_value_vnd=prize_value,
                    details=details,
                    source_url=source_url,
                )
            )
    result.prizes = _deduplicate_prizes(result.prizes)
    return result


def parse_fast_draw_detail(
    spec: ProductSpec,
    source_url: str,
    html: str,
) -> DrawRecord | None:
    if spec.parser_kind not in {ParserKind.KENO, ParserKind.BINGO}:
        raise ValueError(f"Fast detail parsing is unsupported for {spec.slug}")
    soup = BeautifulSoup(html, "html.parser")
    if re.search(r"Không tìm thấy kết quả", soup.get_text(" ", strip=True), re.IGNORECASE):
        return None
    table = next(
        (
            candidate
            for candidate in soup.select("table.table-result-info")
            if "Ngày quay" in candidate.get_text(" ", strip=True)
            and "Kỳ quay" in candidate.get_text(" ", strip=True)
        ),
        None,
    )
    if table is None:
        raise ValueError("detail page has no recognizable draw summary table")
    summary_row = next(
        (
            row
            for row in table.find_all("tr")
            if re.search(r"\d{2}/\d{2}/\d{4}", row.get_text(" ", strip=True))
            and re.search(r"#\d+", row.get_text(" ", strip=True))
        ),
        None,
    )
    if summary_row is None:
        raise ValueError("detail page has no draw date and ID row")
    text = summary_row.get_text(" ", strip=True)
    date_match = re.search(r"(\d{2}/\d{2}/\d{4})", text)
    id_match = re.search(r"#(\d+)", text)
    if date_match is None or id_match is None:
        raise ValueError("detail page draw identity is malformed")

    if spec.parser_kind is ParserKind.KENO:
        numbers = [int(span.get_text(strip=True)) for span in summary_row.select("span.bong_tron")]
        even = sum(number % 2 == 0 for number in numbers)
        small = sum(number <= 40 for number in numbers)
        result = {"numbers": numbers}
        attributes = {
            "odd_even": {"even": even, "odd": len(numbers) - even},
            "big_small": {"big": len(numbers) - small, "small": small},
        }
    else:
        digits = [int(span.get_text(strip=True)) for span in summary_row.select("span.bong_tron_bingo")]
        total = sum(digits)
        result = {"digits": digits}
        attributes = {
            "total": total,
            "big_small": "big" if total > 10 else "small" if total < 10 else "tie",
        }
    attributes["data_source"] = "official_vietlott"
    return DrawRecord(
        product=spec.slug,
        draw_id=id_match.group(1),
        draw_date=datetime.strptime(date_match.group(1), "%d/%m/%Y").date(),
        result=result,
        attributes=attributes,
        source_url=source_url,
        prize_status="rules_available",
    )


def _table_data(table: Tag) -> tuple[list[str], list[list[str]]]:
    header_row = table.select_one("thead tr")
    if header_row is None:
        first_row = table.find("tr")
        if first_row and first_row.find("th"):
            header_row = first_row
    if header_row is None:
        return [], []
    headers = [cell.get_text(" ", strip=True) for cell in header_row.find_all(["th", "td"], recursive=False)]
    rows: list[list[str]] = []
    for row in table.find_all("tr"):
        if row is header_row:
            continue
        cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"], recursive=False)]
        if cells:
            rows.append(cells)
    return headers, rows


def _looks_like_prize_table(headers: Iterable[str]) -> bool:
    text = " ".join(_normalize(value) for value in headers)
    markers = ("giai", "thuong", "gia tri", "so luong", " sl")
    return any(marker in text for marker in markers)


def _context_label(table: Tag, fallback: str) -> str:
    for element in table.find_all_previous(["caption", "h3", "h4", "h5", "strong"], limit=8):
        text = element.get_text(" ", strip=True)
        normalized = _normalize(text)
        if not text or len(text) > 100:
            continue
        if not re.search(r"[A-Za-zÀ-ỹ]", text):
            continue
        if "ky quay" in normalized or "ket qua quay" in normalized:
            continue
        return text
    classes = " ".join(str(value) for value in table.get("class", []))
    return classes or fallback


def _parse_summary_attributes(soup: BeautifulSoup) -> dict[str, object]:
    attributes: dict[str, object] = {}
    jackpots: dict[str, int] = {}
    for index, block in enumerate(soup.select(".gt_jackpot"), start=1):
        text = block.get_text(" ", strip=True)
        label_match = re.search(
            r"(Jackpot(?:\s+[12](?!\d))?)",
            text,
            flags=re.IGNORECASE,
        )
        amount_element = block.find(["h2", "h3", "h4"])
        amount = _parse_currency(amount_element.get_text(" ", strip=True) if amount_element else text)
        if amount is not None:
            label = label_match.group(1) if label_match else f"jackpot_{index}"
            jackpots[label] = amount
    if jackpots:
        attributes["jackpots_vnd"] = jackpots

    for candidate in soup.find_all(["h4", "h5"]):
        text = candidate.get_text(" ", strip=True)
        if re.search(r"Kỳ quay|Kỳ QSMT", text, re.IGNORECASE):
            attributes["detail_title"] = text
            break
    return attributes


def _parse_pdf_urls(soup: BeautifulSoup) -> list[str]:
    urls = {
        urljoin(BASE_URL, str(link.get("href")))
        for link in soup.find_all("a", href=True)
        if ".pdf" in str(link.get("href")).lower()
    }
    return sorted(urls)


def _column_index(headers: list[str], candidates: tuple[str, ...]) -> int | None:
    for candidate in candidates:
        for index, header in enumerate(headers):
            if candidate == header or candidate in header:
                return index
    return None


def _cell(cells: list[str], index: int | None) -> str | None:
    if index is None or index >= len(cells):
        return None
    value = cells[index].strip()
    return value or None


def _parse_integer(value: str | None) -> int | None:
    if value is None:
        return None
    compact = value.replace(".", "").replace(",", "")
    match = re.search(r"-?\d+", compact)
    return int(match.group()) if match else None


def _parse_winner_count(
    value: str | None,
    *,
    combined_value_and_count: bool,
) -> int | None:
    if value is None:
        return None
    labeled = re.search(
        r"Số\s*lượng\s*:\s*([\d.,]+)",
        value,
        flags=re.IGNORECASE,
    )
    if labeled:
        return _parse_integer(labeled.group(1))
    if combined_value_and_count:
        return 0
    return _parse_integer(value)


def _parse_currency(value: str | None) -> int | None:
    if value is None:
        return None
    amount = re.search(
        r"([\d][\d.,\s]*)\s*(?:đ|đồng|vnd)\b",
        value,
        flags=re.IGNORECASE,
    )
    selected = amount.group(1) if amount else value
    digits = re.sub(r"\D", "", selected)
    return int(digits) if digits else None


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", ascii_text.lower()).strip()


def _deduplicate_prizes(records: list[PrizeRecord]) -> list[PrizeRecord]:
    unique: dict[tuple[object, ...], PrizeRecord] = {}
    for record in records:
        unique[record.key] = record
    return list(unique.values())
