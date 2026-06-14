from __future__ import annotations

from datetime import date
from pathlib import Path

from vietlott_analytics.weather import update_weather_dataset


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {
            "latitude": 21.0,
            "longitude": 105.86,
            "daily": {
                "time": ["2025-01-22", "2025-01-23"],
                "temperature_2m_mean": [18.8, 19.2],
                "temperature_2m_min": [15.1, 16.1],
                "temperature_2m_max": [23.1, 23.4],
                "relative_humidity_2m_mean": [82, 83],
            },
        }


def test_weather_update_writes_csv_and_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("requests.Session.get", lambda *args, **kwargs: FakeResponse())
    monkeypatch.setattr("time.sleep", lambda _: None)

    report = update_weather_dataset(
        tmp_path,
        start=date(2025, 1, 22),
        end=date(2025, 1, 23),
        refresh_days=0,
        request_delay=0,
    )

    assert report["rows"] == 2
    assert report["latest_date"] == "2025-01-23"
    assert (tmp_path / "daily.csv").exists()
    metadata = (tmp_path / "metadata.json").read_text(encoding="utf-8")
    assert "ERA5-Land" in metadata
    assert "Tam Trinh" in metadata


def test_weather_update_never_shrinks_existing_cache(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("requests.Session.get", lambda *args, **kwargs: FakeResponse())
    monkeypatch.setattr("time.sleep", lambda _: None)
    update_weather_dataset(
        tmp_path,
        start=date(2025, 1, 22),
        end=date(2025, 1, 23),
        refresh_days=0,
        request_delay=0,
    )
    monkeypatch.setattr(
        "vietlott_analytics.weather._fetch_venue_range",
        lambda *args, **kwargs: {},
    )

    report = update_weather_dataset(
        tmp_path,
        start=date(2025, 1, 22),
        end=date(2025, 1, 22),
        refresh_days=0,
        request_delay=0,
    )

    assert report["rows"] == 2
    assert report["latest_date"] == "2025-01-23"
