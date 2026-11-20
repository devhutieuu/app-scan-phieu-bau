---
type: brainstorm
feature: ballot-scan
status: draft
updated: 2026-10-28
links:
  - handoff-app-scan-phieu-bau.md
  - DESIGN.md
  - docs/ballot-scan/html-design/ballot-scan-prototype.html
---

# Màn hình quét và duyệt phiếu bầu

## 1. Ý tưởng gốc

- Màn hình máy tính chia 2 phần, kéo dãn được: bên trái xem trực tiếp camera điện thoại đang quét, bên phải là phiếu điện tử mô phỏng lại phiếu giấy, điền sẵn STT và họ tên máy đọc được.
- Mỗi lần quét, bên phiếu điện tử có 2 nút: **Chấp nhận** hoặc **Quét lại**.
- Mỗi phiếu lưu 1 file ảnh ghép: ảnh thật một bên, phiếu điện tử một bên.
- Có nút xem danh sách phiếu đã quét.
- Đếm tổng phiếu đã quét, số phiếu hợp lệ và không hợp lệ, tính tỉ lệ % cho từng ứng viên.

## 2. Vai trò trong buổi kiểm phiếu

| Vai trò | Làm gì trên app |
|---|---|
| Người đưa phiếu | Đặt từng phiếu lên tấm nền dưới điện thoại, rút ra khi app báo đã chụp. Không chạm vào máy tính. |
| Người duyệt | Ngồi trước máy tính, so ảnh thật với phiếu điện tử, xử lý các dòng bị gắn cờ, bấm Chấp nhận / Quét lại / Không hợp lệ. |
| Thư ký / giám sát | Nhập số phiếu phát ra, theo dõi kết quả, chốt kết quả và xuất file Excel. |

Một máy tính dùng chung. Tên tổ kiểm phiếu nhập 1 lần ở đầu phiên và ghi vào mọi thao tác; không phân biệt từng người duyệt.

## 3. Hai vòng bầu và vòng đời một phiên

Hội Thánh bầu **2 vòng, cách nhau 1 tuần**. Mỗi vòng là 1 phiên kiểm phiếu riêng trên app.

| | Vòng 1 · Đề cử | Vòng 2 · Bầu chính thức |
|---|---|---|
| Danh sách trên phiếu | Khoảng 200 tín hữu đủ điều kiện | Những người trên 50% ở vòng 1 |
| Mỗi phiếu chọn | Tối đa 10 người, phiếu 10 dòng | Quy định sau |
| STT | 3 chữ số (001–200) | Theo danh sách vòng 2 |
| Kết quả | Danh sách **vào vòng 2** (không có "trúng cử") | Người trúng cử |

```
Thiết lập phiên  ->  Chạy thử  ->  Quét & duyệt  ->  Đối soát  ->  Chốt kết quả  ->  Xuất Excel
```

1. **Thiết lập**: tên cuộc bầu, loại vòng (đề cử / chính thức), danh sách ứng viên (STT + họ tên, nhập từ Excel), số người được chọn tối đa, quy tắc phiếu (Mục 6). Khi đã có phiếu đầu tiên thì khóa số dòng và danh sách ứng viên.
2. **Chạy thử**: quét 3-5 phiếu mẫu để kiểm tra ánh sáng, khoảng cách camera. Phiếu chạy thử không tính vào kết quả.
3. **Quét & duyệt**: vòng lặp chính, xem Mục 4 và 5.
4. **Đối soát**: so số phiếu phát ra với số phiếu đã ghi nhận (Mục 7).
5. **Chốt kết quả**: khóa phiên, không nhận thêm phiếu, không sửa phiếu. Mở khóa phải ghi lý do.
6. **Xuất**: file Excel gồm 3 trang (Tổng hợp / Kết quả / Danh sách phiếu) và thư mục ảnh ghép. Thư ký tự soạn biên bản từ file Excel. Vòng 1 xuất thêm **danh sách vào vòng 2** để làm danh sách ứng viên cho phiên tuần sau.

## 4. Màn hình làm việc chính

