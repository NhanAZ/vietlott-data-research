# Nguồn và quy trình thu thập

Ngày rà soát gần nhất là 14/06/2026.

## Nguồn chính thức

Nguồn chuẩn là trang kết quả công khai của Vietlott.

- [Mega 6/45](https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/winning-number-645)
- [Power 6/55](https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/winning-number-655)
- [Lotto 5/35](https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/winning-number-535)
- [Max 3D](https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/winning-number-max-3D)
- [Max 3D Pro](https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/winning-number-max-3Dpro)
- [Max 4D](https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/winning-number-max-4d)
- [Keno](https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/winning-number-keno)
- [Bingo18](https://vietlott.vn/vi/trung-thuong/ket-qua-trung-thuong/winning-number-bingo18)

Trang đầu chứa các kỳ gần nhất. Trang cũ được tải qua AjaxPro
`ServerSideDrawResult`. Mã nguồn tự đọc khóa động và tổng số dòng từ HTML.
Trang chi tiết được dùng cho giải thưởng và liên kết biên bản PDF khi có.

## Nguồn hỗ trợ lịch sử

Giao diện chính thức hiện không phân trang toàn bộ lịch sử Keno. Việc xây dựng
lịch sử đầu tiên đã dùng thêm nguồn công khai theo ngày từ `xoso.com.vn`. Các
khoảng trống còn lại chỉ được điền khi `ketquaday.vn` và `onbit.vn` cùng khớp
ngày quay và đủ 20 số.

Các nguồn phụ chỉ dùng cho lịch sử cũ và lưu dấu nguồn trong `attributes_json`.
Workflow hằng ngày chỉ truy cập Vietlott.

Quy tắc đối chiếu Keno

1. Giữ bản ghi Vietlott khi đã có.
2. So sánh mọi vùng giao nhau trước khi chèn dữ liệu phụ.
3. Chỉ chèn bản ghi khoảng trống khi cấu trúc hợp lệ.
4. Với khoảng trống mã kỳ, yêu cầu hai nguồn độc lập cùng xác nhận.
5. Không nội suy kết quả từ mã kỳ trước và sau.

Kết quả kiểm toán lịch sử Keno

- 284.594 bản ghi từ `0000001` đến `0284669`
- 75 mã kỳ được xác nhận không phát hành
- 74 mã từ `0032987` đến `0033060`
- mã `0115204`
- không còn mã chưa giải quyết trong phạm vi trên

## Ngoại lệ chính thức

Thông báo Vietlott ngày 12/05/2026 nêu rằng một số kết quả đã phát hành ngày
02/04/2026 không được Hội đồng giám sát xổ số và đơn vị kiểm toán độc lập xác nhận.

- Keno từ `0275986` đến `0276016`
- Bingo18 từ `0160137` đến `0160168`

Nguồn
[Thông báo xử lý](https://vietlott.vn/vi/tin-tuc/20321-thong-bao-vv-xu-ly-ve-san-pham-keno-bingo-18-da-phat-hanh-ngay-02042026/)

Repo giữ các kết quả còn thu thập được để phục vụ kiểm toán nguồn nhưng đặt
`draw_status=not_confirmed` và `prize_status=not_applicable`. Hai mã Bingo18 cuối
không có trong lịch sử đã thu thập vẫn được liệt kê trong `datasets/exclusions.csv`.

## Chuẩn hóa

Bảng `draws` lưu mã sản phẩm, mã kỳ có số 0 đầu, ngày ISO, trạng thái kỳ, kết quả
JSON, thuộc tính, URL nguồn, trạng thái giải thưởng và thời điểm thu thập UTC.

Bảng `prizes` lưu từng hạng giải, biến thể trò chơi, quy tắc trúng, số người trúng,
giá trị giải và ô gốc trong `details_json`.

Kiểm tra tự động gồm

- khóa trùng
- trường bắt buộc
- JSON hợp lệ
- số lượng và miền giá trị
- tính duy nhất khi luật yêu cầu
- giải thưởng mồ côi
- ngày không hợp lệ
- trạng thái kỳ hợp lệ
- kích thước tệp phù hợp GitHub

## Lỗi đã gặp

- HTML tiếng Việt có nhiều biến thể và tên class thay đổi
- AjaxPro dùng khóa động
- `TotalRow` của Keno không phản ánh toàn bộ lịch sử phát hành
- một số nguồn phụ thiếu ngày hoặc thiếu từng mã kỳ
- hai nguồn từng mâu thuẫn tại một số điểm và không được dùng nếu chưa có nguồn thứ ba
- trang có thể trả HTTP 429, 5xx hoặc nội dung chưa hoàn thiện
- kết quả từng được công bố nhưng sau đó không được xác nhận

Các lỗi mạng được retry với backoff và jitter. Lỗi parser làm workflow báo lỗi,
không tự biến HTML lạ thành dữ liệu.

## Pháp lý và nguồn gốc

Điều 15 Luật Sở hữu trí tuệ liệt kê tin tức thời sự thuần túy đưa tin, quy trình,
hệ thống, phương pháp hoạt động, khái niệm, nguyên lý và số liệu trong nhóm không
thuộc phạm vi bảo hộ quyền tác giả. Có thể tra cứu văn bản tại
[Cơ sở dữ liệu văn bản pháp luật](https://vbpl.vn/bogiaoducdaotao/Pages/vbpq-toanvan.aspx?ItemID=16748).

Điều này không đồng nghĩa mọi cách thu thập hoặc tái sử dụng đều mặc nhiên được
phép. Tuyển tập, nội dung bài viết, video, nhãn hiệu, điều khoản website và quyền
truy cập vẫn có thể chịu quy định riêng. Repo chỉ lưu dữ kiện cần cho nghiên cứu,
ghi nguồn, giới hạn tần suất và không sao chép giao diện hay nội dung biên tập.

Phần này chỉ mô tả cách dự án vận hành, không phải tư vấn pháp lý.
