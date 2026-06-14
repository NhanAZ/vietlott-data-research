from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup

from ..models import DrawRecord


def parse_ketquaday_keno_detail(
    html: str,
    *,
    source_url: str,
) -> DrawRecord | None:
    soup = BeautifulSoup(html, "html.parser")
    block = soup.select_one("div.table-bkn")
    if block is None:
        return None
    identity = block.select_one("div.table-colxs1")
    date_cell = block.select_one("div.table-colxs2")
    if identity is None or date_cell is None:
        return None
    draw_match = re.search(r"#(\d+)", identity.get_text(" ", strip=True))
    date_match = re.search(
        r"(\d{1,2}/\d{1,2}/\d{4})(?:\s+(\d{1,2}:\d{2}))?",
        date_cell.get_text(" ", strip=True),
    )
    if draw_match is None or date_match is None:
        return None
    numbers = [
        int(span.get_text(strip=True))
        for span in block.select("span.btn-number-live")
    ]
    if len(numbers) != 20:
        return None
    return _record(
        draw_id=draw_match.group(1),
        draw_date=date_match.group(1),
        draw_time=date_match.group(2),
        numbers=numbers,
        source_url=source_url,
        data_source="ketquaday_detail",
    )


def parse_onbit_keno_page(
    html: str,
    *,
    source_url: str,
) -> list[DrawRecord]:
    soup = BeautifulSoup(html, "html.parser")
    records: list[DrawRecord] = []
    for row in soup.select("table tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 2:
            continue
        identity_text = cells[0].get_text(" ", strip=True)
        draw_match = re.search(r"Kỳ\s*#(\d+)", identity_text, re.IGNORECASE)
        date_match = re.search(
            r"(\d{1,2}/\d{1,2}/\d{4})(?:\s+(\d{1,2}:\d{2})(?::\d{2})?)?",
            identity_text,
        )
        numbers = [
            int(node.get_text(strip=True))
            for node in cells[1].select("div.red_number")
        ]
        if draw_match is None or date_match is None or len(numbers) != 20:
            continue
        records.append(
            _record(
                draw_id=draw_match.group(1),
                draw_date=date_match.group(1),
                draw_time=date_match.group(2),
                numbers=numbers,
                source_url=source_url,
                data_source="onbit_archive",
            )
        )
    return records


def _record(
    *,
    draw_id: str,
    draw_date: str,
    draw_time: str | None,
    numbers: list[int],
    source_url: str,
    data_source: str,
) -> DrawRecord:
    even = sum(number % 2 == 0 for number in numbers)
    small = sum(number <= 40 for number in numbers)
    attributes: dict[str, object] = {
        "odd_even": {"even": even, "odd": len(numbers) - even},
        "big_small": {"big": len(numbers) - small, "small": small},
        "data_source": data_source,
    }
    if draw_time:
        attributes["draw_time"] = draw_time
    return DrawRecord(
        product="keno",
        draw_id=draw_id.zfill(7),
        draw_date=datetime.strptime(draw_date, "%d/%m/%Y").date(),
        result={"numbers": numbers},
        attributes=attributes,
        source_url=source_url,
        prize_status="rules_available",
    )
