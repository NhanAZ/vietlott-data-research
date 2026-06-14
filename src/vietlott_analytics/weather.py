from __future__ import annotations

import argparse
import csv
import json
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

LOGGER = logging.getLogger(__name__)

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
SOURCE_DOC_URL = "https://open-meteo.com/en/docs/historical-weather-api"
VENUE_SOURCE_URL = (
    "https://www.vietlott.vn/vi/tin-tuc/"
    "20199-thong-bao-thay-doi-dia-diem-trung-tam-quay-so-mo-thuong/"
)
DAILY_VARIABLES = (
    "temperature_2m_mean",
    "temperature_2m_min",
    "temperature_2m_max",
    "relative_humidity_2m_mean",
)
ARCHIVE_SAFETY_LAG_DAYS = 7
WEATHER_TIMEZONE = "Asia/Ho_Chi_Minh"
CSV_FIELDS = (
    "date",
    "venue_id",
    "venue_name",
    "address",
    "requested_latitude",
    "requested_longitude",
    "grid_latitude",
    "grid_longitude",
    *DAILY_VARIABLES,
    "weather_model",
    "source",
)


@dataclass(frozen=True, slots=True)
class VenuePeriod:
    venue_id: str
    name: str
    address: str
    latitude: float
    longitude: float
    start: date
    end: date | None


VENUES = (
    VenuePeriod(
        venue_id="lac_trung",
        name="Trung tâm QSMT tại VTC",
        address="Tầng 19, tòa nhà VTC, số 23 Lạc Trung, Hà Nội",
        latitude=21.0023039,
        longitude=105.8640524,
        start=date(2016, 7, 20),
        end=date(2025, 1, 21),
    ),
    VenuePeriod(
        venue_id="tam_trinh",
        name="Trung tâm QSMT tại VTC Online",
        address="Tầng 21, tòa nhà VTC Online, số 18 Tam Trinh, Hà Nội",
        latitude=20.9949485,
        longitude=105.8618052,
        start=date(2025, 1, 22),
        end=None,
    ),
)


def update_weather_dataset(
    output_dir: Path,
    *,
    start: date = VENUES[0].start,
    end: date | None = None,
    refresh_days: int = 14,
    retries: int = 4,
    request_delay: float = 0.8,
) -> dict[str, object]:
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "daily.csv"
    metadata_path = output_dir / "metadata.json"
    stable_end = _weather_today() - timedelta(days=ARCHIVE_SAFETY_LAG_DAYS)
    requested_end = min(end or stable_end, stable_end)
    if requested_end < start:
        raise ValueError("Weather end date is earlier than start date")

    existing = _read_existing(csv_path)
    refresh_start = max(start, requested_end - timedelta(days=max(0, refresh_days - 1)))
    missing_dates = {
        current
        for current in _date_range(start, requested_end)
        if current.isoformat() not in existing or current >= refresh_start
    }
    fetched: dict[str, dict[str, object]] = {}
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "vietlott-data-research/0.2 "
                "(https://github.com/NhanAZ/vietlott-data-research)"
            )
        }
    )

    for venue in VENUES:
        venue_start = max(start, venue.start)
        venue_end = min(requested_end, venue.end or requested_end)
        target_dates = [
            current
            for current in sorted(missing_dates)
            if venue_start <= current <= venue_end
        ]
        if not target_dates:
            continue
        fetched.update(
            _fetch_venue_range(
                session,
                venue,
                target_dates[0],
                target_dates[-1],
                retries=retries,
                request_delay=request_delay,
            )
        )

    # An incremental refresh may run before midnight in UTC while Vietnam is
    # already on the next date. Never let that make the historical cache shrink.
    merged = dict(existing)
    merged.update(fetched)
    _write_csv(csv_path, merged)
    metadata = {
        "schema_version": 1,
        "source": "Open-Meteo Historical Weather API",
        "source_documentation": SOURCE_DOC_URL,
        "source_endpoint": ARCHIVE_URL,
        "weather_model": "ERA5-Land",
        "timezone": WEATHER_TIMEZONE,
        "nominal_availability_delay_days": 5,
        "pipeline_safety_lag_days": ARCHIVE_SAFETY_LAG_DAYS,
        "first_date": min(merged) if merged else None,
        "latest_date": max(merged) if merged else None,
        "rows": len(merged),
        "variables": list(DAILY_VARIABLES),
        "venue_source": VENUE_SOURCE_URL,
        "geocoding_source": "https://www.openstreetmap.org/copyright",
        "venues": [
            {
                "venue_id": venue.venue_id,
                "name": venue.name,
                "address": venue.address,
                "latitude": venue.latitude,
                "longitude": venue.longitude,
                "start": venue.start.isoformat(),
                "end": venue.end.isoformat() if venue.end else None,
                "period_basis": (
                    "Thông báo Vietlott xác nhận đây là địa điểm ngay trước khi chuyển. "
                    "Repo tạm áp dụng ngược đến ngày đầu dataset vì chưa tìm thấy thông báo "
                    "đổi địa điểm cũ hơn."
                    if venue.venue_id == "lac_trung"
                    else "Ngày bắt đầu theo thông báo thay đổi địa điểm của Vietlott."
                ),
            }
            for venue in VENUES
        ],
        "limitations": [
            "Dữ liệu là tái phân tích thời tiết ngoài trời, không phải đo trong phòng quay.",
            "Giá trị theo ngày không phản ánh chính xác điều kiện tại phút quay.",
            "Không có metadata mã máy, bộ bi, bảo trì, điều hòa hoặc luồng khí trong phòng.",
            "Phiên bản đầu chỉ dùng nhiệt độ và độ ẩm từ cùng mô hình ERA5-Land.",
            "Giai đoạn Lạc Trung trước năm 2025 là giả định liên tục cần sửa nếu tìm thấy nguồn cũ hơn.",
        ],
    }
    _write_json(metadata_path, metadata)
    return {
        "rows": len(merged),
        "fetched_rows": len(fetched),
        "first_date": metadata["first_date"],
        "latest_date": metadata["latest_date"],
        "csv_path": str(csv_path),
    }


