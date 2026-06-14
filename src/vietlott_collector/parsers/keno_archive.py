from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup

from ..models import DrawRecord


def parse_xoso_keno_archive_page(
    html: str,
    *,
    source_url: str,
    archive_endpoint: str,
) -> list[DrawRecord]:
    soup = BeautifulSoup(html, "html.parser")
    records: list[DrawRecord] = []
    for block in soup.select("div.keno-row1"):
        identity = block.select_one("div.keno-col1")
        if identity is None:
            continue
        identity_text = identity.get_text(" ", strip=True)
        draw_match = re.search(r"#(\d+)", identity_text)
        date_match = re.search(
            r"(\d{1,2}/\d{1,2}/\d{4})(?:\s+(\d{1,2}:\d{2}))?",
            identity_text,
        )
        if draw_match is None or date_match is None:
            raise ValueError("Keno archive row has no draw ID or date")

        numbers = [
            int(span.get_text(strip=True))
            for span in block.select("div.kenno-btn-kq span.btn-number-kq")
        ]
        even = sum(number % 2 == 0 for number in numbers)
        small = sum(number <= 40 for number in numbers)
        attributes: dict[str, object] = {
            "odd_even": {"even": even, "odd": len(numbers) - even},
            "big_small": {"big": len(numbers) - small, "small": small},
            "data_source": "xoso_com_vn_archive",
            "archive_endpoint": archive_endpoint,
        }
        if date_match.group(2):
            attributes["draw_time"] = date_match.group(2)

        records.append(
            DrawRecord(
                product="keno",
                draw_id=draw_match.group(1).zfill(7),
                draw_date=datetime.strptime(date_match.group(1), "%d/%m/%Y").date(),
                result={"numbers": numbers},
                attributes=attributes,
                source_url=source_url,
                prize_status="rules_available",
            )
        )
    return records
