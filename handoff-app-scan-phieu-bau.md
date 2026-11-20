# Handoff: App scan phiếu bầu cử (hội đồng)

## 1. Mục tiêu

Làm app đọc phiếu bầu cử dùng thật cho hội đồng. Người bầu điền **STT** và viết tay **họ tên** lên phiếu. App tự nhận phiếu khi người kiểm soát đưa phiếu vào camera, đọc nội dung, và hiển thị lên máy tính để người kiểm soát **duyệt (approve) hoặc sửa**. Máy chỉ đọc, người quyết định kết quả cuối.

## 2. Bối cảnh và quyết định đã chốt

- Quy mô: **dưới 200 phiếu**.
- Bầu cử có một danh sách gồm **STT + Họ và tên**. Người bầu điền cả STT lẫn họ tên.
- Lý do điền cả hai: STT là chữ số, OCR đọc rất dễ và chính xác, dùng làm điểm tựa. Phần họ tên viết tay chắc chắn sẽ có lệch, nên đối chiếu ngược với danh sách để sửa.
- Thiết bị quét: **camera (webcam hoặc điện thoại làm webcam), không bấm chụp**. Người kiểm soát đưa phiếu vào khung, giữ khoảng 1-2 giây, app tự chốt ảnh.
- Máy tính nhận phiếu vừa quét và hiện ngay để người kiểm soát duyệt.
- Không cần GPU. Chạy CPU, laptop/PC 8-16GB RAM, SSD.
- Nguyên tắc: **máy đọc, người xác nhận**. Không để máy tự chốt kết quả.

## 3. Quyết định đã chốt (cập nhật 28/10/2026) và câu hỏi còn mở

Đã chốt:
1. Danh sách là danh sách **ứng viên**; người bầu điền STT + tên người mình chọn.
2. Mỗi phiếu có **số dòng quy định (mẫu: 10 dòng)**, được chọn ít hơn, được để phiếu trắng. STT tối đa **3 chữ số** (danh sách đến 200, cập nhật 28/10/2026). Cả hai là tham số trong `tools/make_ballot.py`.
3. Phiếu **ẩn danh**, không mã cử tri.
4. Máy: MacBook Pro M1 Pro 32GB. Camera: **iPhone qua Continuity Camera**.
5. **Offline hoàn toàn**.
6. OCR họ tên: dùng **VietOCR làm engine chính**, **PaddleOCR làm dự phòng** (đặt sau lớp trừu tượng để đổi được). Chữ số STT: Tesseract digits hoặc CNN nhỏ. Các model ở mục 10c chỉ thử thêm nếu hai engine này chưa đạt.

7. **Bầu 2 vòng, cách nhau 1 tuần**, mỗi vòng 1 phiên. Vòng 1 (đề cử): danh sách ~200 tín hữu đủ điều kiện, chọn tối đa 10 người; ai **trên 50% tổng phiếu hợp lệ** vào vòng 2. Vòng 2 (bầu chính thức): danh sách là kết quả vòng 1, số người được chọn quy định sau.
8. Quy tắc phiếu (chi tiết ở `docs/ballot-scan/brainstorms/scan-review-workspace.md` Mục 5-6), tính theo chữ ghi trên phiếu:
   - Dòng có STT và tên chỉ 2 người khác nhau: **dòng không hợp lệ**.
   - Tên có trong danh sách nhưng STT không có: **dòng không hợp lệ**.
   - Dòng chỉ có STT hoặc chỉ có tên: **cả phiếu không hợp lệ**.
   - Ghi trùng 1 người ở 2 dòng: **cả phiếu không hợp lệ**.
   - Phiếu trắng: tạm tính **hợp lệ** (vào mẫu số).
   - Không dùng dấu Hội Thánh, không in mã đợt in.
9. Xuất kết quả ra **Excel**, thư ký tự soạn biên bản. Ghi 1 tên tổ kiểm phiếu cho cả phiên.

Còn mở:
- Dòng không hợp lệ (lệch STT–tên, STT ngoài danh sách) có làm cả phiếu không hợp lệ không.
- Vòng 2: số người được bầu, ngưỡng và mẫu số.

## 4. Thiết kế phiếu

