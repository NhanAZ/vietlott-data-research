# Registry hiệu chỉnh nhiều phép thử của backtest

Tài liệu này khóa cách đọc `backtest.multiple_testing_trials` trong từng báo
cáo sản phẩm. Mục tiêu là không chỉ hiệu chỉnh trên các mô hình cuối được công
bố, mà còn tính cả các biến thể tham số đã đăng ký/thử trong cùng họ backtest.

## Phạm vi trial

Mỗi report complete có `multiple_testing_trials` gồm:

- `method = benjamini_hochberg_over_published_and_registered_trials`.
- `scope_policy = published_final_models_plus_registered_parameter_variants`.
- `trial_count`: tổng số trial đưa vào hiệu chỉnh cho sản phẩm.
- `published_trial_count`: số trial là mô hình cuối đang hiển thị trên website.
- `registered_parameter_variant_count`: số biến thể tham số/shadow trial đã thử
  nhưng không công bố như mô hình chính.
- `trials`: từng trial với `trial_id`, `strategy`, `variant_role`,
  `approximate_p_value`, thước đo chênh lệch, khoảng ước lượng và tham số.

Với registry hiện tại, mỗi sản phẩm complete có 13 trial: 3 trial công bố,
4 shadow trial tham số cũ và 6 trial cửa sổ phụ từ `backtest.window_sensitivity`.
Các cửa sổ phụ này là một phần của `registered_parameter_variant_count`.

Các trial có `published = true` trỏ về `published_comparison_key` tương ứng:
`comparison`, `recent_comparison` hoặc `audit_comparison`.

## Quy tắc q-value

`finalize_backtests` gom mọi `trials` của mọi sản phẩm complete, chạy
Benjamini-Hochberg trên toàn bộ p-value trong registry, rồi copy q-value về
các comparison công bố. Vì vậy:

- `manifest.backtest_summary.comparison_count` vẫn là số comparison công bố.
- `manifest.backtest_summary.correction_trial_count` là số trial thật sự dùng
  để hiệu chỉnh.
- `comparison.multiple_testing_scope` phải bằng `correction_trial_count`.
- Chỉ ghi `beats_baseline = true` khi chênh lệch dương và
  `q_value_global_bh < 0.05`.

## Kiểm soát tự động

`finalize_backtests` validate `multiple_testing_trials` trước khi hiệu chỉnh.
Nếu thiếu registry, thiếu p-value, trial lệch `target_scope`, hoặc trial công
bố không khớp p-value với comparison tương ứng, lệnh tạo báo cáo sẽ dừng bằng
`ValueError`.

`manifest.backtest_summary.multiple_testing_registry_validation` công bố trạng
thái validate toàn hệ thống, gồm số comparison công bố và số trial correction.

Các trial không thắng sau hiệu chỉnh và cấu hình bị loại trước phase đánh giá
cuối được lưu riêng trong `backtest.trial_disposition_log`. Trường này không đổi
q-value, nhưng giữ dấu vết những thử nghiệm âm và lý do loại bỏ cấu hình.