```
+------------------------------------------------------------------------------------+
| Kiểm phiếu · Bầu cử Hội Thánh · Vòng 1 · Đề cử        Đã ghi nhận 42 · Hợp lệ 40 · Không hợp lệ 2 |
|                                                       [Danh sách] [Kết quả] [Thiết lập] |
+-------------------------------+--+-------------------------------------------------+
|  CAMERA                       |::|  PHIẾU #043                                     |
|  +-------------------------+  |::|  +-------------------------------------------+  |
|  |                         |  |::|  | 1  [0 0 5]  [Hoàng Thị Thu Hà    ]   ✓     |  |
|  |   ảnh trực tiếp         |  |::|  | 2  [0 0 8]  [#Lê Văn Cường#      ]  Lệch   |  |
|  |   + khung 4 góc         |  |::|  |    [ảnh cắt dòng 2]  Máy chưa chắc chỗ tô  |  |
|  |                         |  |::|  |    vàng. So với ảnh; sai thì gõ sửa.       |  |
|  |  Giữ yên... 70%         |  |::|  | 3  [     ]  [                    ]         |  |
|  +-------------------------+  |::|  +-------------------------------------------+  |
|                 [Mô phỏng ▾]  |::|  Hợp lệ · 7 người      [Quét lại] [Phiếu hỏng] [Chấp nhận] |
+-------------------------------+--+-------------------------------------------------+
```
(`#...#` = ô tô vàng, máy chưa chắc)

**Bên trái (camera)**
- Chọn nguồn camera (iPhone qua Continuity Camera, webcam).
- Khung hướng dẫn đặt phiếu; khi thấy phiếu thì vẽ viền nối 4 góc phiếu: đủ 4 góc viền xanh, thiếu góc viền đỏ.
- Một dòng trạng thái bằng lời đời thường: *Đặt phiếu vào khung* / *Bỏ tay khỏi góc phiếu* / *Giữ yên…* / *Đã chụp xong. Mời xem bên phải*.
- Sau khi chụp, camera **khóa** cho đến khi phiếu đang duyệt được xử lý xong **và** tờ phiếu rời khung. Như vậy không bao giờ có 2 phiếu chờ duyệt cùng lúc, không chụp lặp.

**Đường chia giữa**: kéo để đổi tỉ lệ, nhấp đúp để về mặc định, app nhớ tỉ lệ lần sau.

**Bên phải (phiếu điện tử)**
- Bố cục giống phiếu giấy (10 dòng, ô STT 3 chữ số, ô họ tên) để mắt so từng dòng với ảnh bên trái.
- Dòng máy đọc chắc chắn: chỉ có dấu ✓.
- Dòng máy chưa chắc: ô nghi ngờ **tô vàng**, kèm **ảnh cắt đúng dòng đó** ngay bên dưới để so. Không có câu hỏi, không có nút riêng cho dòng.
- Người duyệt chỉ có 1 việc: làm cho phiếu điện tử **giống phiếu giấy**. Đúng rồi thì để nguyên, sai thì gõ sửa thẳng vào ô (gõ STT thì tự điền tên và ngược lại).
- Kết luận phiếu do **app tự tính** theo quy tắc trên giá trị đang có trong các ô, cập nhật ngay khi gõ, hiện nổi bật cạnh nút Chấp nhận: *Hợp lệ · 7 người* (xanh) / *Không hợp lệ · Dòng 3 thiếu họ tên* (đỏ).
- 3 hành động:
  - **Chấp nhận** (nút chính): nghĩa là "tôi đã đối chiếu, phiếu điện tử giống phiếu giấy". Luôn bấm được, kể cả khi kết luận là không hợp lệ.
  - **Quét lại**.
  - **Phiếu hỏng**: chỉ cho điều máy không tự thấy được. Bấm vào hiện 3 nút lý do *Có ký hiệu, chữ ký lạ* / *Không đúng mẫu* / *Rách, không đọc được*; bấm 1 nút là ghi nhận luôn.

## 5. Luồng xử lý 1 phiếu

```
Phiếu vào khung -> thấy đủ 4 góc + nét + đứng yên 1,5 giây -> tự chụp (bíp)
   -> cấp mã phiếu #NNN, máy đọc từng dòng, đối chiếu danh sách
   -> phiếu điện tử hiện bên phải, ô máy chưa chắc tô vàng
        |
        +-- Máy đọc sai : gõ sửa ô cho giống phiếu giấy -> kết luận tự cập nhật
        +-- Chấp nhận   : lưu kết quả + ảnh ghép, cộng vào bộ đếm
        +-- Phiếu hỏng  : chọn 1 trong 3 lý do -> ghi nhận không hợp lệ
        +-- Quét lại    : giữ nguyên mã #NNN, chụp lại, đọc lại
                -> camera mở khóa khi phiếu rời khung -> phiếu tiếp
```

Số thao tác:

| Tình huống | Thao tác |
|---|---|
| Phiếu khớp hết | 1 (Chấp nhận) |
| Có ô tô vàng, phiếu ghi đúng như máy đọc (vd lệch STT–tên thật) | 1 (Chấp nhận) |
| Có ô tô vàng, máy đọc sai | 2 (gõ sửa → Chấp nhận) |
| Phiếu có ký hiệu lạ / không đúng mẫu / rách | 2 (Phiếu hỏng → chọn lý do) |
| Ảnh mờ, che góc | 1 (Quét lại) |

Nguyên tắc chốt:
- **Người đối chiếu, app kết luận.** Người duyệt không phải trả lời "hợp lệ không" hay chọn lý do cho các quy tắc đã chốt; app tự áp quy tắc và ghi lý do.
- **Quy tắc tính theo chữ ghi trên phiếu.** Vì vậy ô nào máy đọc sai thì người phải sửa cho giống phiếu trước khi Chấp nhận; ô tô vàng và ảnh cắt đặt sát nhau để liếc mắt là so được.
- **Mã phiếu cấp lúc chụp, không bao giờ bị bỏ**: phiếu đã chụp chỉ có 2 kết cục là hợp lệ (gồm phiếu trắng) hoặc không hợp lệ. Không có nút "xóa phiếu". Nhờ vậy số thứ tự liên tục, đối soát được.
- **Quét lại không tạo phiếu mới**: chỉ thay ảnh và kết quả đọc của mã đang duyệt, đếm số lần quét lại.
- **Máy không tự chấp nhận**: kể cả phiếu khớp 100% cũng cần người bấm Chấp nhận.
- **Hoàn tác**: sau khi Chấp nhận hoặc Phiếu hỏng có vài giây để bấm Hoàn tác; không có hộp xác nhận.

### App tự áp quy tắc cho mỗi dòng

Áp trên giá trị đang có trong ô (máy đọc, hoặc người đã sửa cho giống phiếu):

| Giá trị trong dòng | App kết luận |
|---|---|
| STT và tên cùng chỉ 1 người trong danh sách | Dòng tính cho người đó (✓) |
| STT chỉ người A, tên là người B | **Dòng không hợp lệ** · "Lệch STT–tên" (gạch dòng) |
| Tên có trong danh sách, STT không có trong danh sách | **Dòng không hợp lệ** · "STT không có trong danh sách" |
| STT hợp lệ, tên không có trong danh sách | **Dòng không hợp lệ** · "Tên không có trong danh sách" |
| Có STT, ô họ tên trống | **Cả phiếu không hợp lệ** · "Dòng N thiếu họ tên" |
| Có tên, ô STT trống | **Cả phiếu không hợp lệ** · "Dòng N thiếu STT" |
| Ô có chữ nhưng máy không đọc được, người không sửa | **Dòng không hợp lệ** · "Không đọc được" |
| Dòng trống hoàn toàn | Không tính |

Muốn bỏ một dòng thì xóa trắng cả 2 ô.

Tên viết tắt hoặc thiếu chữ đệm (vd "Ngô Thiện", "Ng. Công Thiện") vẫn tính là khớp nếu **hợp với người mang STT đó**, kể cả khi danh sách có người khác tên gần giống (vd Ngô Quốc Thiện). Chỉ khi tên rõ ràng là của người khác mới kết luận "Lệch STT–tên".

"Dòng không hợp lệ" nghĩa là dòng đó không tính phiếu cho ai; lý do được ghi vào ảnh ghép. Một dòng không hợp lệ có làm cả phiếu không hợp lệ hay không: chưa quy định (OQ-8), tạm thời phiếu vẫn hợp lệ và app hiện ghi chú.

Lưu ý với vòng 1: danh sách khoảng 200 người nên dễ có tên gần giống nhau. **STT là chỗ dựa chính**, tên dùng để kiểm tra chéo.

## 6. Quy tắc phiếu hợp lệ / không hợp lệ

Phân biệt 2 cấp:
- **Cấp dòng**: một dòng sai thì chỉ dòng đó không được tính (Mục 5).
- **Cấp phiếu**: cả phiếu không được tính.