- 4 marker ở 4 góc (ví dụ ArUco hoặc hình vuông đen đặc) để căn chỉnh phối cảnh.
- Ô **STT**: mỗi chữ số một ô riêng (kiểu phiếu thi), có khung rõ ràng.
- Ô **họ tên**: khung chữ nhật rõ, viết tay, đủ rộng cho tên có dấu tiếng Việt.
- Nền trắng, mực in đen, không họa tiết gần vùng điền.
- In bằng máy laser. Kích thước và vị trí các ô lưu trong một file cấu hình (JSON) để code cắt vùng theo tọa độ chuẩn.

## 5. Pipeline xử lý

1. **Camera loop**: quay liên tục, theo dõi từng khung hình.
2. **Auto-capture** (xem mục 6).
3. **Nắn phối cảnh**: tìm 4 marker, `cv2.getPerspectiveTransform` đưa phiếu về kích thước chuẩn.
4. **Cắt vùng** theo cấu hình: ô STT, ô họ tên.
5. **OCR STT**: nhận dạng từng chữ số trong từng ô riêng (CNN nhỏ kiểu MNIST hoặc Tesseract chế độ digits). Ghép thành STT, đối chiếu danh sách hợp lệ.
6. **OCR họ tên**: model đọc chữ viết tay tiếng Việt chạy offline (ví dụ VietOCR hoặc PaddleOCR), kết quả đi qua fuzzy match với danh sách (rapidfuzz, chuẩn hóa bỏ dấu để so khớp).
7. **Kiểm tra chéo** STT với họ tên:
   - Khớp: độ tin cậy cao.
   - STT hợp lệ nhưng tên không khớp danh sách: cờ "nghi ngờ".
   - STT không có trong danh sách, ô trống, độ tin cậy thấp, đọc không ra: cờ "cần duyệt kỹ".
8. **Phát hiện trùng**: cùng một ảnh quét hai lần (hash ảnh) thì cảnh báo, không tính hai lần.
9. Đẩy kết quả lên hàng đợi duyệt, phiếu cờ nghi ngờ lên đầu.

## 6. Logic tự chụp (không cần bấm)

Điều kiện chốt ảnh, cần đạt đồng thời:
- Thấy đủ **4 marker**.
- Ảnh **đủ nét**: phương sai Laplacian của vùng phiếu trên một ngưỡng.
- Phiếu **đứng yên** khoảng 1-2 giây: so sánh các khung hình liên tiếp (độ chênh nhỏ hoặc vị trí marker gần như không đổi).

Sau khi chốt:
- Lấy khung hình **nét nhất** trong khoảng đứng yên.
- Phản hồi: khung xanh + tiếng bíp.
- Khóa lại, chỉ sẵn sàng cho phiếu tiếp khi phiếu **rời khỏi khung hình** (tránh chụp lặp).
- Ngón tay che marker hoặc ảnh mờ thì không kích hoạt, tự lọc ảnh xấu.

Ngưỡng nét, thời gian đứng yên, độ chênh khung hình để vào file cấu hình, tinh chỉnh khi thử thực tế.

## 7. Giao diện duyệt (máy tính)

- Mỗi phiếu hiện: ảnh phiếu gốc (đã nắn thẳng), STT máy đọc, họ tên máy đọc, tên gợi ý từ danh sách, mức tin cậy, các cờ cảnh báo.
- Hành động: **Duyệt**, **Sửa** (chọn lại từ danh sách theo STT hoặc tên), **Loại phiếu** (không hợp lệ, kèm lý do).
- Hàng đợi sắp xếp: nghi ngờ trước, bình thường sau. Phím tắt (Enter = duyệt, E = sửa) để duyệt nhanh.
- Bộ đếm: đã quét / đã duyệt / chờ duyệt / không hợp lệ.
- Gợi ý: kiểm tra lại ngẫu nhiên một tỷ lệ phiếu đã duyệt bởi người thứ hai.

## 8. Dữ liệu và kiểm toán

Mỗi phiếu lưu:
- Ảnh gốc (chưa nắn) và ảnh đã nắn.
- Kết quả máy đọc (STT, tên, độ tin cậy) và kết quả cuối sau duyệt.
- Người duyệt, thời điểm, và lịch sử sửa (ai sửa gì, giá trị cũ, giá trị mới).
- Hash ảnh để phát hiện quét trùng và chống sửa đổi.

