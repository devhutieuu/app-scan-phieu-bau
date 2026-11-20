"""Dịch vụ đọc họ tên viết tay bằng Qwen2.5-VL-7B (4-bit, mlx-vlm), chạy offline trên chip Apple.

Chạy trong môi trường riêng (tránh đụng thư viện của máy đọc chính):
    .venv-mlx/bin/python tools/qwen_server.py          (cổng 8767)
Máy đọc chính (tools/ocr_server.py) gọi POST /name với ảnh 1 ô họ tên khi chọn engine "qwen-vl".
Model tải sẵn bằng huggingface_hub vào ~/.cache/huggingface (mlx-community/Qwen2.5-VL-7B-Instruct-4bit).
"""
import base64
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from mlx_vlm import generate, load
from mlx_vlm.prompt_utils import apply_chat_template
from mlx_vlm.utils import load_config

MODEL = "mlx-community/Qwen2.5-VL-7B-Instruct-4bit"
PORT = int(os.environ.get("KP_QWEN_PORT", 8767))
PROMPT = ("Ảnh là một ô họ tên viết tay tiếng Việt trên phiếu bầu. Hãy chép lại chính xác họ tên được viết, "
          "giữ đúng dấu tiếng Việt và đúng như chữ trên giấy, kể cả khi viết sai hoặc viết tắt. "
          "Chỉ trả về họ tên, không giải thích. Ô trống thì trả về chuỗi rỗng.")

print(f"Đang nạp {MODEL} ...", flush=True)
model, processor = load(MODEL)
config = load_config(MODEL)
LOCK = threading.Lock()  # model không chạy song song


def read_name(png_bytes):
    with tempfile.NamedTemporaryFile(suffix=".png") as f:
        f.write(png_bytes)
        f.flush()
        prompt = apply_chat_template(processor, config, PROMPT, num_images=1)
        with LOCK:
            out = generate(model, processor, prompt, [f.name], max_tokens=32, temperature=0.0, verbose=False)
    text = getattr(out, "text", out)
    return " ".join(str(text).strip().strip('"').split())


class H(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send(200, {"ok": True, "model": MODEL}) if self.path.startswith("/health") else self._send(404, {})

    def do_POST(self):
        if not self.path.startswith("/name"):
            return self._send(404, {"error": "not found"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            t0 = time.time()
            text = read_name(base64.b64decode(body["image"].split(",", 1)[-1]))
            self._send(200, {"text": text, "ms": int((time.time() - t0) * 1000)})
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def log_message(self, fmt, *a):
        if not self.path.startswith("/health"):
            sys.stderr.write("[qwen] " + fmt % a + "\n")


if __name__ == "__main__":
    print(f"Dịch vụ Qwen đọc họ tên chạy ở http://localhost:{PORT}", flush=True)
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)  # nhiều luồng để /health trả lời ngay cả khi model đang bận
    srv.daemon_threads = True
    srv.serve_forever()