| Tình huống | Máy phát hiện được? | Quy tắc | Cấu hình |
|---|---|---|---|
| Không chọn ai (phiếu trắng) | Có | **Hợp lệ** (tạm thời), đếm riêng nhóm Phiếu trắng, có trong mẫu số | Giữ tùy chọn để đổi khi quy chế thay đổi |
| Ghi trùng 1 người ở 2 dòng | Có | **Cả phiếu không hợp lệ** | Không |
| Có dòng chỉ ghi STT hoặc chỉ ghi tên | Có | **Cả phiếu không hợp lệ** | Không |
| Chọn quá số người cho phép | Có (đếm số người khác nhau) | Cả phiếu không hợp lệ | Không |
| Dòng trống xen giữa các dòng đã điền | Có | Chỉ ghi chú, không ảnh hưởng | Không |
| Có nét viết, chữ ký, ký hiệu ngoài ô điền | Có (vùng ngoài ô có mực) | App chỉ nhắc "Có nét viết ngoài ô — xem ảnh"; là ký hiệu lạ thì người duyệt bấm **Phiếu hỏng** | Không |
| Không đúng mẫu phiếu, rách nát, tẩy xóa không đọc được | Không | Người duyệt bấm **Phiếu hỏng** + 1 trong 3 lý do | Không |

- Trùng được xét **sau khi** đã loại các dòng không hợp lệ. Ví dụ dòng 2 "008 – Lê Văn Cường" đã bị xác nhận lệch, dòng 5 "012 – Lê Văn Cường" hợp lệ thì phiếu không bị tính là trùng.
- Vòng 1: phiếu 10 dòng, chọn tối đa 10 người, nên chọn quá số lượng chỉ xảy ra khi viết thêm ngoài khung.
- Không dùng dấu Hội Thánh, không in mã đợt in lên phiếu.

## 7. Đếm phiếu và tỉ lệ

**Các con số**
- **Phiếu phát ra**: thư ký nhập tay.
- **Phiếu đã ghi nhận** = số phiếu đã bấm Chấp nhận hoặc Không hợp lệ.
- **Phiếu hợp lệ** = phiếu có chọn người + phiếu trắng.
- **Phiếu không hợp lệ**.
- **Còn lại** = phát ra trừ đã ghi nhận. Khi kết thúc mà khác 0 thì báo chênh lệch (phiếu không thu về, hoặc quét thiếu).
- Luôn đúng: *đã ghi nhận = hợp lệ + không hợp lệ*.

**Tỉ lệ từng người**
- Tỉ lệ = số phiếu của người đó ÷ **tổng số phiếu hợp lệ**. Không tính phiếu không hợp lệ, không tính người vắng mặt.
- Mỗi phiếu chọn nhiều người nên **tổng các tỉ lệ vượt 100%** là bình thường. Màn kết quả ghi rõ điều này để tránh hiểu nhầm.

**Vòng 1 · Đề cử**
- Người có tỉ lệ **trên 50%** thì **vào vòng 2**, xếp từ cao xuống thấp. Không giới hạn số người vào vòng 2.
- Ví dụ 140 phiếu hợp lệ thì cần ít nhất 71 phiếu.
- Màn kết quả chỉ liệt kê người có ít nhất 1 phiếu (danh sách 200 người quá dài), kèm số người không có phiếu nào.

**Vòng 2 · Bầu chính thức** (chờ quy định số người và ngưỡng, OQ-3b)
- Đạt ngưỡng rồi lấy từ cao xuống thấp cho đủ số người cần bầu.
- Bằng phiếu ở vị trí cuối: không tự chọn, gắn nhãn **Bằng phiếu** để hội đồng quyết định.
- Thiếu người đạt ngưỡng: báo số vị trí còn thiếu.

Trong lúc quét, màn kết quả luôn có nhãn **Kết quả tạm thời** cho đến khi chốt.

## 8. Ảnh ghép lưu cho mỗi phiếu

```
+-----------------------------------------------------------------------------+
| Phiếu #043   HỢP LỆ · 8 người được chọn        Bầu Ban Chấp sự · Vòng 1       |
|                                               Chụp 09:41:12 · Duyệt 09:41:30 |
| ẢNH CHỤP (ĐÃ NẮN THẲNG)            | BẢN ĐIỆN TỬ (SAU DUYỆT)                  |
| [ảnh thật]                         | [phiếu in sạch kết quả cuối; dòng sửa    |
|                                    |  ghi "máy đọc: 008"; dòng không hợp lệ    |
|                                    |  gạch ngang + lý do]                      |
|                                    | KẾT LUẬN: HỢP LỆ                          |
| Người duyệt: Tổ 1 · Quét lại: 0 · Sửa 1 dòng · Mã kiểm tra ảnh: 3f9a12c0      |
+-----------------------------------------------------------------------------+
```

- Lưu ngay khi chấp nhận, vào thư mục của phiên, tên file dạng `phieu-043_hop-le.jpg`, `phieu-044_khong-hop-le.jpg`.
- Sửa phiếu sau đó thì sinh **ảnh mới** (`phieu-043_v2_...`), giữ ảnh cũ.
- Ngoài ảnh ghép vẫn giữ ảnh gốc chưa nắn (theo handoff Mục 8) để kiểm toán.

