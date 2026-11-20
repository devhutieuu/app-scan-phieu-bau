# Kiểm phiếu bầu cử

Ứng dụng đọc phiếu bầu cử viết tay, chạy **offline hoàn toàn** trên 1 máy Mac. Điện thoại (tối đa khoảng 5 máy) mở trình duyệt để chụp phiếu, máy đọc **STT** và **họ tên**, người kiểm phiếu **duyệt hoặc sửa**. Máy chỉ đọc, người quyết định kết quả cuối.

- Đọc STT: Apple Vision + mạng CNN chữ số nhỏ.
- Đọc họ tên: ghép 3 bộ đọc (CRNN, VietOCR, Qwen2.5-VL) rồi kiểm chéo với STT, dòng nào lệch sẽ tô vàng.
- Kho phiếu chung cho nhiều bàn, xuất kết quả ra Excel.

Thiết kế chi tiết: [handoff-app-scan-phieu-bau.md](handoff-app-scan-phieu-bau.md), [DESIGN.md](DESIGN.md). Cách dùng nhiều điện thoại: [docs/ballot-scan/huong-dan-nhieu-ban.md](docs/ballot-scan/huong-dan-nhieu-ban.md).

## Yêu cầu

| | |
|---|---|
| Máy chủ | **Mac** chip Apple Silicon (M1 trở lên), RAM 16 GB trở lên (Qwen cần khoảng 6 GB), hoặc **Windows 10/11 64-bit**, RAM 16 GB (xem mục "Cài đặt trên Windows") |
| Hệ điều hành | macOS (đầy đủ nhất) hoặc Windows (bản rút gọn, không có Qwen) |
| Python | 3.12 (khuyên dùng [uv](https://docs.astral.sh/uv/)) |
| Mạng | Internet chỉ cần lúc cài đặt. Ngày bầu dùng router/Wi-Fi riêng, không cần Internet |
| Dung lượng trống | khoảng 12 GB (thư viện + model) |

## Cài đặt trên Mac

Chạy 1 lần, có Internet. Dự án dùng **3 môi trường Python riêng** vì TensorFlow, PyTorch và MLX xung đột phiên bản với nhau.

### 1. Lấy mã nguồn

```bash
git clone https://github.com/thienhuyuel/app-scan-phieu-bau.git
cd app-scan-phieu-bau
```

### 2. Cài uv (nếu chưa có)

```bash
brew install uv
```

### 3. Tạo 3 môi trường và cài thư viện

Môi trường chính (máy chủ, STT, VietOCR, sinh phiếu):

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

Môi trường CRNN (TensorFlow):

```bash
uv venv --python 3.12 .venv-tf
uv pip install --python .venv-tf/bin/python -r requirements-tf.txt
```

Môi trường Qwen (MLX, chỉ Apple Silicon):

```bash
uv venv --python 3.12 .venv-mlx
uv pip install --python .venv-mlx/bin/python -r requirements-mlx.txt
```

> Thiếu `.venv-tf` hoặc `.venv-mlx` thì máy chủ vẫn đọc STT bình thường, chỉ không có phần kiểm chéo họ tên (tô vàng "tên không khớp STT").

### 4. Tải model

```bash
bash tools/setup_models.sh
```

Script tải về:

| Model | Dùng cho | Nơi lưu | Dung lượng |
|---|---|---|---|
| VietOCR `vgg_transformer` | đọc họ tên | `tools/models/vgg_transformer.pth` | 152 MB |
| CRNN tiếng Việt ([TomHuynhSG](https://github.com/TomHuynhSG/vietnamese-handwriting-recognition-ocr), MIT) | đọc họ tên | `tools/models/crnn_vi_cinnamon.hdf5` | 88 MB |
| `mlx-community/Qwen2.5-VL-7B-Instruct-4bit` | đọc họ tên | `~/.cache/huggingface` | khoảng 5 GB |
| CNN chữ số STT | đọc STT | `tools/models/digits_cnn.pt` (có sẵn trong repo) | 1 MB |

Mạng chữ số được huấn luyện từ MNIST. Muốn huấn luyện lại: `.venv/bin/python tools/train_digits.py` (tự tải MNIST).

### 5. Cho phép Terminal dùng mạng cục bộ

Vào **Cài đặt hệ thống → Quyền riêng tư & Bảo mật → Mạng cục bộ**, bật cho **Terminal**, rồi chạy máy chủ từ Terminal. Nếu không, điện thoại sẽ không vào được máy chủ.

## Cài đặt trên Windows

Bản Windows dùng cùng mã nguồn, khác Mac ở 3 điểm: không có Apple Vision (VietOCR đọc thay, riêng ô STT vẫn dùng mạng CNN chữ số nên gần như không ảnh hưởng), **không có Qwen** (chỉ chạy trên chip Apple; kiểm chéo họ tên dùng CRNN + VietOCR, độ chính xác thấp hơn ghép đủ ba), và chạy hoàn toàn trên CPU nên chậm hơn Mac M1.

Mở **PowerShell** và chạy lần lượt.

1. Cài Python 3.12, Git và uv:

```powershell
winget install Python.Python.3.12 Git.Git astral-sh.uv
```

2. Lấy mã nguồn:

```powershell
git clone https://github.com/thienhuyuel/app-scan-phieu-bau.git
cd app-scan-phieu-bau
```

3. Tạo môi trường chính và môi trường CRNN (không cần `.venv-mlx`):

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
uv venv --python 3.12 .venv-tf
uv pip install --python .venv-tf\Scripts\python.exe -r requirements-tf.txt
```

4. Tải model (VietOCR, CRNN):

```powershell
powershell -ExecutionPolicy Bypass -File tools\setup_models.ps1
```

5. Chạy máy chủ (lần đầu tự tạo chứng chỉ https, cho phép Windows Firewall khi được hỏi, chọn mạng riêng):

```powershell
powershell -ExecutionPolicy Bypass -File tools\start_prototype.ps1
```

Mở <http://localhost:8766/> trên chính máy đó, các máy khác mở `https://<IP máy>:8443/` (script in IP ra). Tạo lại chứng chỉ khi đổi IP: `.venv\Scripts\python.exe tools\make_cert.py`. Sinh phiếu in: `.venv\Scripts\python.exe tools\make_ballot.py`.

> Bản Windows mới được kiểm tra bằng cách mô phỏng trên Mac (đọc STT cho kết quả giống hệt Mac trên phiếu mẫu), chưa chạy thử trên máy Windows thật.

## Chạy trên Mac

```bash
bash tools/start_prototype.sh
```

Script tự bật 3 dịch vụ rồi mở trang kiểm phiếu:

| Dịch vụ | Cổng | Môi trường |
|---|---|---|
| Máy chủ kiểm phiếu + giao diện | 8766 (http), 8443 (https) | `.venv` |
| Qwen đọc họ tên | 8767 | `.venv-mlx` |
| CRNN đọc họ tên | 8768 | `.venv-tf` |

- Máy Mac: <http://localhost:8766/>
- Điện thoại / máy khác trong cùng mạng: `https://<IP máy Mac>:8443/`
- Dừng: `Ctrl+C`.
- Qwen nạp model mất khoảng nửa phút, trong lúc đó phiếu chưa được kiểm tên.

### Chứng chỉ https (bắt buộc cho điện thoại)

Trình duyệt chỉ cho dùng camera khi trang chạy qua https. Tạo chứng chỉ tự ký (lần đầu `start_prototype.sh` tự làm, đổi IP thì chạy lại):

```bash
bash tools/make_cert.sh
```

Sau đó cài `config/kiem-phieu-cert.crt` lên từng điện thoại. Các bước cho iPhone, Android, Windows xem [huong-dan-nhieu-ban.md](docs/ballot-scan/huong-dan-nhieu-ban.md).

## Sinh phiếu để in

```bash
.venv/bin/python tools/make_ballot.py
```

Ra `out/phieu-de-cu.pdf`, `out/phieu-mau.pdf`, `out/phieu-mau.docx` và cập nhật `config/ballot_layout.json`. Số dòng/phiếu, số chữ số STT chỉnh ngay đầu file `tools/make_ballot.py`.

## Công cụ khác

| Lệnh | Việc |
|---|---|
| `.venv/bin/python tools/load_test_phones.py` | Thử tải giả lập nhiều điện thoại |
| `.venv/bin/python tools/bench_verify.py` | Đo độ chính xác kiểm chéo họ tên |
| `.venv/bin/python tools/train_digits.py` | Huấn luyện lại mạng chữ số |
| `.venv/bin/python tools/llm_names.py` | Thử đọc tên bằng Gemini (cần `GEMINI_API_KEY`, chưa gắn vào máy chủ) |

## Dữ liệu không đưa lên GitHub

Các thứ sau nằm trong `.gitignore`, mỗi máy tự tạo:

- `out/`: phiếu đã quét, trạng thái phiên (`out/session/state.json`), phiếu in. Chứa dữ liệu thật của buổi bầu.
- `docs/*.xlsx`: danh sách cử tri.
- `config/key.pem`, `config/cert.pem`, `config/kiem-phieu-cert.crt`: tạo bằng `tools/make_cert.sh`.
- `config/gemini_key.txt`: API key Gemini (tùy chọn).
- Model lớn trong `tools/models/`: tải bằng `tools/setup_models.sh`.

## Cấu trúc thư mục

```
tools/            máy chủ, dịch vụ đọc họ tên, script sinh phiếu, công cụ thử
config/           bố cục phiếu (ballot_layout.json), logo
docs/ballot-scan/ brainstorm, giao diện HTML mẫu, hướng dẫn nhiều bàn
DESIGN.md         bảng màu và quy tắc giao diện
```
