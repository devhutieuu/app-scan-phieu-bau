"""Dịch vụ đọc họ tên viết tay bằng CRNN + CTC (TensorFlow) của TomHuynhSG/vietnamese-handwriting-recognition-ocr.

Nguồn: https://github.com/TomHuynhSG/vietnamese-handwriting-recognition-ocr (giấy phép MIT).
Model học trên 1.838 ảnh địa chỉ viết tay của Cinnamon AI; tác giả báo CER 4,8% / WER 15,7% trên tập thử của họ.
Kiến trúc, bảng ký tự và tiền xử lý chép đúng theo notebook gốc (ô 14-16, 34, 43) để nạp được trọng số.

Chạy trong môi trường riêng:  .venv-tf/bin/python tools/crnn_server.py      (cổng 8768)
POST /name {images: [ảnh các ô họ tên của 1 phiếu], cands: [tên...]} -> {norms: [{tên: điểm đã chuẩn hóa}], ms}
POST /name {image: ảnh 1 ô họ tên (base64), cands: [tên...] tùy chọn}
  -> {text: đọc tự do, best: tên trong danh sách có xác suất CTC cao nhất, scores: {tên: log-xác suất}, ms}
"""
import base64
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np
import tensorflow as tf
from tensorflow.keras import layers, Model

ROOT = Path(__file__).resolve().parent
WEIGHTS = ROOT / "models" / "crnn_vi_cinnamon.hdf5"
PORT = int(os.environ.get("KP_CRNN_PORT", 8768))
H, W = 118, 2167
CHARS = " #'()+,-./0123456789:ABCDEFGHIJKLMNOPQRSTUVWXYabcdeghiklmnopqrstuvwxyzÂÊÔàáâãèéêìíòóôõùúýăĐđĩũƠơưạảấầẩậắằẵặẻẽếềểễệỉịọỏốồổỗộớờởỡợụủỨứừửữựỳỵỷỹ"
BLANK = len(CHARS)


def build():
    inp = layers.Input(shape=(H, W, 1))
    x = layers.Conv2D(64, 3, padding="same")(inp)
    x = layers.Activation("relu")(layers.MaxPool2D(3, 3)(x))
    x = layers.Conv2D(128, 3, padding="same")(x)
    x = layers.Activation("relu")(layers.MaxPool2D(3, 3)(x))
    x = layers.Activation("relu")(layers.BatchNormalization()(layers.Conv2D(256, 3, padding="same")(x)))
    x3 = x
    x = layers.BatchNormalization()(layers.Conv2D(256, 3, padding="same")(x))
    x = layers.Activation("relu")(layers.Add()([x, x3]))
    x = layers.Activation("relu")(layers.BatchNormalization()(layers.Conv2D(512, 3, padding="same")(x)))
    x5 = x
    x = layers.BatchNormalization()(layers.Conv2D(512, 3, padding="same")(x))
    x = layers.Activation("relu")(layers.Add()([x, x5]))
    x = layers.BatchNormalization()(layers.Conv2D(1024, 3, padding="same")(x))
    x = layers.Activation("relu")(layers.MaxPool2D(pool_size=(3, 1))(x))
    x = layers.MaxPool2D(pool_size=(3, 1))(x)
    x = layers.Lambda(lambda t: tf.squeeze(t, 1))(x)
    x = layers.Bidirectional(layers.LSTM(512, return_sequences=True, dropout=0.2))(x)
    x = layers.Bidirectional(layers.LSTM(512, return_sequences=True, dropout=0.2))(x)
    out = layers.Dense(len(CHARS) + 1, activation="softmax")(x)
    m = Model(inp, out)
    m.load_weights(str(WEIGHTS))
    return m


def prep(gray):
    """Như notebook: cao 118, giữ tỉ lệ, đệm phải bằng màu trung vị tới 2167, làm mờ, ngưỡng thích nghi (nét trắng)."""
    h, w = gray.shape
    nw = min(W, max(1, int(H / h * w)))
    g = cv2.resize(gray, (nw, H))
    g = np.pad(g, ((0, 0), (0, W - nw)), "median")
    g = cv2.GaussianBlur(g, (5, 5), 0)
    g = cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 4)
    return (g / 255.0).astype(np.float32)[None, :, :, None]