Lưu SQLite cho metadata, ảnh lưu thư mục cục bộ. Không xóa, chỉ thêm bản ghi mới khi sửa (append-only log).

## 9. Xuất kết quả

- Excel/CSV: số phiếu theo từng STT, tổng phiếu hợp lệ, không hợp lệ, danh sách phiếu đã sửa.
- Báo cáo kiểm toán: nhật ký thao tác.
- Sao lưu ảnh và DB ra ổ ngoài ngay trong buổi kiểm phiếu.

## 10. Stack đề xuất

- Ngôn ngữ: Python.
- Xử lý ảnh: OpenCV (marker, nắn phối cảnh, đo độ nét).
- OCR: PaddleOCR hoặc VietOCR cho họ tên; Tesseract hoặc CNN nhỏ cho chữ số.
- So khớp tên: rapidfuzz + chuẩn hóa tiếng Việt (bỏ dấu, lowercase).
- Backend: FastAPI.
- Giao diện: web UI chạy local (React hoặc HTML đơn giản), nhận stream camera qua trình duyệt hoặc đọc webcam trực tiếp ở backend.
- DB: SQLite.
- Chạy offline hoàn toàn trên máy của hội đồng.

## 10b. Ghi chú riêng cho macOS (Apple Silicon, 32GB)

- Python, OpenCV, FastAPI chạy tốt trên arm64. Dùng venv hoặc uv, cài bản wheel arm64.
- PyTorch dùng GPU của chip Apple qua backend **MPS** (`torch.device("mps")`), PaddleOCR/VietOCR chạy được trên CPU, đủ nhanh cho dưới 200 phiếu.
- Với 32GB RAM có thể chạy model vision cỡ nhỏ-vừa cục bộ (MLX hoặc Ollama) để đọc họ tên viết tay, vẫn offline. Dùng làm engine so sánh, không bắt buộc.
- macOS có **Vision framework** (OCR của Apple, hỗ trợ tiếng Việt), gọi qua `pyobjc-framework-Vision`. Thêm vào danh sách engine cần thử.
- Quyền camera: lần đầu chạy, cho phép camera cho Terminal/IDE trong System Settings > Privacy & Security > Camera.
- Chống ngủ máy trong buổi kiểm phiếu: `caffeinate -d` hoặc tắt sleep, cắm sạc liên tục.
- Đọc camera: OpenCV `cv2.VideoCapture` với backend AVFoundation, chọn đúng index khi có nhiều camera (iPhone Continuity Camera hiện như một camera riêng).

### Bước benchmark OCR trước khi chốt engine

Lấy 30-50 phiếu thử, nhiều kiểu chữ (đủ dấu, viết ẩu, viết tắt). Chạy qua các engine: Apple Vision, VietOCR và các model vision ở mục 10c. Đo tỷ lệ khớp tên **sau khi bỏ dấu và fuzzy match với danh sách**, không đo độ đúng từng dấu. Chọn engine có tỷ lệ khớp cao nhất và ít phiếu phải duyệt tay nhất.

## 10c. Model vision đọc chữ viết tay tiếng Việt (kết quả tìm hiểu 26-27/10/2026)

**Lưu ý trung thực:** chưa tìm thấy benchmark nào so sánh trực tiếp các model dưới đây trên cùng một bộ chữ viết tay tiếng Việt. Các con số lấy từ những bộ dữ liệu và điều kiện khác nhau, **không so sánh trực tiếp được**. Vì vậy mục này là danh sách rút gọn để benchmark trên phiếu thật, không phải kết luận model nào tốt nhất.

Ô họ tên trên phiếu là một dòng chữ, nên phù hợp với các model đọc **từng dòng** (line-level). Cắt đúng ô họ tên rồi đưa vào model, không đưa cả tờ phiếu.

### Danh sách rút gọn để benchmark

