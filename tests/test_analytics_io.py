import csv
import json

from vietlott_analytics.catalog import PRODUCTS
from vietlott_analytics.io import load_product_dataset


def test_load_product_dataset_attaches_observation_source_metadata(tmp_path) -> None:
    product = PRODUCTS["bingo18"]
    draw_dir = tmp_path / "draws" / product.slug
    draw_dir.mkdir(parents=True)
    attributes = {"data_source": "official_vietlott"}
    row = {
        "product": product.slug,
        "draw_id": "0000001",
        "draw_date": "2026-01-01",
        "draw_status": "confirmed",
        "result_json": json.dumps({"digits": [1, 2, 3]}),
        "attributes_json": json.dumps(attributes),
        "official_pdf_urls_json": "[]",
        "source_url": "https://vietlott.vn/example?id=0000001",
        "prize_status": "unchecked",
        "validation_status": "valid",
        "validation_warnings_json": "[]",
        "fetched_at": "2026-01-01T00:00:00+00:00",
    }
    fields = list(row)
    with draw_dir.joinpath("all.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow(row)

    dataset = load_product_dataset(tmp_path, product)
    observation = dataset.observations[0]

    assert observation.source_host == "vietlott.vn"
    assert observation.data_source == "official_vietlott"
    assert observation.source_origin == "official"
    assert observation.source_verification == "official_direct"
