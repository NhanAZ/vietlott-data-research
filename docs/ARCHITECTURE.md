# Kiến trúc chương trình

## Luồng dữ liệu

```text
GitHub Actions hoặc CLI
 |
 v
OfficialVietlottSource
 |
 |-- GET trang kết quả hiện tại
 |-- POST AjaxPro cho các trang tiếp theo
 `-- GET trang chi tiết khi cần giải thưởng
 |
 v
Parser theo họ sản phẩm
 |
 v
Validation và chuẩn hóa
 |
 v
SQLite working store
 |
 |-- draws.csv
 |-- prizes.csv
 `-- prize_rules.csv
 |
 v
Repository data publisher
 |
 `-- datasets phân vùng theo sản phẩm và tháng
```

## Thành phần

`config.py` định nghĩa sản phẩm, miền số, số lượng kết quả và endpoint.

`http.py` quản lý session, retry, backoff, `Retry-After`, rate limit và jitter.

`sources/vietlott.py` giao tiếp với trang chính thức. Khóa AjaxPro động được đọc
từ HTML thay vì lưu cứng.

`parsers` chuyển từng họ HTML thành `DrawRecord` và `PrizeRecord`.

`validation.py` kiểm tra số lượng phần tử, miền giá trị, trùng số và cấu trúc giải.

`storage.py` cung cấp kho CSV nhỏ và SQLite cho lịch sử lớn. Upsert dùng khóa ổn
định, giao dịch SQLite và xuất CSV nguyên tử.

`repository_data.py` chia CSV lớn thành phân vùng nhỏ hơn giới hạn tệp GitHub,
ghép lại khi chạy workflow và kiểm tra toàn vẹn.

`incremental_update.py` đọc kỳ mới, đối chiếu lại các trang gần nhất, áp dụng danh
sách ngoại lệ chính thức, xuất dữ liệu và báo cáo kiểm toán.

## Khóa dữ liệu

- Draw dùng `(product, draw_id)`
- Prize dùng `(product, draw_id, game_variant, prize_tier, winning_rule, prize_value_vnd)`

## Nguyên tắc cập nhật

- Nguồn dữ liệu quyết định kỳ nào tồn tại
- Lịch chỉ quyết định thời điểm thăm dò
- Không suy mã kỳ kế tiếp để tạo bản ghi
- Mỗi lần chạy có thể bắt kịp nhiều trang
- Bản ghi trùng được upsert
- Bản ghi bị rút xác nhận không bị xóa
- Workflow không commit nếu dữ liệu không đổi
- Mọi tệp được kiểm tra trước khi push

## Mở rộng sản phẩm

Thêm `ProductSpec` trong `config.py`. Nếu HTML thuộc họ đã hỗ trợ thì dùng lại
parser hiện có. Nếu cấu trúc khác, thêm parser và fixture riêng. Tầng lưu trữ không
cần thay đổi nếu mô hình `DrawRecord` và `PrizeRecord` vẫn đáp ứng được.