def _fetch_venue_range(
    session: requests.Session,
    venue: VenuePeriod,
    start: date,
    end: date,
    *,
    retries: int,
    request_delay: float,
) -> dict[str, dict[str, object]]:
    params = {
        "latitude": venue.latitude,
        "longitude": venue.longitude,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "daily": ",".join(DAILY_VARIABLES),
        "timezone": WEATHER_TIMEZONE,
        "models": "era5_land",
        "cell_selection": "land",
    }
    payload: dict[str, object] | None = None
    for attempt in range(1, retries + 1):
        try:
            response = session.get(ARCHIVE_URL, params=params, timeout=60)
            response.raise_for_status()
            payload = response.json()
            break
        except (requests.RequestException, ValueError):
            if attempt == retries:
                raise
            sleep_for = request_delay * (2 ** (attempt - 1))
            LOGGER.warning(
                "Weather request failed for %s, retrying in %.1fs",
                venue.venue_id,
                sleep_for,
            )
            time.sleep(sleep_for)
    if payload is None:
        raise RuntimeError(f"No weather payload returned for {venue.venue_id}")

    daily = payload.get("daily")
    if not isinstance(daily, dict) or not isinstance(daily.get("time"), list):
        raise ValueError(f"Invalid weather payload for {venue.venue_id}")
    times = daily["time"]
    rows: dict[str, dict[str, object]] = {}
    for index, day in enumerate(times):
        row: dict[str, object] = {
            "date": str(day),
            "venue_id": venue.venue_id,
            "venue_name": venue.name,
            "address": venue.address,
            "requested_latitude": venue.latitude,
            "requested_longitude": venue.longitude,
            "grid_latitude": payload.get("latitude"),
            "grid_longitude": payload.get("longitude"),
            "weather_model": "ERA5-Land",
            "source": "open-meteo",
        }
        for variable in DAILY_VARIABLES:
            values = daily.get(variable)
            if not isinstance(values, list) or index >= len(values):
                raise ValueError(f"Missing {variable} for {day}")
            row[variable] = values[index]
        if all(row[variable] is not None for variable in DAILY_VARIABLES):
            rows[str(day)] = row
    if request_delay:
        time.sleep(request_delay)
    return rows


def _read_existing(path: Path) -> dict[str, dict[str, object]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        return {row["date"]: dict(row) for row in csv.DictReader(handle)}


def _write_csv(path: Path, rows: dict[str, dict[str, object]]) -> None:
    temp_path = path.with_suffix(".csv.tmp")
    with temp_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for key in sorted(rows):
            writer.writerow(rows[key])
    temp_path.replace(path)


def _write_json(path: Path, value: object) -> None:
    temp_path = path.with_suffix(".json.tmp")
    temp_path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def _date_range(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _weather_today() -> date:
    return datetime.now(ZoneInfo(WEATHER_TIMEZONE)).date()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="vietlott-weather-update",
        description="Update the reproducible daily weather dataset for known Vietlott venues.",
    )
    parser.add_argument("--output-dir", type=Path, default=Path("datasets/weather"))
    parser.add_argument("--start-date", type=date.fromisoformat, default=VENUES[0].start)
    parser.add_argument("--end-date", type=date.fromisoformat)
    parser.add_argument("--refresh-days", type=int, default=14)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--request-delay", type=float, default=0.8)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    report = update_weather_dataset(
        args.output_dir,
        start=args.start_date,
        end=args.end_date,
        refresh_days=args.refresh_days,
        retries=args.retries,
        request_delay=args.request_delay,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
