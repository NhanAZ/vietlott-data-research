# Kiểm tra độ nhạy cửa sổ gần của backtest

Tài liệu này khóa cách đọc `backtest.window_sensitivity` trong từng báo cáo
sản phẩm. Mục tiêu là kiểm tra liệu kết luận backtest có phụ thuộc quá mạnh vào
độ dài cửa sổ tần suất gần hay không.

## Cấu trúc dữ liệu

Mỗi report complete có `window_sensitivity` gồm:

- `method = registered_recent_window_sensitivity`.
- `sensitivity_dimension = recent_window_draws`.
- `registered_window_draws = [50, 200, 500]`.
- `primary_recent_window_draws`: cửa sổ mặc định của report.
- `trial_count`: số dòng trong ma trận chiến lược x cửa sổ.
- `primary_trial_count`: số trial công bố dùng cửa sổ mặc định.
- `alternative_window_trial_count`: số trial cửa sổ phụ.
- `trials`: các dòng trial chi tiết.

Mỗi dòng trong `trials` dùng cùng `target_scope_id` và `target_draw_count` với
phase đánh giá cuối. Ba chiến lược được kiểm tra là:

- `balanced_signal`.
- `recent_frequency`.
- `audit_signal`.

## Vai trò trong registry

Cửa sổ mặc định vẫn là trial công bố và có
`window_sensitivity_role = primary_published_window`. Các cửa sổ còn lại có
`window_sensitivity_role = registered_alternative_window`,
`variant_role = registered_parameter_variant` và được đưa vào
`multiple_testing_trials`.

Vì vậy `window_sensitivity.trials` có 9 dòng, còn `multiple_testing_trials` có
thêm 6 trial cửa sổ phụ ngoài 3 model công bố và 4 shadow trial đã đăng ký từ
trước.

## Validation

`build_backtest_report` validate `window_sensitivity` trước khi trả report.
`finalize_backtests` validate field này khi report có công bố nó và ghi summary
vào `manifest.backtest_summary.window_sensitivity_validation`.

Các lỗi phải làm fail build:

- thiếu một cặp chiến lược/cửa sổ trong ma trận 50/200/500;
- trial độ nhạy không nằm trong `multiple_testing_trials`;
- dòng trial dùng sai `target_scope_id` hoặc `target_draw_count`;
- cửa sổ mặc định không khớp `primary_recent_window_draws`;
- cửa sổ phụ bị đánh dấu như trial công bố.

## Cách đọc

Đây là kiểm tra độ nhạy, không phải một kết luận thắng riêng. Kết luận chính vẫn
dựa trên comparison công bố sau hiệu chỉnh Benjamini-Hochberg toàn hệ thống.
Nếu một cửa sổ phụ có p thô đẹp nhưng không qua q toàn hệ thống thì chỉ nên đọc
như tín hiệu thăm dò.
