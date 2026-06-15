from __future__ import annotations

import json
from pathlib import Path

from .catalog import PRODUCT_ORDER, PRODUCTS
from .fairness import (
    audit_log_events,
    build_product_audit,
    dump_jsonl,
    finalize_audits,
)
from .io import load_prize_summary, load_product_dataset
from .predictions import PredictionLedger, build_backtest_report
from .statistics import build_product_report
from .weather_analysis import build_weather_report, load_weather_days


def build_research_site(
    datasets_dir: Path = Path("datasets"),
    site_dir: Path = Path("site"),
    prediction_ledger_path: Path = Path("predictions/ledger.jsonl"),
) -> dict[str, object]:
    datasets_dir = datasets_dir.resolve()
    site_dir = site_dir.resolve()
    product_data_dir = site_dir / "data" / "products"
    product_data_dir.mkdir(parents=True, exist_ok=True)
    ledger = PredictionLedger.load(prediction_ledger_path.resolve())
    weather_days = load_weather_days(datasets_dir)
    product_summaries: list[dict[str, object]] = []
    product_reports: list[dict[str, object]] = []

    for slug in PRODUCT_ORDER:
        product = PRODUCTS[slug]
        dataset = load_product_dataset(datasets_dir, product)
        prize_summary = load_prize_summary(datasets_dir, product)
        report = build_product_report(dataset, prize_summary)
        report["weather"] = build_weather_report(dataset, weather_days)
        report["backtest"] = build_backtest_report(dataset)
        report["audit"] = build_product_audit(dataset)
        product_reports.append(report)
        ledger.process_product(dataset)
        summary = report["summary"]
        product_summaries.append(
            {
                "slug": slug,
                "name": product.name,
                "short_name": product.short_name,
                "kind": product.kind.value,
                "active": product.active,
                "confirmed_draws": summary["confirmed_draws"],
                "not_confirmed_draws": summary["not_confirmed_draws"],
                "first_date": summary["first_date"],
                "latest_date": summary["latest_date"],
                "latest_draw_id": summary["latest_draw_id"],
            }
        )

    audit_summary = finalize_audits(product_reports)
    for report in product_reports:
        _write_json(product_data_dir / f"{report['product']['slug']}.json", report)
    _write_json(site_dir / "data" / "audit-summary.json", audit_summary)
    audit_events = list(audit_log_events(product_reports))
    _write_jsonl(site_dir / "data" / "audit-log.jsonl", audit_events)

    ledger.save()
    prediction_report = ledger.site_report()
    _write_json(site_dir / "data" / "predictions.json", prediction_report)

    source_summary_path = datasets_dir / "metadata" / "dataset-summary.json"
    source_summary = json.loads(source_summary_path.read_text(encoding="utf-8"))
    manifest = {
        "schema_version": 1,
        "title": "Vietlott Data Research",
        "generated_from_dataset_at": source_summary.get("dataset_updated_at"),
        "draw_rows": source_summary["draw_rows"],
        "confirmed_rows": source_summary["confirmed_rows"],
        "not_confirmed_rows": source_summary["not_confirmed_rows"],
        "prize_rows": source_summary["prize_rows"],
        "products": product_summaries,
        "prediction_evaluations": prediction_report["evaluation_count"],
        "prediction_pending": prediction_report["pending_count"],
        "fairness_audit": audit_summary["summary"],
        "methodology_version": "1.0.0",
        "analysis_export": {
            "path": "data/analysis-export.json",
            "schema_version": 1,
            "description": (
                "Gói JSON tự mô tả chứa toàn bộ dữ liệu dẫn xuất quan trọng đang dùng "
                "trên website để phục vụ tái phân tích bằng phần mềm hoặc AI."
            ),
        },
    }
    analysis_export = _build_analysis_export(
        manifest=manifest,
        source_summary=source_summary,
        product_reports=product_reports,
        prediction_report=prediction_report,
        audit_summary=audit_summary,
        audit_events=audit_events,
    )
    _write_json(site_dir / "data" / "analysis-export.json", analysis_export)
    _write_json(site_dir / "data" / "manifest.json", manifest)
    return manifest