def greedy(p):
    out, prev = [], -1
    for k in p.argmax(1):
        if k != prev and k != BLANK:
            out.append(CHARS[k])
        prev = k
    return "".join(out)


def encode(text):
    """Tên -> chỉ số ký tự. Ký tự model không có (vd chữ hoa có dấu hiếm) thì thử chữ thường, không có nữa thì bỏ."""
    idx = []
    for c in text:
        if c in CHARS:
            idx.append(CHARS.index(c))
        elif c.lower() in CHARS:
            idx.append(CHARS.index(c.lower()))
    return idx


def ctc_logprob(logp, label):
    """log P(label | ảnh) theo thuật toán forward của CTC (log-space). logp: (T, C) log-softmax."""
    ext = [BLANK]
    for k in label:
        ext += [k, BLANK]
    S, T = len(ext), logp.shape[0]
    a = np.full(S, -np.inf)
    a[0] = logp[0, ext[0]]
    if S > 1:
        a[1] = logp[0, ext[1]]
    for t in range(1, T):
        prev = a
        a = np.full(S, -np.inf)
        for s in range(S):
            v = prev[s]
            if s > 0:
                v = np.logaddexp(v, prev[s - 1])
            if s > 1 and ext[s] != BLANK and ext[s] != ext[s - 2]:
                v = np.logaddexp(v, prev[s - 2])
            a[s] = v + logp[t, ext[s]]
    return float(np.logaddexp(a[-1], a[-2]) if S > 1 else a[-1])


print("Đang nạp CRNN ...", flush=True)
MODEL = build()
sys.path.insert(0, str(ROOT))
from name_verify import CtcScorer  # noqa: E402
SCORER = CtcScorer(CHARS)
LOCK = threading.Lock()  # mạng chạy từng yêu cầu một; /health trả lời ngay cả khi đang bận (máy chủ nhiều luồng)


def read(png_bytes, cands=None):
    g = cv2.imdecode(np.frombuffer(png_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
    with LOCK:
        p = MODEL.predict(prep(g), verbose=0)[0]
    res = {"text": " ".join(greedy(p).split())}
    if cands:
        # Chấm cả danh sách 1 lượt bằng bản CTC tính theo mảng (tools/name_verify.py): ~0,1 giây thay vì vài giây.
        logp = np.log(np.clip(p, 1e-12, 1)).astype(np.float32)
        norm = SCORER.score(logp, cands)          # đã trừ cách đọc tự do tốt nhất, <= 0
        raw = norm + float(logp.max(1).sum())     # log-xác suất CTC gốc, như bản cũ
        res["scores"] = {c: float(v) for c, v in zip(cands, raw)}
        res["norm"] = {c: float(v) for c, v in zip(cands, norm)}
        res["best"] = max(res["scores"], key=res["scores"].get)
    return res


def read_batch(pngs, cands):
    """Nhiều ô họ tên của cùng 1 phiếu, chạy mạng 1 lượt (nhanh hơn hẳn gọi từng ô). Trả [{tên: điểm đã chuẩn hóa}]."""
    x = np.concatenate([prep(cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_GRAYSCALE)) for b in pngs])
    with LOCK:
        p = MODEL.predict(x, batch_size=len(pngs), verbose=0)
    norm = SCORER.score_many(np.log(np.clip(p, 1e-12, 1)).astype(np.float32), cands)  # chấm mọi ô 1 lượt
    return [{c: float(v) for c, v in zip(cands, row)} for row in norm]


class Hd(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send(200, {"ok": True}) if self.path.startswith("/health") else self._send(404, {})

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            t0 = time.time()
            if "images" in body:  # cả phiếu 1 lần
                r = {"norms": read_batch([base64.b64decode(i) for i in body["images"]], body["cands"])}
            else:
                r = read(base64.b64decode(body["image"].split(",", 1)[-1]), body.get("cands"))
            r["ms"] = int((time.time() - t0) * 1000)
            self._send(200, r)
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def log_message(self, fmt, *a):
        if not self.path.startswith("/health"):
            sys.stderr.write("[crnn] " + fmt % a + "\n")


if __name__ == "__main__":
    print(f"Dịch vụ CRNN đọc họ tên chạy ở http://localhost:{PORT}", flush=True)
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Hd)
    srv.daemon_threads = True
    srv.serve_forever()