| Model | Cỡ | Bằng chứng về tiếng Việt viết tay | Chạy trên Mac |
|---|---|---|---|
| **PaddleOCR-VL-1.6** (PaddlePaddle) | 0.9B, Apache-2.0 | Bản gốc hỗ trợ 100+ ngôn ngữ, đứng đầu OmniDocBench v1.6 (96.34%), nhưng đó là benchmark tài liệu in. Một dự án nghiên cứu trên GitHub (`khanhlinh-innomation/vlm-handwriting-ocr`) **fine-tune** model này trên UIT-HWDB (chữ viết tay tiếng Việt, cấp dòng) và đạt test CER 5.40%, WER 12.77%, đúng nguyên dòng 43.28%, độ trễ 0.374s (chạy trên GPU RTX 5090, chưa kiểm chứng độc lập). | `mlx-vlm` có hỗ trợ PaddleOCR-VL |
| **Vintern-1B-v3.5** (5CD-AI) | 1B, fine-tune từ InternVL2.5-1B | Fine-tune riêng cho tiếng Việt, model card nói xử lý tốt hóa đơn, văn bản pháp lý, chữ viết tay, bảng. Chưa tìm thấy con số riêng cho chữ viết tay. | Dùng qua `transformers` + `trust_remote_code`, cần thử có chạy ổn trên MPS không |
| **MinerU2.5-Pro-1.2B-vi-ocr-v2** (Faust345, LoRA từ MinerU2.5-Pro) | 1.2B | Fine-tune trên `5CD-AI/Viet-Handwriting-OCR-v2`: CER 0.2177, WER 0.4677 (test n=300), so với bản gốc CER 0.6077. **Giấy phép CC BY-NC 4.0, chỉ phi thương mại**, và cần đăng nhập Hugging Face để tải. | Qwen2-VL base, có thể chạy qua `mlx-vlm`, cần kiểm tra |
| **Qwen3-VL-8B / Qwen2.5-VL-7B** (4-bit, mlx-community) | 7-8B | Model đa dụng, đọc chữ tốt nói chung. Chưa tìm thấy số liệu chữ viết tay tiếng Việt. Ưu điểm: `mlx-vlm` hỗ trợ **fine-tune LoRA/QLoRA ngay trên Mac** cho dòng Qwen-VL. | Chạy tốt qua `mlx-vlm`, 32GB RAM dư sức |
| **dots.ocr (3B)** / **LightOnOCR-2-1B** | 3B / 1B | Đa ngôn ngữ, chủ yếu đánh giá trên tài liệu in. Chữ viết tay tiếng Việt chưa có số liệu. Làm phương án phụ. | dots.ocr có trong `mlx-vlm` |

### Baseline không phải VLM (nên có để so sánh)

- **VietOCR** và gói **vnhtr** (VGG-Transformer, TrOCR cho chữ viết tay tiếng Việt): nhỏ, nhanh, có sẵn pretrain cho tiếng Việt. Các nghiên cứu trên VNOnDB báo CER khoảng 4-5% cho hệ tốt nhất ở cấp dòng, nhưng đó là chữ viết online được render lại, khác với chữ viết tay trên giấy.
- **Apple Vision** (offline, có sẵn trong macOS).

### Gợi ý cách dùng VLM cho bài toán này

1. Đưa riêng ảnh ô họ tên vào model, nhận chuỗi text.
2. Chuẩn hóa (bỏ dấu, lowercase) rồi fuzzy match với danh sách ứng viên, **kết hợp STT** đã đọc ở bước trước để thu hẹp còn đúng một tên.
3. Nếu có thể, thay vì để model sinh tự do, **xếp hạng các tên trong danh sách** theo độ khả dĩ (so từng tên ứng viên với kết quả đọc), vì danh sách là tập đóng nên hạn chế lỗi lạ.
4. Độ tin cậy thấp hoặc STT/tên mâu thuẫn thì gắn cờ cho người duyệt như thiết kế ở mục 5 và 7.

### Fine-tune (nếu baseline chưa đủ tốt)