## 9. Danh sách phiếu đã quét

- Lọc nhanh: Tất cả / Hợp lệ / Trắng / Không hợp lệ / Có chỉnh tay.
- Mỗi dòng: mã phiếu, giờ, kết luận, số người được chọn, ghi chú (sửa mấy dòng, dòng không hợp lệ, quét lại mấy lần, lý do không hợp lệ), ảnh nhỏ.
- Bấm vào 1 phiếu: xem ảnh ghép lớn, danh sách người được chọn, lịch sử thao tác, tải ảnh ghép.
- **Mở lại để sửa**: bắt buộc nhập lý do, chỉ được khi không có phiếu khác đang chờ duyệt và phiên chưa chốt. Có nút **Hủy sửa** để quay về như cũ.
- Tab **Nhật ký**: toàn bộ thao tác theo thời gian.

## 10. Chống sai sót

| Rủi ro | Cách app chặn |
|---|---|
| Chụp 1 phiếu 2 lần | Khóa camera sau khi chụp, chỉ mở khi phiếu rời khung; so mã ảnh để cảnh báo trùng |
| Bỏ sót phiếu | Đối soát phát ra / đã ghi nhận; mã phiếu liên tục, không xóa được |
| Bấm nhầm Chấp nhận | Hoàn tác trong 8 giây; mở lại có lý do |
| Máy đọc sai mà người không để ý | Ô máy chưa chắc tô vàng, ảnh cắt dòng đặt sát; kết luận phiếu hiện nổi bật cạnh nút Chấp nhận |
| Nhầm người vì tên gần giống (200 người) | STT là chỗ dựa chính; tên chỉ kiểm tra chéo; lệch thì dòng không hợp lệ |
| Sửa kết quả sau khi chốt | Khóa phiên; mở khóa phải ghi lý do, ghi nhật ký |

## 11. Thử nghiệm khi chưa in / chưa quét được phiếu

Bản mẫu tương tác `docs/ballot-scan/html-design/ballot-scan-prototype.html` có:
- **Chế độ mô phỏng**: app tự sinh phiếu viết tay giả, mô phỏng đưa phiếu vào khung, che góc, rung tay, tự chụp. Chọn được kịch bản phiếu tiếp theo (sạch, lệch STT–tên, STT không có trong danh sách, thiếu STT hoặc tên, không đọc được, trùng người, phiếu trắng, có ký hiệu lạ) để thử từng quy tắc.
- **Camera thật**: chọn iPhone/webcam để xem khung hình thật và chụp bằng phím Space. Bản mẫu chưa có nhận dạng chữ nên phiếu điện tử để trống, nhập tay.
- **Nạp 30 phiếu mẫu** trong Thiết lập để xem ngay danh sách phiếu và màn kết quả.

Bước tiếp theo khi in được: in `out/phieu-mau.pdf` (đã đổi sang 3 ô STT), nhờ 5-10 người viết thử, chụp ảnh tĩnh để benchmark OCR (handoff Mục 10b).

## 12. Câu hỏi mở

- [x] OQ-1: Resolved: vòng 1 phiếu 10 dòng, chọn tối đa 10 người; vòng 2 quy định sau.
- [x] OQ-2: Resolved: phiếu trắng tạm tính hợp lệ (vào mẫu số); thiết kế lại nếu quy chế đổi.
- [x] OQ-3: Resolved: vòng 1 vào vòng 2 khi trên 50% tổng phiếu hợp lệ.
- [ ] OQ-3b: Vòng 2 bầu bao nhiêu người, ngưỡng và mẫu số thế nào?
- [x] OQ-4: Resolved: ghi trùng 1 người ở 2 dòng thì cả phiếu không hợp lệ.
- [x] OQ-5: Resolved: không dùng dấu Hội Thánh, không in mã đợt in.
- [~] OQ-6: Out of scope: ghi 1 tên tổ cho cả phiên, không phân biệt người duyệt, không kiểm tra lại ngẫu nhiên.
- [x] OQ-7: Resolved: xuất Excel, thư ký tự soạn biên bản.
- [ ] OQ-8: Dòng không hợp lệ (lệch STT–tên, STT không có trong danh sách) có làm cả phiếu không hợp lệ không? (quyết định sau)
- [x] OQ-9: Resolved: dòng chỉ có STT hoặc chỉ có tên thì cả phiếu không hợp lệ.
