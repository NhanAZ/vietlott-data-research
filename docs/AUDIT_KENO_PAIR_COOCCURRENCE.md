# Đồng xuất hiện cặp số Keno

`number_pair_co_occurrence` kiểm tra mạng cặp số trong các sản phẩm chọn tập số.
Trước `AUDIT-014`, test này bị bỏ qua với Keno vì tổng số quan sát cặp vượt ngưỡng
workflow cũ. Keno có rất nhiều kỳ quay, nhưng không gian cặp chỉ gồm
`C(80, 2) = 3.160` cặp, nên có thể đếm đầy đủ mà không cần lấy mẫu.

## Phương pháp đếm

Fairness audit dùng `dense_pair_index_vector`:

- tạo một vector đếm có độ dài bằng toàn bộ không gian cặp hợp lệ;
- mỗi cặp `(a, b)` với `a < b` được ánh xạ vào một chỉ số ổn định;
- duyệt toàn bộ lịch sử đã xác nhận và cộng mọi cặp trong từng kỳ;
- tính chi-square trên đủ mọi cặp, bao gồm cả cặp có số lần xuất hiện bằng 0 nếu có.

Phương pháp này không lấy mẫu. Với Keno, `pair_observations` hiện ở mức hơn 54 triệu
nhưng vector chỉ có 3.160 ô, nên bộ nhớ ổn định và workflow vẫn tái lập được.

## Trường JSON

Trong `parameters` của `number_pair_co_occurrence` có các trường:

- `counting_method`: `dense_pair_index_vector`.
- `no_sampling`: `true`, xác nhận không dùng lấy mẫu tùy tiện.
- `pairs` và `pair_space`: số cặp hợp lệ trong không gian sản phẩm.
- `pair_observations`: số quan sát cặp kỳ vọng từ số kỳ và số bóng mỗi kỳ.
- `observed_pair_observations`: số quan sát cặp thực sự đã đếm sau khi lọc miền hợp lệ.
- `expected_count_per_pair`: kỳ vọng nền cho mỗi cặp nếu mọi cặp đều như nhau dài hạn.
- `highest_count_pair`, `highest_count`, `highest_count_ratio_to_expected`: cặp xuất hiện
  nhiều nhất và tỷ lệ so với kỳ vọng.
- `top_pairs`: tối đa năm cặp có số lần xuất hiện cao nhất để kiểm tra nhanh.

## Cách đọc

P-value và q-value của test chính vẫn đến từ chi-square toàn bộ không gian cặp.
`top_pairs` chỉ là mô tả hậu kiểm, không tạo thêm p-value và không được đọc như
một bộ kiểm định riêng. Vì các cặp trong cùng kỳ không độc lập hoàn toàn, kết quả
đồng xuất hiện chỉ là tín hiệu cần đọc cùng các kiểm định khác, không phải kết luận
vận hành.