def _build_analysis_export(
    *,
    manifest: dict[str, object],
    source_summary: dict[str, object],
    product_reports: list[dict[str, object]],
    prediction_report: dict[str, object],
    audit_summary: dict[str, object],
    audit_events: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "export_type": "vietlott_research_analysis",
        "language": "vi",
        "generated_from_dataset_at": manifest["generated_from_dataset_at"],
        "purpose": (
            "Một điểm vào duy nhất cho phân tích dữ liệu, kiểm tra phương pháp, "
            "đối chiếu backtest và đọc sổ dự đoán. Không phải khuyến nghị mua vé."
        ),
        "manifest": manifest,
        "dataset_summary": source_summary,
        "data_dictionary": {
            "product_reports": (
                "Báo cáo đầy đủ theo sản phẩm gồm thống kê mô tả, tần suất, độ vắng, "
                "mùa vụ, thời tiết, giải thưởng, backtest và kiểm định công bằng."
            ),
            "predictions": (
                "Sổ dự đoán đã lưu trước, kết quả đối chiếu, trạng thái đúng, gần đúng, "
                "sai và các chỉ số trùng một phần."
            ),
            "audit_summary": (
                "Kết quả tổng hợp của bộ kiểm định công bằng thống kê sau hiệu chỉnh "
                "nhiều phép thử trong từng bộ kiểm định."
            ),
            "audit_events": (
                "Nhật ký phẳng của từng phép kiểm để lọc theo sản phẩm, phương pháp, "
                "trạng thái, p-value, q-value và kích thước hiệu ứng."
            ),
            "backtest": (
                "Walk-forward theo thời gian. Mỗi kỳ chỉ dùng lịch sử trước kỳ đó và "
                "so sánh ghép cặp với baseline chọn đồng đều có seed."
            ),
            "raw_draws": (
                "Dữ liệu kỳ quay gốc không nhúng vào gói này vì có hàng trăm nghìn dòng. "
                "Dùng danh mục source_files để tải CSV phân vùng khi cần phân tích cấp kỳ."
            ),
        },
        "methodology": {
            "backtest": {
                "method": "walk_forward",
                "candidate_strategies": ["balanced_signal", "audit_signal"],
                "baseline": "uniform_seeded",
                "win_rule": "mean_paired_difference > 0 and approximate_two_sided_p < 0.05",
                "important_limitations": [
                    "Ngưỡng thắng chưa hiệu chỉnh đồng thời giữa nhiều sản phẩm và chiến lược.",
                    "Điểm backtest tập số hiện chỉ tính số chính, chưa tính số đặc biệt.",
                    "Tần suất cửa sổ gần có trong sổ dự đoán nhưng chưa nằm trong báo cáo backtest.",
                    "Backtest quá khứ không thay thế dự đoán đã đóng băng trước kỳ quay.",
                ],
            },
            "fairness_audit": {
                "suite_version": audit_summary["suite_version"],
                "multiple_testing": "Benjamini-Hochberg trong bộ kiểm định được công bố",
                "interpretation": (
                    "Tín hiệu thống kê chỉ cho biết dữ liệu cần theo dõi hoặc đọc kỹ hơn; "
                    "không tự chứng minh nguyên nhân vận hành hay gian lận."
                ),
            },
        },
        "source_files": {
            "draws": "https://github.com/NhanAZ/vietlott-data-research/tree/main/datasets/draws",
            "prizes": "https://github.com/NhanAZ/vietlott-data-research/tree/main/datasets/prizes",
            "weather": (
                "https://github.com/NhanAZ/vietlott-data-research/blob/main/"
                "datasets/weather/daily.csv"
            ),
            "prediction_ledger": (
                "https://github.com/NhanAZ/vietlott-data-research/blob/main/"
                "predictions/ledger.jsonl"
            ),
            "implementation": (
                "https://github.com/NhanAZ/vietlott-data-research/tree/main/"
                "src/vietlott_analytics"
            ),
        },
        "product_reports": {
            str(report["product"]["slug"]): report for report in product_reports
        },
        "predictions": prediction_report,
        "audit_summary": audit_summary,
        "audit_events": audit_events,
    }


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def _write_jsonl(path: Path, events: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(dump_jsonl(events), encoding="utf-8")
    temp_path.replace(path)
