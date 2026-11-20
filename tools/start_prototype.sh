#!/bin/bash
# Bật máy chủ kiểm phiếu trên Mac: đọc STT + kiểm chéo họ tên + trang kiểm phiếu + kho phiếu chung cho nhiều bàn. Dừng bằng Ctrl+C.
#   Máy Mac:       http://localhost:8766/
#   Các bàn khác:  https://<IP máy Mac>:8443/   (cần chứng chỉ: tools/make_cert.sh tự tạo lần đầu)
# Phiếu đã duyệt lưu ở out/session/state.json, tắt/bật lại máy chủ không mất.
cd "$(dirname "$0")/.."

busy() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

[ -f config/cert.pem ] || bash tools/make_cert.sh

if busy 8766; then
  echo "Máy chủ đã chạy sẵn ở cổng 8766. Muốn nạp bản mới thì tắt nó (Ctrl+C ở cửa sổ đang chạy) rồi chạy lại script."
  open "http://localhost:8766/"
  exit 0
fi

PIDS=()
trap 'kill "${PIDS[@]}" 2>/dev/null' EXIT
# Hai dịch vụ đọc họ tên (kiểm chéo tên với STT). Thiếu môi trường nào thì bỏ qua: máy chủ vẫn đọc STT như thường,
# chỉ không có phần tô vàng "tên không khớp STT". Qwen nạp mô hình mất khoảng nửa phút, trong lúc đó phiếu chưa được kiểm tên.
if [ -x .venv-tf/bin/python ] && ! busy 8768; then .venv-tf/bin/python tools/crnn_server.py >out/crnn.log 2>&1 & PIDS+=($!); fi
if [ -x .venv-mlx/bin/python ] && ! busy 8767; then .venv-mlx/bin/python tools/qwen_server.py >out/qwen.log 2>&1 & PIDS+=($!); fi
.venv/bin/python tools/ocr_server.py &
PIDS+=($!)
for _ in $(seq 1 40); do curl -s -o /dev/null http://localhost:8766/health && break; sleep 0.5; done
IP="$(ipconfig getifaddr en0 || ipconfig getifaddr en1)"
echo "Các bàn khác mở: https://${IP:-<IP máy Mac>}:8443/"
open "http://localhost:8766/"
wait
