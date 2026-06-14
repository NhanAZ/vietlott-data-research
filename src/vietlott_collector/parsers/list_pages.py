from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from ..config import BASE_URL, ParserKind, ProductSpec
from ..models import DrawRecord

DATE_PATTERN = re.compile(r"\b(\d{2}/\d{2}/\d{4})\b")


def parse_list_page(spec: ProductSpec, html: str) -> list[DrawRecord]:
    soup = BeautifulSoup(html, "html.parser")
    if spec.parser_kind is ParserKind.MATRIX:
        return _parse_matrix(spec, soup)
    if spec.parser_kind is ParserKind.THREE_DIGIT:
        return _parse_three_digit(spec, soup)
    if spec.parser_kind is ParserKind.FOUR_DIGIT:
        return _parse_four_digit(spec, soup)
    if spec.parser_kind is ParserKind.KENO:
        return _parse_keno(spec, soup)
    if spec.parser_kind is ParserKind.BINGO:
        return _parse_bingo(spec, soup)
    raise ValueError(f"Unsupported parser kind: {spec.parser_kind}")


def _parse_matrix(spec: ProductSpec, soup: BeautifulSoup) -> list[DrawRecord]:
    records: list[DrawRecord] = []
    for row in soup.select("table tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 3:
            continue
        draw_date = _parse_date(cells[0].get_text(" ", strip=True))
        draw_link = cells[1].find("a")
        if draw_date is None or draw_link is None:
            continue
        draw_id = _clean_draw_id(draw_link.get_text(" ", strip=True))
        if not draw_id:
            continue
        values = [
            int(span.get_text(strip=True))
            for span in cells[2].select("span.bong_tron")
            if span.get_text(strip=True).isdigit()
        ]
        main_count = spec.main_count or len(values)
        result = {
            "numbers": values[:main_count],
            "special_numbers": values[main_count : main_count + spec.special_count],
        }
        records.append(
            DrawRecord(
                product=spec.slug,
                draw_id=draw_id,
                draw_date=draw_date,
                result=result,
                source_url=_absolute_href(draw_link, spec.detail_url(draw_id)),
            )
        )
    return _deduplicate(records)


def _parse_three_digit(spec: ProductSpec, soup: BeautifulSoup) -> list[DrawRecord]:
    records: list[DrawRecord] = []
    for row in soup.select("table tr"):
        draw_link = row.find("a", href=re.compile(r"[?&]id=\d+"))
        result_root = row.select_one(".tong_day_so_ket_qua")
        if draw_link is None or result_root is None:
            continue
        draw_date = _parse_date(row.get_text(" ", strip=True))
        draw_id = _clean_draw_id(draw_link.get_text(" ", strip=True))
        if draw_date is None or not draw_id:
            continue
        digits = [
            span.get_text(strip=True)
            for span in result_root.select("span.bong_tron")
            if span.get_text(strip=True).isdigit()
        ]
        triplets = ["".join(digits[index : index + 3]) for index in range(0, len(digits), 3)]
        triplets = [value for value in triplets if len(value) == 3]
        tiers = {
            "special": triplets[0:2],
            "first": triplets[2:6],
            "second": triplets[6:12],
            "third": triplets[12:20],
        }
        records.append(
            DrawRecord(
                product=spec.slug,
                draw_id=draw_id,
                draw_date=draw_date,
                result={"tiers": tiers},
                source_url=_absolute_href(draw_link, spec.detail_url(draw_id)),
            )
        )
    return _deduplicate(records)


def _parse_four_digit(spec: ProductSpec, soup: BeautifulSoup) -> list[DrawRecord]:
    records: list[DrawRecord] = []
    for row in soup.select("table tr"):
        draw_link = row.find("a", href=re.compile(r"[?&]id=\d+"))
        result_root = row.select_one(".tong_day_so_ket_qua")
        if draw_link is None or result_root is None:
            continue
        draw_date = _parse_date(row.get_text(" ", strip=True))
        draw_id = _clean_draw_id(draw_link.get_text(" ", strip=True))
        if draw_date is None or not draw_id:
            continue
        symbols = [
            span.get_text(strip=True).upper()
            for span in result_root.select("span.bong_tron")
            if span.get_text(strip=True)
        ]
        values = ["".join(symbols[index : index + 4]) for index in range(0, len(symbols), 4)]
        values = [value for value in values if len(value) == 4]
        tiers = {
            "first": values[0:1],
            "second": values[1:3],
            "third": values[3:6],
            "consolation_1": values[6:7],
            "consolation_2": values[7:8],
        }
        records.append(
            DrawRecord(
                product=spec.slug,
                draw_id=draw_id,
                draw_date=draw_date,
                result={"tiers": tiers},
                source_url=_absolute_href(draw_link, spec.detail_url(draw_id)),
            )
        )
    return _deduplicate(records)


def _parse_keno(spec: ProductSpec, soup: BeautifulSoup) -> list[DrawRecord]:
    records: list[DrawRecord] = []
    for row in soup.select("table tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 4:
            continue
        links = cells[0].find_all("a")
        if len(links) < 2:
            continue
        draw_date = _parse_date(links[0].get_text(" ", strip=True))
        draw_id = _clean_draw_id(links[1].get_text(" ", strip=True))
        if draw_date is None or not draw_id:
            continue
        numbers = [
            int(span.get_text(strip=True))
            for span in cells[1].select("span.bong_tron")
            if span.get_text(strip=True).isdigit()
        ]
        records.append(
            DrawRecord(
                product=spec.slug,
                draw_id=draw_id,
                draw_date=draw_date,
                result={"numbers": numbers, "special_numbers": []},
                attributes={
                    "odd_even": cells[2].get_text(" ", strip=True),
                    "big_small": cells[3].get_text(" ", strip=True),
                },
                source_url=_absolute_href(links[1], spec.detail_url(draw_id)),
            )
        )
    return _deduplicate(records)


def _parse_bingo(spec: ProductSpec, soup: BeautifulSoup) -> list[DrawRecord]:
    records: list[DrawRecord] = []
    for row in soup.select("table tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 4:
            continue
        links = cells[0].find_all("a")
        if len(links) < 2:
            continue
        draw_date = _parse_date(links[0].get_text(" ", strip=True))
        draw_id = _clean_draw_id(links[1].get_text(" ", strip=True))
        if draw_date is None or not draw_id:
            continue
        digits = [
            int(span.get_text(strip=True))
            for span in cells[1].select("span.bong_tron_bingo")
            if span.get_text(strip=True).isdigit()
        ]
        total = _parse_integer(cells[2].get_text(" ", strip=True))
        records.append(
            DrawRecord(
                product=spec.slug,
                draw_id=draw_id,
                draw_date=draw_date,
                result={"digits": digits},
                attributes={
                    "total": total if total is not None else sum(digits),
                    "big_small": cells[3].get_text(" ", strip=True),
                },
                source_url=_absolute_href(links[1], spec.detail_url(draw_id)),
            )
        )
    return _deduplicate(records)


def _parse_date(text: str):
    match = DATE_PATTERN.search(text)
    if match is None:
        return None
    return datetime.strptime(match.group(1), "%d/%m/%Y").date()


def _parse_integer(text: str) -> int | None:
    match = re.search(r"-?\d+", text.replace(".", "").replace(",", ""))
    return int(match.group()) if match else None


def _clean_draw_id(value: str) -> str:
    return re.sub(r"\D", "", value)


def _absolute_href(link: Tag, fallback: str) -> str:
    href = link.get("href")
    return urljoin(BASE_URL, str(href)) if href else fallback


def _deduplicate(records: list[DrawRecord]) -> list[DrawRecord]:
    unique: dict[tuple[str, str], DrawRecord] = {}
    for record in records:
        unique[record.key] = record
    return list(unique.values())
