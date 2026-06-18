# Phân rã kiểm định theo nguồn dữ liệu

Tài liệu này khóa cách đọc `source_breakdown` trong tham số của phép kiểm
`digit_position_chi_square`. Mục tiêu là xem tín hiệu vị trí chữ số có tập trung
ở một nguồn, parser hoặc mirror cụ thể hay không.

## Phạm vi áp dụng

`source_breakdown` áp dụng cho các sản phẩm chuỗi chữ số khi observation có thông
tin nguồn từ `attributes_json.data_source`, hoặc fallback theo host trong
`source_url` nếu dữ liệu cũ chưa gắn `data_source`.

Các nhóm nguồn hiện có thể gồm:

- `official_vietlott`: nguồn chính thức Vietlott.
- `community_mirror`: dữ liệu mirror cộng đồng.
- `xosominhngoc_net_vn`: nguồn phụ Xổ số Minh Ngọc.
- `vietlott_vn`: host Vietlott nhưng dòng cũ chưa gắn `data_source`.
- `unknown`: không đủ metadata nguồn.

## Cách đọc

Mỗi dòng trong `sources` có:

- `source_key`, `source_label`: mã và nhãn nguồn.
- `draws`: số kỳ thuộc nguồn đó.
- `outcomes`: số chuỗi đầy đủ dùng được trong nguồn đó.
- `source_hosts`, `source_origins`, `source_verification`: bảng đếm provenance.
- `sample_status`: `usable` khi nguồn có tối thiểu 30 kỳ; `too_small` khi mẫu quá nhỏ.
- `expected_per_position_digit`: kỳ vọng mỗi chữ số ở mỗi vị trí nếu phân bố đều.
- `chi_square_contribution`: đóng góp mô tả trong riêng nguồn đó.
- `effect_size`: độ lệch chuẩn hóa trong riêng nguồn đó.
- `max_abs_standardized_residual`: residual tuyệt đối lớn nhất.
- `top_residuals`: các ô vị trí và chữ số nổi bật nhất để rà nhanh.

`source_breakdown.no_new_p_values` luôn là `true`. Bảng này chỉ giúp rà xem tín
hiệu tổng có thể đến từ parser, mirror hoặc vùng dữ liệu cũ hay không. Nó không
tạo thêm p-value riêng cho từng nguồn.

## Trạng thái đối chứng

- `available`: có ít nhất hai nguồn đủ mẫu để đọc song song.
- `limited_comparison`: có nhiều nguồn nhưng chỉ một nguồn đủ mẫu; nguồn nhỏ chỉ
  dùng để rà parser hoặc dữ liệu nguồn.
- `single_source`: chỉ có một nguồn có outcome dùng được.
- `missing_source_metadata`: không có outcome hoặc metadata đủ để phân nhóm.

Nếu tín hiệu chỉ xuất hiện ở một nguồn nhỏ hoặc nguồn chưa xác minh, ưu tiên kiểm
tra parser, mapping hạng giải và dòng `source_url` trước khi diễn giải thống kê.
Nếu tín hiệu cũng xuất hiện trên nguồn chính thức đủ mẫu, đó vẫn chỉ là bằng
chứng mô tả và cần giao thức tái kiểm tra đã khóa trước hoặc mẫu tương lai độc lập.