- Bằng chứng ở trên cho thấy fine-tune cải thiện rất mạnh so với bản gốc (MinerU: CER từ 0.61 xuống 0.22 sau khi fine-tune trên dữ liệu chữ viết tay tiếng Việt).
- Dữ liệu công khai: UIT-HWDB (Kaggle `ntklinhfitus/uit-hwdb`), `5CD-AI/Viet-Handwriting-OCR-v2` (cần xin quyền truy cập, CC BY-NC 4.0), bộ Cinnamon AI (1.838 ảnh), VNOnDB.
- Cách tốt nhất vẫn là thu thêm mẫu **chữ viết tay thật của người sẽ điền phiếu** (hoặc người tương tự), vì phong cách chữ là yếu tố quyết định.
- Trên Mac: `mlx-vlm` có script `lora.py` hỗ trợ LoRA/QLoRA cho Qwen2-VL, Qwen2.5-VL, Qwen3-VL.

### Cách chọn

Chạy 3-4 model trên cùng 30-50 phiếu thử, đo CER/WER và tỷ lệ khớp đúng tên sau fuzzy match. Chọn model có tỷ lệ phiếu khớp đúng cao nhất, độ trễ dưới vài giây mỗi phiếu, và giấy phép phù hợp. Hội đồng dùng nội bộ nên xác nhận lại điều khoản giấy phép của từng model (nhất là các model và dữ liệu CC BY-NC).

## 11. Phần cứng

- **Máy chạy app: MacBook Pro M1 Pro, 32GB RAM** (đã chốt). Dư sức cho toàn bộ pipeline, không cần GPU rời.
- Camera: webcam Full HD có lấy nét tự động, hoặc iPhone làm webcam bằng **Continuity Camera** (có sẵn trên macOS, không cần app thứ ba). Camera tích hợp trên MacBook khó cố định nhìn xuống bàn nên không khuyến khích.
- Giá đỡ cố định, tấm nền phẳng có viền chặn để đặt phiếu vào đúng vị trí, đèn LED hai bên cho sáng đều.
- Khóa lấy nét và độ sáng camera cố định.
- Ổ cứng ngoài/USB sao lưu, UPS nhỏ, màn hình thứ hai cho người duyệt.
- Máy in laser để in phiếu và báo cáo.

## 12. Rủi ro và cách giảm

| Rủi ro | Cách giảm |
|---|---|
| Phiếu cầm tay bị rung, mờ | Tấm nền phẳng có viền chặn, ngưỡng độ nét + đứng yên |
| Họ tên viết tay đọc sai | Fuzzy match với danh sách, STT làm điểm tựa, người duyệt xác nhận |
| STT và tên không khớp | Cờ nghi ngờ, đẩy lên đầu hàng đợi |
| Quét trùng một phiếu | Chờ phiếu rời khung, hash ảnh phát hiện trùng |
| Ánh sáng thay đổi | Đèn cố định, khóa exposure, kiểm tra ảnh trước khi nhận |
| Mất điện/hỏng máy | UPS, ghi DB sau mỗi phiếu, sao lưu liên tục |
| Hội đồng cần kiểm tra lại | Lưu ảnh gốc, nhật ký append-only |

## 13. Lộ trình gợi ý

1. **Mẫu phiếu** + file cấu hình tọa độ + sinh phiếu thử (PDF).
2. **Pipeline trên ảnh tĩnh**: nắn phối cảnh, cắt vùng, đọc STT, đọc tên, fuzzy match. Đo độ chính xác trên bộ phiếu thử có nhiều kiểu chữ.
3. **Auto-capture từ camera**: marker + độ nét + đứng yên + chống chụp lặp.
4. **Giao diện duyệt** + hàng đợi + phím tắt.
5. **Lưu trữ, nhật ký, xuất Excel**.
6. **Chạy thử** với phiếu giả (khoảng 50-100 phiếu, nhiều người viết), tinh chỉnh ngưỡng, trước ngày bầu.

## 14. Tiêu chí hoàn thành

- STT đọc đúng gần như tuyệt đối trên phiếu thử; mọi phiếu STT/tên không chắc chắn đều bị gắn cờ.
- Không có phiếu nào được tính vào kết quả mà chưa qua người duyệt.
- Mỗi phiếu truy vết được: ảnh gốc, kết quả máy đọc, người duyệt, lịch sử sửa.
- Quét liên tục không chụp lặp, không bỏ sót phiếu.
- Chạy offline được trọn buổi kiểm phiếu.
