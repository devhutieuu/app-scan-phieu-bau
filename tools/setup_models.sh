#!/bin/bash
# Tải các model đọc họ tên về máy (làm 1 lần, cần Internet). Sau đó chạy offline hoàn toàn.
#   bash tools/setup_models.sh          # tải tất cả
# Bỏ qua file đã có. Qwen tải riêng vào ~/.cache/huggingface (khoảng 5 GB).
set -e
cd "$(dirname "$0")/.."
mkdir -p tools/models

get() {  # get <đường dẫn> <url>
  if [ -s "$1" ]; then echo "Đã có: $1"; else echo "Tải: $1"; curl -L --fail --progress-bar -o "$1" "$2"; fi
}

# VietOCR (đọc họ tên viết tay), ~152 MB
get tools/models/vgg_transformer.pth "https://vocr.vn/data/vietocr/vgg_transformer.pth"
# CRNN tiếng Việt của TomHuynhSG (MIT), ~88 MB
get tools/models/crnn_vi_cinnamon.hdf5 "https://github.com/TomHuynhSG/vietnamese-handwriting-recognition-ocr/raw/main/model_checkpoint_weights.hdf5"

# Qwen2.5-VL-7B 4-bit (cần .venv-mlx)
if [ -x .venv-mlx/bin/python ]; then
  .venv-mlx/bin/python - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download("mlx-community/Qwen2.5-VL-7B-Instruct-4bit")
print("Đã có Qwen2.5-VL-7B-Instruct-4bit")
PY
else
  echo "Chưa có .venv-mlx, bỏ qua Qwen (xem README, mục Cài đặt)."
fi
echo "Xong."
