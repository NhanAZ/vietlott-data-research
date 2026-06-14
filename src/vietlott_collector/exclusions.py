from __future__ import annotations

import json
from dataclasses import dataclass

from .storage import SqliteDatasetStore


@dataclass(frozen=True, slots=True)
class DrawExclusion:
    product: str
    first_id: int
    last_id: int
    status: str
    effective_date: str
    reason: str
    source_url: str

    def draw_ids(self) -> range:
        return range(self.first_id, self.last_id + 1)


NOTICE_URL = (
    "https://vietlott.vn/vi/tin-tuc/"
    "20321-thong-bao-vv-xu-ly-ve-san-pham-keno-bingo-18-"
    "da-phat-hanh-ngay-02042026/"
)

_NOTICE_REASON = (
    "Kết quả không được Hội đồng giám sát xổ số và đơn vị kiểm toán "
    "độc lập xác nhận"
)

KNOWN_EXCLUSIONS = (
    DrawExclusion(
        product="keno",
        first_id=275_986,
        last_id=276_016,
        status="not_confirmed",
        effective_date="2026-04-02",
        reason=_NOTICE_REASON,
        source_url=NOTICE_URL,
    ),
    DrawExclusion(
        product="bingo18",
        first_id=160_137,
        last_id=160_168,
        status="not_confirmed",
        effective_date="2026-04-02",
        reason=_NOTICE_REASON,
        source_url=NOTICE_URL,
    ),
)


def apply_known_exclusions(store: SqliteDatasetStore) -> dict[str, int]:
    matched = 0
    absent = 0
    with store.connection:
        for exclusion in KNOWN_EXCLUSIONS:
            for numeric_id in exclusion.draw_ids():
                draw_id = str(numeric_id).zfill(7)
                row = store.connection.execute(
                    """
                    SELECT attributes_json
                    FROM draws
                    WHERE product = ? AND draw_id = ?
                    """,
                    (exclusion.product, draw_id),
                ).fetchone()
                if row is None:
                    absent += 1
                    continue
                attributes = json.loads(str(row[0]) or "{}")
                attributes["exclusion"] = {
                    "effective_date": exclusion.effective_date,
                    "reason": exclusion.reason,
                    "source_url": exclusion.source_url,
                }
                store.connection.execute(
                    """
                    UPDATE draws
                    SET draw_status = ?,
                        prize_status = 'not_applicable',
                        attributes_json = ?
                    WHERE product = ? AND draw_id = ?
                    """,
                    (
                        exclusion.status,
                        json.dumps(
                            attributes,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        exclusion.product,
                        draw_id,
                    ),
                )
                store.connection.execute(
                    "DELETE FROM prizes WHERE product = ? AND draw_id = ?",
                    (exclusion.product, draw_id),
                )
                matched += 1
    return {"matched_rows": matched, "absent_ids": absent}
