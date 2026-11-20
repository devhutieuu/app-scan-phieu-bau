# Kiểm phiếu: 1 máy Mac + nhiều điện thoại

Chỉ cần **1 máy Mac** làm máy chủ. Máy Mac đọc STT, giữ kho phiếu chung, xem kết quả và xuất Excel. Mỗi bàn quét là **một điện thoại mở trình duyệt**, không cần cài app. Điện thoại chụp phiếu, xem kết quả đọc rồi bấm **Chấp nhận** hoặc **Không hợp lệ**. Phiếu đã chấp nhận hiện ngay trên máy Mac và mọi điện thoại khác.

Máy tính khác (Windows hoặc Mac) mở cùng địa chỉ thì được trang đầy đủ như máy Mac: duyệt, sửa, xem kết quả.

## Chuẩn bị (làm 1 lần, trước ngày bầu)

1. **Mạng:** một router hoặc bộ phát Wi-Fi riêng trong phòng, không cần Internet. Mọi máy nối vào đó. Nên đặt IP cố định cho máy Mac trên router.
2. **Chứng chỉ:** trên Mac chạy `bash tools/make_cert.sh` (đổi IP thì chạy lại). Lệnh in ra địa chỉ, ví dụ `https://192.168.1.238:8443/`. Trình duyệt chỉ cho dùng camera khi trang chạy qua https, nên bước này bắt buộc.
3. **Cài chứng chỉ `config/kiem-phieu-cert.crt` lên từng máy quét** (gửi file qua AirDrop, Zalo hoặc USB):
   - **iPhone:** mở file, vào Cài đặt, chọn "Đã tải về hồ sơ" rồi Cài đặt. Sau đó vào Cài đặt chung → Giới thiệu → Cài đặt tin cậy chứng nhận và bật cho "Kiem phieu".
   - **Android:** Cài đặt → Bảo mật → Mã hóa và thông tin xác thực → Cài đặt chứng chỉ → Chứng chỉ CA, rồi chọn file. Tên mục có thể khác tùy hãng máy.
   - **Windows:** bấm đúp vào file, chọn Install Certificate → Local Machine → "Place all certificates in the following store" → Trusted Root Certification Authorities → Finish.
4. Trên mỗi điện thoại, mở địa chỉ ở bước 2 (trang dành cho điện thoại tự mở), cho phép dùng camera, đặt **tên máy** (ĐT 1, ĐT 2...), rồi thêm trang vào màn hình chính.

## Ngày bầu

1. Trên Mac chạy `bash tools/start_prototype.sh`.
2. Thư ký nhập thiết lập phiên và danh sách ứng viên trên **máy Mac** (mục Thiết lập). Các điện thoại tự nhận theo.
3. Mỗi điện thoại mở trang. Thanh trên cùng phải hiện "**Đã nối máy chủ**". Nếu hiện chữ đỏ "MẤT KẾT NỐI máy chủ" thì kiểm tra Wi-Fi.
4. Quét từng phiếu:
   - **Chụp:** đưa trọn tờ phiếu (thấy đủ 4 ô vuông ở góc) vào khung, giữ yên máy rồi bấm Chụp.
   - So họ tên viết tay (ảnh từng dòng) với tên máy đọc được.
   - Bấm **Chấp nhận** hoặc **Không hợp lệ**. Ô số tô vàng là chỗ máy đọc không chắc; nếu máy đọc sai số thì bấm **Quét lại**.
5. **Chia xấp phiếu cố định cho từng điện thoại.** Cuối buổi, đối chiếu số tờ của từng xấp với số phiếu của máy đó (cột Bàn trong Danh sách phiếu trên Mac).
6. Nên cắm sạc cho điện thoại khi quét. Trang tự giữ màn hình sáng trong lúc mở.

## Khi gặp cảnh báo "phiếu giống hệt"

Máy chủ so nét chữ của phiếu vừa quét với mọi phiếu đã ghi nhận ở mọi máy. Nếu thấy giống hệt, trang hiện cảnh báo ở đầu phiếu và khóa nút Chấp nhận:

- Đúng là một tờ bị quét hai lần: bấm **Bỏ, phiếu trùng** và cất tờ đó riêng.
- Là hai tờ khác nhau: bấm **Không trùng** rồi xử lý bình thường.

Phiếu trắng không được so, vì tờ trắng nào cũng giống nhau.

## Lưu ý

- Phiếu đã ghi nhận lưu trên Mac ở `out/session/state.json`. Tắt hoặc bật lại máy chủ không mất phiếu. Lệnh "Xóa dữ liệu phiên" vẫn giữ một bản sao `state-xoa-*.json` cạnh file đó.
- Mất Wi-Fi đúng lúc bấm Chấp nhận: phiếu được lưu tạm trên điện thoại ("chưa gửi N" ở thanh trên) và tự gửi khi nối lại.
- Phiếu đang xem dở mà tải lại trang thì mất phiếu đó. Khi đó quét lại tờ đó; mã phiếu cũ bị bỏ trống, không ảnh hưởng kết quả.
- Điện thoại không sửa số được. Phiếu đã ghi nhận cần sửa thì mở lại trên máy Mac (Danh sách phiếu → Mở lại để sửa). Hai máy cùng sửa một phiếu thì máy lưu trước được ghi; máy sau nhận thông báo, không ghi đè.
- Đo thử ngày 07/11/2026 trên MacBook M1 Pro, 5 máy gửi liên tục: đọc một phiếu khoảng 26 ms, mỗi máy chờ kết quả không quá 0,2 giây.
- Muốn đo lại trước ngày bầu (chỉ chạy vào máy chủ thử, không chạy vào phiên thật): xem cách chạy ở đầu file `tools/load_test.py`.
