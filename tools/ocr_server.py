"""Máy chủ nhận dạng chữ cục bộ cho bản mẫu kiểm phiếu (offline, chạy trên Mac).

Chạy:  .venv/bin/python tools/ocr_server.py
  - http://localhost:8766/            trang kiểm phiếu cho chính máy Mac
  - https://<IP máy Mac>:8443/        trang cho các bàn khác trong mạng nội bộ (cần config/cert.pem, xem tools/make_cert.sh)
Nhiều bàn dùng chung: máy chủ giữ kho phiếu đã duyệt (out/session/state.json), các bàn hỏi /state để cập nhật.
Bản mẫu HTML (cổng 8765) gọi POST /read gửi ảnh phiếu, nhận lại STT từng dòng (engine "none", mặc định:
không đọc họ tên, chỉ báo ô họ tên có chữ hay không). Các engine đọc tên cũ vẫn giữ để thử nghiệm.

Engine: Apple Vision (có sẵn trong macOS) và VietOCR (đọc họ tên; trọng số tải về tools/models/).
Đổi engine: viết hàm có cùng chữ ký như `recognize()` rồi gán vào ENGINES.
Tọa độ ô đọc từ config/ballot_layout.json (mm, gốc trên trái).
"""
import base64
import json
import mimetypes
import os
import re
import ssl
import sys
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np
import Foundation
import Vision

ROOT = Path(__file__).resolve().parent.parent
LAYOUT = json.loads((ROOT / "config" / "ballot_layout.json").read_text(encoding="utf-8"))
PPM = LAYOUT.get("canonical_px_per_mm", 8.0)
W_MM, H_MM = LAYOUT["page_mm"]
INSET = LAYOUT.get("crop_inset_mm", 0.8)
CANON = (int(W_MM * PPM), int(H_MM * PPM))
PORT = int(os.environ.get("KP_PORT", 8766))
DIGIT_FIX = str.maketrans({"O": "0", "o": "0", "D": "0", "Q": "0", "l": "1", "I": "1", "|": "1", "i": "1",
                           "Z": "2", "z": "2", "S": "5", "s": "5", "b": "6", "G": "6", "T": "7", "B": "8", "g": "9", "q": "9"})


# ---------- Apple Vision ----------
def recognize(img_bgr, langs, correction=False, level_accurate=True):
    """Trả về list (text, confidence, x) của các dòng chữ Vision thấy trong ảnh."""
    ok, buf = cv2.imencode(".png", img_bgr)
    data = Foundation.NSData.dataWithBytes_length_(buf.tobytes(), len(buf))
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate if level_accurate else Vision.VNRequestTextRecognitionLevelFast)
    req.setUsesLanguageCorrection_(correction)
    req.setRecognitionLanguages_(langs)
    handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, {})
    ok, err = handler.performRequests_error_([req], None)
    out = []
    for obs in (req.results() or []):
        cand = obs.topCandidates_(1)
        if cand:
            out.append((str(cand[0].string()), float(cand[0].confidence()), float(obs.boundingBox().origin.x)))
    out.sort(key=lambda t: t[2])
    return out


ENGINES = {"apple-vision": recognize}

# ---------- VietOCR (chữ viết tay/in tiếng Việt, đọc từng dòng) ----------
_VIET = {}


def vietocr_predictor():
    """Nạp model VietOCR 1 lần (trọng số ở tools/models/vgg_transformer.pth, tải từ vocr.vn)."""
    if "p" not in _VIET:
        from vietocr.tool.config import Cfg
        from vietocr.tool.predictor import Predictor
        cfg = Cfg.load_config_from_name("vgg_transformer")
        cfg["weights"] = str(ROOT / "tools" / "models" / "vgg_transformer.pth")
        cfg["device"] = "cpu"
        cfg["predictor"]["beamsearch"] = False
        _VIET["p"] = Predictor(cfg)
    return _VIET["p"]


def read_name_vietocr(page, row):
    from PIL import Image
    g = cv2.cvtColor(crop(page, row["name_box"], INSET + 0.5), cv2.COLOR_BGR2GRAY)
    if ink(g) < 0.006:
        return "", 0.9
    h, w = g.shape
    gg = g[int(h * .06):int(h * .94), int(w * .02):int(w * .98)]
    bg = np.percentile(gg, 85)
    ys, xs = np.where(gg < bg - 55)
    if len(xs):
        gg = gg[max(0, ys.min() - 6):ys.max() + 7, max(0, xs.min() - 12):xs.max() + 13]
    gg = cv2.normalize(gg, None, 0, 255, cv2.NORM_MINMAX)
    text, prob = vietocr_predictor().predict(Image.fromarray(gg).convert("RGB"), return_prob=True)
    return re.sub(r"\s+", " ", text).strip(), float(prob)


# ---------- Chữ số viết tay (ô STT): mạng nhỏ huấn luyện trên MNIST ----------
# Apple Vision đọc chữ số viết tay đứng riêng trong ô rất kém (thử thật: "001" ra "VOO" hoặc rỗng),
# nên ô STT dùng mạng riêng (tools/train_digits.py). Thiếu file model thì quay về cách cũ.
_DIG = {}
DIGIT_MODEL = ROOT / "tools" / "models" / "digits_cnn.pt"


def digit_net():
    if "net" not in _DIG:
        _DIG["net"] = None
        if DIGIT_MODEL.exists():
            import importlib.util
            import torch
            spec = importlib.util.spec_from_file_location("train_digits", ROOT / "tools" / "train_digits.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            net = mod.DigitNet()
            net.load_state_dict(torch.load(DIGIT_MODEL, map_location="cpu"))
            net.eval()
            _DIG["net"] = net
    return _DIG["net"]


def to_mnist(gray):
    """Ô chữ số -> ảnh 28x28 kiểu MNIST: nét sáng trên nền đen, chữ nằm gọn 20x20, căn theo trọng tâm.
    Ngưỡng tách nét thích ứng theo độ tương phản của chính ô (bút nhạt/mảnh vẫn ra nét), nối nét đứt
    bằng phép đóng (closing) rồi làm dày nhẹ (dilation) trước khi cắt chữ.
    Bỏ các mẩu viền ô còn sót sát mép (dài, mảnh, chạm mép)."""
    h, w = gray.shape
    bg = np.percentile(gray, 85)
    contrast = max(bg - float(np.percentile(gray, 0.5)), 1)
    inkv = np.clip((bg - gray.astype(np.float32)) / contrast, 0, 1)
    # Ngưỡng theo độ tương phản của chính ô (bút nhạt/mảnh vẫn giữ nét liền), tối thiểu 18 mức xám
    mask = (gray < bg - max(18, 0.4 * contrast)).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(mask, 8)
    keep = np.zeros_like(mask)
    for i in range(1, n):
        x, y, bw, bh, area = st[i]
        # Viền ô sót lại: nét dọc dài mảnh chạm mép trái/phải, hoặc nét ngang dài mảnh chạm mép trên/dưới.
        # (Số 1 cũng dọc, dài, mảnh nhưng nằm giữa ô nên giữ lại.)
        vline = bh > .7 * h and bw < .15 * w and (x == 0 or x + bw >= w)
        hline = bw > .7 * w and bh < .15 * h and (y == 0 or y + bh >= h)
        if area < 12 or vline or hline:
            continue
        keep[lab == i] = 1
    ys, xs = np.where(keep > 0)
    if not len(xs):
        return None
    keep = cv2.dilate(keep, np.ones((3, 3), np.uint8))
    g = (inkv * keep)[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    g = g / max(float(g.max()), 1e-3)
    s = 20 / max(g.shape)
    g = cv2.resize(g, (max(1, round(g.shape[1] * s)), max(1, round(g.shape[0] * s))), interpolation=cv2.INTER_AREA)
    out = np.zeros((28, 28), np.float32)
    y0, x0 = (28 - g.shape[0]) // 2, (28 - g.shape[1]) // 2
    out[y0:y0 + g.shape[0], x0:x0 + g.shape[1]] = g
    m = cv2.moments(out)
    if m["m00"] > 0:
        dx, dy = 14 - m["m10"] / m["m00"], 14 - m["m01"] / m["m00"]
        out = cv2.warpAffine(out, np.float32([[1, 0, dx], [0, 1, dy]]), (28, 28))
    out = out / max(out.max(), 1e-6)
    return (out - 0.1307) / 0.3081


def digit_probs(cells):
    import torch
    with torch.no_grad():
        x = torch.from_numpy(np.stack(cells)[:, None]).float()
        return torch.softmax(digit_net()(x), 1).numpy()


def read_stt_cnn(page, row, stts=None):
    """Đọc 3 ô STT bằng mạng chữ số. Các ô có mực ghép thành số (ô trống bỏ qua, vd chỉ viết "6" ở ô đầu = 6).
    Đọc đúng như nét viết, KHÔNG BAO GIỜ ép về số trong danh sách (số không có trong danh sách phải để
    người duyệt thấy và xử lý thành phiếu hỏng). Ít hơn 3 chữ số -> hạ độ tin cậy (tối đa 0.5) vì phiếu
    yêu cầu đủ 3 chữ số, cần người duyệt xem lại. Tham số stts giữ lại cho tương thích, không dùng.
    Trả (stt '006' hoặc '', độ tin cậy, chuỗi đọc thẳng)."""
    imgs = []
    for cell in snap_cells(page, row):
        # Dòng đã nắn đúng theo khung in sẵn thì cắt sát viền hơn (0,8 mm thay vì 1,4): người viết hay để chữ số
        # dính vạch chia ô, cắt rộng sẽ mất nét (đo 14/11/2026: 11/17 -> 15/17 trên 1 phiếu, phiếu gấp đôi 17/18 -> 18/18).
        g = cv2.cvtColor(crop(page, cell, INSET if _ROWFIX["ok"] else INSET + 0.6), cv2.COLOR_BGR2GRAY)
        # Ô trống thật có mực đúng 0.0; ngưỡng thấp để không bỏ sót nét bút mảnh (vd số "1" mực 0.0086)
        if ink(g) >= 0.003:
            t = to_mnist(g)
            if t is not None:
                imgs.append(t)
    if not imgs:
        return "", 0.9, ""
    P = digit_probs(imgs)
    raw = "".join(str(int(d)) for d in P.argmax(1))
    raw_p = float(np.prod(P.max(1)))
    k = len(imgs)
    conf = raw_p
    if k < 3:
        conf = min(conf, 0.5)
    return raw.zfill(3), conf, raw


# ---------- Nắn ảnh ----------
sys.path.insert(0, str(Path(__file__).resolve().parent))
import row_fix  # noqa: E402

_ROWFIX = {"ok": False}  # lần nắn gần nhất có nắn được từng dòng không (đọc phiếu chạy lần lượt nên dùng chung được)


def decode(data_url):
    raw = base64.b64decode(data_url.split(",", 1)[1])
    return cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)


def align(img):
    """Nắn phiếu về khung chuẩn theo 4 marker ArUco. Không thấy đủ 4 marker thì coi ảnh đã nắn sẵn."""
    try:
        det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, LAYOUT["aruco_dict"])))
        corners, ids, _ = det.detectMarkers(img)
    except Exception:
        corners, ids = None, None
    if ids is not None:
        pts = {int(i): c.reshape(4, 2).mean(axis=0) for i, c in zip(ids.flatten(), corners)}
        if all(m["id"] in pts for m in LAYOUT["markers"]):
            src = np.float32([pts[m["id"]] for m in LAYOUT["markers"]])
            dst = np.float32([[m["center"][0] * PPM, m["center"][1] * PPM] for m in LAYOUT["markers"]])
            M = cv2.getPerspectiveTransform(src, dst)
            page = cv2.warpPerspective(img, M, CANON, flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255))
            # Phiếu gấp / cong: 4 marker không đủ, nắn lại từng dòng theo khung in sẵn (tools/row_fix.py).
            page, n, _ = row_fix.fix_rows(page, LAYOUT, img, M)
            _ROWFIX["ok"] = n > 0
            return page, True
    _ROWFIX["ok"] = False
    return cv2.resize(img, CANON, interpolation=cv2.INTER_CUBIC), False


# ---------- Số phiếu in trên giấy (mã ArUco riêng ở góc trên phải, id = số phiếu) ----------
# Số này là mã phiếu trong hệ thống: quét lại đúng tờ đó thì biết chắc là trùng. Phiếu mẫu cũ không có mã -> None.
SHEET = LAYOUT.get("ballot_id")
_SHEET_DET = {}


def read_sheet(page, aligned, img):
    if not SHEET:
        return None
    try:
        if "det" not in _SHEET_DET:
            _SHEET_DET["det"] = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, SHEET["aruco_dict"])))
        det, views = _SHEET_DET["det"], []
        if aligned:  # tìm quanh chỗ in mã trên ảnh đã nắn trước, không ra thì tìm cả khung hình gốc
            pad, (cx, cy) = SHEET["size"] * 1.5, SHEET["center"]
            x0, y0 = max(int((cx - pad) * PPM), 0), max(int((cy - pad) * PPM), 0)
            views.append(page[y0:int((cy + pad) * PPM), x0:int((cx + pad) * PPM)])
        views.append(img)
        for v in views:
            _, ids, _ = det.detectMarkers(v)
            got = {int(i) for i in ids.flatten()} if ids is not None else set()
            got = {i for i in got if SHEET["first"] <= i <= SHEET["last"]}
            if len(got) == 1:
                return got.pop()
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[ocr] không đọc được số phiếu: {e}\n")
    return None


_DET = {"det": None, "lock": threading.Lock()}


def detect_corners(img):
    """Dò nhanh 4 marker góc trên khung hình nhỏ từ camera (điện thoại gọi liên tục để vẽ viền bám phiếu).
    Trả tọa độ chuẩn hóa 0..1 theo khung hình: góc ngoài của từng marker (đủ 4 -> viền tờ phiếu)."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    with _DET["lock"]:  # 1 bộ dò dùng chung, mỗi lần chỉ ~10 ms nên xếp hàng không đáng kể
        if _DET["det"] is None:
            _DET["det"] = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, LAYOUT["aruco_dict"])))
        corners, ids, _ = _DET["det"].detectMarkers(gray)
    h, w = gray.shape
    found = {}
    if ids is not None:
        for i, c in zip(ids.flatten(), corners):
            found[int(i)] = c.reshape(4, 2)
    want = [m["id"] for m in LAYOUT["markers"]]
    got = [i for i in want if i in found]
    out = {"n": len(got), "w": w, "h": h}
    if len(got) == 4:
        mid = np.mean([found[i].mean(axis=0) for i in want], axis=0)
        quad = [found[i][np.argmax(((found[i] - mid) ** 2).sum(axis=1))] for i in want]
        out["quad"] = [[round(float(x) / w, 4), round(float(y) / h, 4)] for x, y in quad]
    else:
        out["pts"] = [[round(float(found[i].mean(axis=0)[0]) / w, 4), round(float(found[i].mean(axis=0)[1]) / h, 4)] for i in got]
    return out


# ---------- Đọc từng dòng ----------
def crop(page, box, inset=INSET):
    x0, y0 = int((box["x"] + inset) * PPM), int((box["y"] + inset) * PPM)
    x1, y1 = int((box["x"] + box["w"] - inset) * PPM), int((box["y"] + box["h"] - inset) * PPM)
    return page[y0:y1, x0:x1]


SNAP_X_MM, SNAP_Y_MM = 6.0, 3.0  # dò lệch tối đa: ngang ±6 mm, dọc ±3 mm (khoảng hở giữa 2 khung dòng chỉ 2 mm)


def _line_profiles(gray):
    """Mặt nạ đường kẻ dọc / ngang (nét dài, thẳng) trong vùng ảnh xám -> (tổng theo cột, tổng theo hàng)."""
    bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 12)
    v = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, int(6 * PPM))))
    h = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (int(12 * PPM), 1)))
    k = np.ones(3) / 3  # nới 1 px cho đường kẻ hơi nghiêng
    return np.convolve(v.sum(0) / 255.0, k, "same"), np.convolve(h.sum(1) / 255.0, k, "same")


def snap_cells(page, row):
    """Phiếu cong/xô thì 4 marker góc không đủ: dòng giữa/dưới lệch vài mm, ô cắt trúng đường kẻ.
    Dò lại khung 3 ô STT thật quanh vị trí chuẩn (khớp các đường kẻ dọc + cạnh trên/dưới) rồi dịch ô theo.
    Không thấy đường kẻ rõ thì giữ vị trí chuẩn."""
    cells = row["stt_cells"]
    if _ROWFIX["ok"]:
        return cells  # dòng đã được nắn đúng theo khung in sẵn, dò thêm chỉ dễ bắt nhầm đường kẻ của dòng bên cạnh
    x0 = min(c["x"] for c in cells); x1 = max(c["x"] + c["w"] for c in cells)
    y0 = min(c["y"] for c in cells); y1 = max(c["y"] + c["h"] for c in cells)
    mx, my = SNAP_X_MM, SNAP_Y_MM
    X0, Y0 = max(int((x0 - mx) * PPM), 0), max(int((y0 - my) * PPM), 0)
    X1, Y1 = min(int((x1 + mx) * PPM), page.shape[1]), min(int((y1 + my) * PPM), page.shape[0])
    g = cv2.cvtColor(page[Y0:Y1, X0:X1], cv2.COLOR_BGR2GRAY)
    if g.size == 0:
        return cells
    vp, hp = _line_profiles(g)
    xs = sorted({c["x"] for c in cells} | {c["x"] + c["w"] for c in cells})
    ys = [y0, y1]

    def best(prof, pos, origin, m):
        r = int(m * PPM)
        idx = [int(p * PPM) - origin for p in pos]
        scores = []
        for d in range(-r, r + 1):
            s = sum(prof[i + d] for i in idx if 0 <= i + d < len(prof))
            scores.append((s, -abs(d), d))
        s, _, d = max(scores)
        return d if s > 0.5 * len(idx) * 4 * PPM else 0  # cần đường kẻ dài ~4 mm trung bình mỗi vạch

    dx = best(vp, xs, X0, mx) / PPM
    dy = best(hp, ys, Y0, my) / PPM
    if not dx and not dy:
        return cells
    return [dict(c, x=c["x"] + dx, y=c["y"] + dy) for c in cells]


def ink(gray):
    """Tỉ lệ điểm mực (tối hơn nền) trong ô, bỏ viền ô."""
    h, w = gray.shape
    g = gray[int(h * .06):int(h * .94), int(w * .06):int(w * .94)]
    bg = np.percentile(g, 85)
    return float(np.mean(g < bg - 55))


def prep(gray, height):
    g = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(2, 2)).apply(gray)
    s = height / g.shape[0]
    g = cv2.resize(g, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)
    g = cv2.copyMakeBorder(g, 30, 30, 40, 40, cv2.BORDER_CONSTANT, value=255)
    return cv2.cvtColor(g, cv2.COLOR_GRAY2BGR)


def glyph(gray):
    """Cắt sát nét chữ trong 1 ô, đưa về chiều cao chuẩn, nền trắng."""
    h, w = gray.shape
    g = gray[int(h * .06):int(h * .94), int(w * .06):int(w * .94)]
    bg = np.percentile(g, 85)
    mask = (g < bg - 55).astype(np.uint8)
    ys, xs = np.where(mask > 0)
    g = g[max(0, ys.min() - 3):ys.max() + 4, max(0, xs.min() - 3):xs.max() + 4]
    g = cv2.normalize(g, None, 0, 255, cv2.NORM_MINMAX)
    s = 110 / g.shape[0]
    return cv2.resize(g, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)


def read_stt(page, row, engine):
    """Đọc 3 ô STT. Ghép các ô có chữ thành 1 dải ảnh (Vision đọc cả dãy số tốt hơn từng chữ số rời).
    Trả (chuỗi 3 ký tự, ' ' = ô trống, độ tin cậy)."""
    glyphs, idx = [], []
    for i, cell in enumerate(snap_cells(page, row)):
        g = cv2.cvtColor(crop(page, cell, INSET + 0.6), cv2.COLOR_BGR2GRAY)
        if ink(g) >= 0.003:
            glyphs.append(glyph(g)); idx.append(i)
    if not glyphs:
        return "   ", 0.9
    strip = np.full((130, 1, ), 255, np.uint8).reshape(130, 1)
    for gl in glyphs:
        pad = np.full((130, 50), 255, np.uint8)
        top = (130 - gl.shape[0]) // 2
        cell = np.full((130, gl.shape[1]), 255, np.uint8)
        cell[top:top + gl.shape[0], :] = gl
        strip = np.hstack([strip, pad, cell])
    strip = cv2.copyMakeBorder(strip, 20, 20, 60, 60, cv2.BORDER_CONSTANT, value=255)
    res = engine(cv2.cvtColor(strip, cv2.COLOR_GRAY2BGR), ["en-US"], False)
    text = re.sub(r"\D", "", "".join(t for t, _, _ in res).translate(DIGIT_FIX))
    conf = min([c for _, c, _ in res] or [0.1])
    out = [" "] * 3
    if len(text) == len(idx):
        for i, d in zip(idx, text):
            out[i] = d
    else:
        for i in idx:
            out[i] = "?"
        conf = min(conf, .2)
    return "".join(out), conf


def read_name(page, row, engine):
    g = cv2.cvtColor(crop(page, row["name_box"], INSET + 0.5), cv2.COLOR_BGR2GRAY)
    if ink(g) < 0.006:
        return "", 0.9
    res = engine(prep(g, 160), ["vi-VT", "en-US"], False)
    if not res:
        return "?", 0.1
    text = " ".join(t for t, _, _ in res).strip()
    conf = sum(c for _, c, _ in res) / len(res)
    return re.sub(r"\s+", " ", text), conf


QWEN_URL = f"http://127.0.0.1:{os.environ.get('KP_QWEN_PORT', 8767)}/name"


def name_strip(g):
    """Cắt sát phần chữ trong ô họ tên (bỏ khoảng trắng thừa), tăng tương phản."""
    h, w = g.shape
    gg = g[int(h * .06):int(h * .94), int(w * .02):int(w * .98)]
    bg = np.percentile(gg, 85)
    ys, xs = np.where(gg < bg - 55)
    if len(xs):
        gg = gg[max(0, ys.min() - 6):ys.max() + 7, max(0, xs.min() - 12):xs.max() + 13]
    return cv2.normalize(gg, None, 0, 255, cv2.NORM_MINMAX)


def read_name_qwen(page, row):
    """Gửi ảnh ô họ tên sang dịch vụ Qwen (tools/qwen_server.py, môi trường .venv-mlx)."""
    g = cv2.cvtColor(crop(page, row["name_box"], INSET + 0.5), cv2.COLOR_BGR2GRAY)
    if ink(g) < 0.006:
        return "", 0.9
    ok, buf = cv2.imencode(".png", name_strip(g))
    req = urllib.request.Request(QWEN_URL, data=json.dumps({"image": base64.b64encode(buf.tobytes()).decode()}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=120).read())
    except Exception as e:  # noqa: BLE001
        raise RuntimeError("chưa bật dịch vụ Qwen (.venv-mlx/bin/python tools/qwen_server.py)") from e
    if "error" in r:
        raise RuntimeError(r["error"])
    return r["text"], 0.8


CRNN_URL = f"http://127.0.0.1:{os.environ.get('KP_CRNN_PORT', 8768)}/name"


def _post(url, payload, what):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=120).read())
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"chưa bật dịch vụ {what}") from e
    if "error" in r:
        raise RuntimeError(r["error"])
    return r


def _name_png(page, row):
    g = cv2.cvtColor(crop(page, row["name_box"], INSET + 0.5), cv2.COLOR_BGR2GRAY)
    if ink(g) < 0.006:
        return None
    ok, buf = cv2.imencode(".png", name_strip(g))
    return base64.b64encode(buf.tobytes()).decode()


def read_name_crnn(page, row, cands=None):
    """CRNN + CTC (tools/crnn_server.py, môi trường .venv-tf). Có cands thì trả tên trong danh sách
    có xác suất CTC cao nhất (chọn theo danh sách) thay vì chữ đọc tự do."""
    png = _name_png(page, row)
    if png is None:
        return "", 0.9
    r = _post(CRNN_URL, {"image": png, "cands": cands or []}, "CRNN (.venv-tf/bin/python tools/crnn_server.py)")
    return (r["best"] if cands else r["text"]), 0.8


def vietocr_scores(page, row, cands):
    """log-xác suất VietOCR cho từng tên trong danh sách (teacher forcing: đưa sẵn chuỗi, cộng log-xác suất
    từng ký tự + ký tự kết thúc). Ký tự không có trong bảng của VietOCR thì bỏ."""
    import torch
    from PIL import Image
    from vietocr.tool.translate import process_input
    g = cv2.cvtColor(crop(page, row["name_box"], INSET + 0.5), cv2.COLOR_BGR2GRAY)
    p = vietocr_predictor()
    ds = p.config["dataset"]
    img = process_input(Image.fromarray(name_strip(g)).convert("RGB"), ds["image_height"], ds["image_min_width"],
                        ds["image_max_width"]).to(p.config["device"])
    out = {}
    with torch.no_grad():
        for c in cands:
            ids = p.vocab.encode([ch for ch in c if ch in p.vocab.c2i])
            tgt = torch.tensor(ids[:-1]).unsqueeze(1)
            logits = p.model(img, tgt, tgt_key_padding_mask=torch.zeros(1, len(ids) - 1, dtype=torch.bool))
            lp = torch.log_softmax(logits[0], -1)
            out[c] = float(lp[torch.arange(len(ids) - 1), torch.tensor(ids[1:])].sum())
    return out


def read_name_vietocr_list(page, row, cands):
    g = cv2.cvtColor(crop(page, row["name_box"], INSET + 0.5), cv2.COLOR_BGR2GRAY)
    if ink(g) < 0.006:
        return "", 0.9
    sc = vietocr_scores(page, row, cands)
    return max(sc, key=sc.get), 0.8


NAME_READERS = {"vietocr": lambda page, row, eng: read_name_vietocr(page, row),
                "qwen-vl": lambda page, row, eng: read_name_qwen(page, row),
                "crnn-vi": lambda page, row, eng: read_name_crnn(page, row)}
# Biến thể "chọn theo danh sách": không đọc chữ tự do mà chấm điểm từng tên trong danh sách, chọn tên cao nhất.
LIST_READERS = {"crnn-vi-list": read_name_crnn, "vietocr-list": read_name_vietocr_list}


# Ngưỡng "chắc chắn" cho CRNN chọn theo danh sách (đo trên phiếu thật 30/10/2026, ô cắt lệch ±1 mm):
# tên đúng luôn hơn tên kế tiếp >= 13,8 và điểm/ký tự >= -11,5. Dưới ngưỡng thì báo yếu -> giao diện tô vàng.
LIST_MARGIN = 12.0
LIST_PERCHAR = -12.0


CROSS_SIM = 0.5  # Apple Vision đọc tự do phải giống tên được chọn ít nhất mức này, không thì báo yếu


def _plain(s):
    import unicodedata
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").replace("đ", "d").replace("Đ", "D").lower()
    return " ".join("".join(c if c.isascii() and (c.isalnum() or c == " ") else " " for c in s).split())


def _simil(a, b):
    a, b = _plain(a), _plain(b)
    if not a or not b:
        return 0.0
    p = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        c = [i]
        for j in range(1, len(b) + 1):
            c.append(min(p[j] + 1, c[j - 1] + 1, p[j - 1] + (a[i - 1] != b[j - 1])))
        p = c
    return 1 - p[-1] / max(len(a), len(b))


def read_name_crnn_list(page, row, names):
    """Trả (tên trong danh sách có điểm cao nhất, độ tin cậy, yếu?). Ô trống -> ('', .9, False)."""
    png = _name_png(page, row)
    if png is None:
        return "", 0.9, False
    sc = _post(CRNN_URL, {"image": png, "cands": names}, "CRNN (.venv-tf/bin/python tools/crnn_server.py)")["scores"]
    top = sorted(sc.items(), key=lambda kv: -kv[1])
    best, s1 = top[0]
    margin = s1 - top[1][1] if len(top) > 1 else 99.0
    weak = margin < LIST_MARGIN or s1 / max(len(best), 1) < LIST_PERCHAR
    if not weak:
        # Kiểm tra chéo: chọn-theo-danh-sách luôn ra 1 tên có sẵn, kể cả khi phiếu ghi người ngoài danh sách.
        # Apple Vision đọc tự do mà không giống tên được chọn chút nào thì báo yếu để người duyệt xem.
        free, _ = read_name(page, row, ENGINES["apple-vision"])
        weak = _simil(free, best) < CROSS_SIM
    return best, (0.4 if weak else 0.9), weak


def with_page(out, page, aligned):
    if aligned:
        # Trả ảnh đã nắn để giao diện dùng làm "ảnh chụp" (cắt dòng, ảnh ghép) thay cho khung hình gốc.
        ok, buf = cv2.imencode(".jpg", page, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if ok:
            out["page"] = "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()
    return out


def stt_only(page, aligned, stts=None):
    """Chỉ đọc STT (không đọc họ tên). Mỗi dòng báo thêm nameInk: ô họ tên có chữ viết hay không,
    để giao diện nhắc người duyệt khi dòng có STT mà ô tên trống (hoặc ngược lại). Người duyệt tự so tên."""
    rows = []
    for row in LAYOUT["rows"]:
        g = cv2.cvtColor(crop(page, row["name_box"], INSET + 0.5), cv2.COLOR_BGR2GRAY)
        name_ink = ink(g) >= 0.006
        if digit_net() is not None:
            stt, sc, raw = read_stt_cnn(page, row, stts)
        else:
            raw, sc = read_stt(page, row, ENGINES["apple-vision"])
            raw = raw.replace(" ", "")
            stt = "" if "?" in raw else (raw.zfill(3) if raw else "")
        rows.append({"stt": stt, "sttConf": round(sc, 3), "sttRaw": raw, "name": "", "nameInk": name_ink,
                     "unreadable": "?" in raw})
    return with_page({"rows": rows, "aligned": aligned, "nameEngine": "none"}, page, aligned)


def read_page(img, engine_name="crnn-list", stts=None, cands=None):
    """engine_name (đọc họ tên): 'crnn-list' (mặc định: CRNN chọn theo danh sách, cần cands), 'apple-vision',
    'vietocr', 'qwen-vl', 'crnn-vi'. STT luôn đọc bằng mạng chữ số (nếu có model).
    'crnn-list' mà dịch vụ CRNN chưa bật hoặc không có danh sách thì tự quay về Apple Vision."""
    engine = ENGINES["apple-vision"]
    page, aligned = align(img)
    sheet = read_sheet(page, aligned, img)
    if engine_name == "none":
        return dict(stt_only(page, aligned, stts), **({"sheet": sheet} if SHEET else {}))
    names = [c["name"] for c in (cands or []) if c.get("name")]
    used = engine_name
    rows = []
    for row in LAYOUT["rows"]:
        weak = False
        if engine_name == "crnn-list" and names and used == "crnn-list":
            try:
                name, nc, weak = read_name_crnn_list(page, row, names)
            except RuntimeError:
                used = "apple-vision"
        if used != "crnn-list" or not names:
            used = "apple-vision" if used == "crnn-list" else used
            name, nc = NAME_READERS.get(used, lambda p, r, e: read_name(p, r, e))(page, row, engine)
        if digit_net() is not None:
            stt, sc, raw = read_stt_cnn(page, row, stts)
            rows.append({"stt": stt, "sttConf": round(sc, 3), "sttRaw": raw, "name": name, "nameConf": round(nc, 3),
                         "nameWeak": weak, "unreadable": False})
            continue
        stt_raw, sc = read_stt(page, row, engine)
        stt = stt_raw.replace(" ", "")
        if "?" in stt:
            stt = ""  # có ô có mực nhưng không đọc được chữ số
        rows.append({"stt": stt.zfill(3) if stt else "", "sttConf": round(sc, 3), "name": name, "nameConf": round(nc, 3),
                     "unreadable": "?" in stt_raw})
    return with_page({"rows": rows, "aligned": aligned, "nameEngine": used, **({"sheet": sheet} if SHEET else {})}, page, aligned)


# ---------- Kiểm chéo họ tên với STT (chạy nền) + chữ ghi dưới dòng cuối ----------
# /read trả STT ngay như cũ. Nếu dịch vụ CRNN và Qwen đang bật thì phiếu được xếp hàng kiểm tên ở nền;
# giao diện hỏi GET /names?scan=<mã> vài giây 1 lần. Mỗi dòng trả "top": STT của 3 người có tên khớp chữ viết nhất.
# Giao diện tô vàng dòng nào mà STT đang ghi không nằm trong 2 người đầu. Cách chấm: tools/name_verify.py.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import name_verify as nv  # noqa: E402
import outside_ink  # noqa: E402

NAMES = {}            # mã bản quét -> {"state": "wait" | "done" | "error", "rows": [...]}
NAMES_KEEP = 300
_SVC = {"t": 0.0, "ok": False}


def _svc_alive(url):
    """Dịch vụ còn bật không. Đang bận nên chưa kịp trả lời (hết giờ chờ) vẫn tính là đang bật: chỉ khi không nối
    được mới là tắt. Cách cũ coi "chậm trả lời" là tắt nên lúc đông máy bỏ kiểm tên của khoảng 1/3 số phiếu."""
    try:
        urllib.request.urlopen(url.rsplit("/", 1)[0] + "/health", timeout=2).read()
        return True
    except Exception as e:  # noqa: BLE001
        return isinstance(getattr(e, "reason", e), TimeoutError)


def name_services_up():
    """CRNN và Qwen có đang bật không (hỏi lại sau mỗi 10 giây)."""
    if time.time() - _SVC["t"] > 10:
        _SVC.update(t=time.time(), ok=all(_svc_alive(u) for u in (CRNN_URL, QWEN_URL)))
    return _SVC["ok"]


def _viet_parts():
    p = vietocr_predictor()
    p.model.eval()  # tắt dropout (translate() của VietOCR tự làm việc này; ở đây gọi thẳng vào mạng nên phải tự làm)
    return p.config["dataset"], p.vocab, p.model


def viet_encode(strip):
    """Ảnh 1 ô họ tên -> đặc trưng của VietOCR (S, 1, D)."""
    import torch
    from PIL import Image
    from vietocr.tool.translate import process_input
    ds, _, m = _viet_parts()
    with torch.no_grad():
        img = process_input(Image.fromarray(strip).convert("RGB"), ds["image_height"], ds["image_min_width"], ds["image_max_width"])
        return m.transformer.forward_encoder(m.cnn(img))


def viet_free(mems):
    """VietOCR tự đọc từng ô, mọi ô của phiếu trong cùng 1 lượt giải mã (cách cũ: mỗi ô 1 lượt riêng, chậm hơn ~4 lần).
    Ô ngắn hơn được đệm và che phần đệm, nên chữ đọc ra như khi chạy riêng từng ô."""
    import math
    import torch
    _, V, m = _viet_parts()
    tr = m.transformer
    B, S = len(mems), max(x.shape[0] for x in mems)
    with torch.no_grad():
        memory = torch.zeros(S, B, mems[0].shape[2])
        pad = torch.zeros(B, S)
        for i, x in enumerate(mems):
            memory[:x.shape[0], i] = x[:, 0]
            pad[i, x.shape[0]:] = float("-inf")
        seq, done = [[V.go] * B], [False] * B
        while len(seq) <= 129 and not all(done):  # cùng giới hạn độ dài với translate() của VietOCR
            tgt = torch.LongTensor(seq)
            x = tr.pos_enc(tr.embed_tgt(tgt) * math.sqrt(tr.d_model))
            out = tr.transformer.decoder(x, memory, tgt_mask=tr.gen_nopeek_mask(len(seq)), memory_key_padding_mask=pad)
            nxt = tr.fc(out[-1]).argmax(-1).tolist()
            seq.append(nxt)
            done = [d or k == V.eos for d, k in zip(done, nxt)]
    return [V.decode([row[i] for row in seq]) for i in range(B)]


def viet_score(mem, names, free):
    """VietOCR chấm từng tên (chữ thường và CHỮ HOA, lấy điểm cao hơn), trừ điểm chuỗi nó tự đọc (free). Trả mảng (N,)."""
    import torch
    _, V, m = _viet_parts()
    with torch.no_grad():
        ids = [V.encode([ch for ch in t if ch in V.c2i]) for t in names + [n.upper() for n in names] + [free]]
        A = torch.zeros(max(map(len, ids)), len(ids), dtype=torch.long)
        for i, x in enumerate(ids):
            A[:len(x), i] = torch.tensor(x)
        lp = torch.log_softmax(m.transformer.forward_decoder(A[:-1], mem.repeat(1, len(ids), 1))[0], -1)
        tgt = A[1:].T
        sc = (lp.gather(2, tgt.unsqueeze(-1)).squeeze(-1) * (tgt != 0)).sum(1).numpy()
    sc = sc[:-1] - sc[-1]
    return np.maximum(sc[:len(names)], sc[len(names):])


def viet_list_scores(strip, names):
    """Bản 1 ô (dùng khi thử nghiệm): như viet_encode + viet_free + viet_score."""
    mem = viet_encode(strip)
    return viet_score(mem, names, viet_free([mem])[0])


SUGGEST_SIM = 0.75  # đo trên 206 ô: giữ nút gợi ý cho 146/189 gợi ý đúng, còn 4/17 gợi ý sai vẫn lọt
VIET_TOP = 25  # VietOCR chỉ chấm 25 người CRNN xếp đầu + người theo STT (đo: kết quả như chấm cả 201, nhanh hơn ~8 lần)

# Kiểm tên 1 phiếu đi qua 3 chặng, mỗi chặng 1 luồng riêng nên 3 phiếu khác nhau chạy cùng lúc ở 3 máy đọc:
#   crnn: CRNN chấm cả danh sách cho mọi dòng có chữ trong 1 lượt (tiến trình .venv-tf)
#   viet: VietOCR chấm nhóm đầu của CRNN. Người mang STT máy đọc được là người khớp tên nhất -> dòng qua (fast)
#   qwen: dòng chưa qua mới hỏi thêm Qwen (~1 giây/dòng, tiến trình .venv-mlx) rồi ghép cả ba
# Đo 14/11/2026 trên 206 ô đã duyệt: 74% dòng qua ở chặng viet, không lọt dòng nào trong 13 dòng STT lệch tên.
# Mỗi chặng lấy phiếu MỚI NHẤT trước: lúc đông máy, phiếu vừa chụp (người quét còn đang xem) được kiểm trước,
# phiếu cũ (đã bấm Chấp nhận rồi) kiểm sau khi vãn.


def _names_crnn(job):
    names = [c["name"] for c in job["cands"]]
    todo = []
    for row, stt in zip(LAYOUT["rows"], job["stts"]):
        g = cv2.cvtColor(crop(job["page"], row["name_box"], INSET + 0.5), cv2.COLOR_BGR2GRAY)
        if ink(g) >= 0.006:
            strip = name_strip(g)
            todo.append((row["index"], stt, strip, base64.b64encode(cv2.imencode(".png", strip)[1].tobytes()).decode()))
    job.update(todo=todo, names=names, code=[f"{int(c['stt']):03d}" for c in job["cands"]], rows=[], slow=[])
    job.pop("page")
    if not todo:
        return False
    norms = _post(CRNN_URL, {"images": [t[3] for t in todo], "cands": names}, "CRNN")["norms"]
    job["crnn"] = [np.array([norm[n] for n in names]) for norm in norms]
    return True


class _name_turn:
    """Khóa đọc cho chặng VietOCR, nhường phiếu đang chờ đọc STT: người quét đang đứng chờ kết quả đọc, còn kiểm tên
    chạy nền. Không nhường thì luồng kiểm tên nhả khóa xong lấy lại ngay, phiếu mới phải chờ vài giây."""

    def __enter__(self):
        while True:
            while _WAIT["n"]:
                time.sleep(0.005)
            READ_LOCK.acquire()
            if not _WAIT["n"]:
                return
            READ_LOCK.release()

    def __exit__(self, *a):
        READ_LOCK.release()


def _names_viet(job):
    names, code = job["names"], job["code"]
    # VietOCR và mạng chữ số cùng dùng torch trong tiến trình này: không chạy chồng nhau. Khóa từng đoạn ngắn
    # để phiếu đang chờ đọc STT chen vào được giữa chừng.
    mems = []
    for t in job["todo"]:
        with _name_turn():
            mems.append(viet_encode(t[2]))
    with _name_turn():
        frees = viet_free(mems)
    for (line, stt, _, png), crnn, mem, free in zip(job["todo"], job["crnn"], mems, frees):
        s = code.index(stt) if stt in code else None
        idx = sorted(set(np.argsort(-crnn)[:VIET_TOP].tolist()) | ({s} if s is not None else set()))
        with _name_turn():
            part = viet_score(mem, [names[i] for i in idx], free)
        vt = np.full(len(names), part.min())  # người không được chấm: coi như điểm thấp nhất
        vt[idx] = part
        score = nv._z(crnn + nv.W_VIET * vt)
        fast = s is not None and int(np.argmax(score)) == s
        row = {"line": line, "fast": fast, "sure": True, "top": [code[i] for i in np.argsort(-score)[:3]]}
        job["rows"].append(row)
        if not fast:
            job["slow"].append((row, crnn, vt, png))
    job.pop("todo")
    return bool(job["slow"])


def _names_qwen(job):
    names, code = job["names"], job["code"]
    for row, crnn, vt, png in job["slow"]:
        text = _post(QWEN_URL, {"image": png}, "Qwen")["text"]
        score = nv.fuse(crnn, vt, text, names)
        # Chữ Qwen chép ra phải giống tên người đứng đầu ở mức SUGGEST_SIM thì giao diện mới mời "Đổi sang <STT>".
        # Dưới mức đó (chữ khó đọc, hoặc tên ngoài danh sách) chỉ báo không khớp và cho xem chữ máy đọc được.
        row.update(read=text, sure=nv.sim(text, names[int(np.argmax(score))]) >= SUGGEST_SIM,
                   top=[code[i] for i in np.argsort(-score)[:3]])
    return False


_STAGES = (("crnn", _names_crnn), ("viet", _names_viet), ("qwen", _names_qwen))
_NAMEQ = {k: [] for k, _ in _STAGES}  # hàng chờ của từng chặng
_NAMEQ_CV = threading.Condition()


def name_check_page(page, stts, cands):
    """Kiểm 1 phiếu ngay, lần lượt 3 chặng (dùng khi thử nghiệm / chấm điểm). Trả
    [{"line", "top": [STT của 3 người khớp chữ viết nhất], "fast", "sure", "read"}] cho các dòng có chữ ở ô họ tên."""
    job = {"page": page, "stts": stts, "cands": cands}
    for _, fn in _STAGES:
        if not fn(job):
            break
    return job["rows"]


def _names_done(job, error=None):
    scan = job["scan"]
    if error is None:
        res = {"state": "done", "rows": job.get("rows", []), "ms": int((time.time() - job["t0"]) * 1000)}
    else:
        sys.stderr.write(f"[ocr] kiểm tên lỗi ({scan}): {error}\n")
        res = {"state": "error", "rows": [], "error": str(error)}
        _SVC["t"] = 0.0
    NAMES[scan] = res
    try:
        (SCANS / scan / "names.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass


def _name_worker(k):
    stage, fn = _STAGES[k]
    while True:
        with _NAMEQ_CV:
            while not _NAMEQ[stage]:
                _NAMEQ_CV.wait()
            job = _NAMEQ[stage].pop()  # phiếu mới nhất trước
        try:
            more = fn(job)
        except Exception as e:  # noqa: BLE001
            _names_done(job, e)
            continue
        if not more:
            _names_done(job)
        else:
            with _NAMEQ_CV:
                _NAMEQ[_STAGES[k + 1][0]].append(job)
                _NAMEQ_CV.notify_all()


def start_name_workers():
    for k in range(len(_STAGES)):
        threading.Thread(target=_name_worker, args=(k,), daemon=True).start()


def queue_name_check(scan, page, rows, cands):
    """Xếp phiếu vào hàng kiểm tên. Trả "wait" nếu đã xếp, "off" nếu chưa đủ điều kiện (dịch vụ tắt, chưa có danh sách)."""
    if not scan or not cands or not name_services_up():
        return "off"
    NAMES[scan] = {"state": "wait", "rows": []}
    while len(NAMES) > NAMES_KEEP:
        NAMES.pop(next(iter(NAMES)))
    with _NAMEQ_CV:
        _NAMEQ["crnn"].append({"scan": scan, "t0": time.time(), "page": page, "stts": [r.get("stt", "") for r in rows], "cands": cands})
        _NAMEQ_CV.notify_all()
    return "wait"


def names_result(scan):
    if scan in NAMES:
        return NAMES[scan]
    f = SCANS / scan / "names.json"
    if re.fullmatch(r"\d{8}-\d{6}(-\d+)?", scan) and f.is_file():
        return json.loads(f.read_text(encoding="utf-8"))
    return {"state": "off", "rows": []}


# ---------- Lưu từng lần quét để soi lỗi ----------
SCANS = Path(os.environ.get("KP_SCANS") or ROOT / "out" / "scans")


def save_scan(img, out, engine):
    """Mỗi lần đọc lưu 1 thư mục: ảnh gốc, ảnh đã nắn (nếu nắn được), kết quả đọc. Lỗi ghi file thì bỏ qua."""
    try:
        base = time.strftime("%Y%m%d-%H%M%S")
        d, i = SCANS / base, 1
        while d.exists():
            i += 1
            d = SCANS / f"{base}-{i}"
        d.mkdir(parents=True)
        cv2.imwrite(str(d / "frame.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if out.get("page"):
            (d / "page.jpg").write_bytes(base64.b64decode(out["page"].split(",", 1)[1]))
        meta = {k: v for k, v in out.items() if k != "page"}
        meta["engine"] = engine
        meta["frame_size"] = [int(img.shape[1]), int(img.shape[0])]
        (d / "result.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return d.name
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[ocr] không lưu được bản quét: {e}\n")
        return None


def save_label(body):
    """Đáp án sau khi người duyệt bấm Chấp nhận (phiếu điện tử đã giống phiếu giấy) -> truth.json cạnh bản quét.
    Dùng để chấm điểm các engine (tools/bench_names.py). Bản sau ghi đè bản trước (vd mở lại phiếu để sửa)."""
    name = str(body.get("scan", ""))
    if not re.fullmatch(r"\d{8}-\d{6}(-\d+)?", name) or not (SCANS / name).is_dir():
        raise ValueError("mã bản quét không hợp lệ")
    keep = {k: body.get(k) for k in ("rows", "status", "reason", "cands", "ballot")}
    keep["saved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    (SCANS / name / "truth.json").write_text(json.dumps(keep, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------- Hàng đợi đọc: nhiều bàn gửi cùng lúc thì đọc lần lượt từng phiếu ----------
# Mạng chữ số + OpenCV không nên chạy song song trong cùng tiến trình; đọc 1 phiếu chỉ vài chục ms nên xếp hàng là đủ.
READ_LOCK = threading.Lock()
_WAIT = {"n": 0}
_WAIT_LOCK = threading.Lock()


def read_queued(img, engine, stts, cands):
    with _WAIT_LOCK:
        ahead = _WAIT["n"]
        _WAIT["n"] += 1
    t0 = time.time()
    try:
        with READ_LOCK:
            t1 = time.time()
            out = read_page(img, engine, stts, cands)
            out["ms"] = int((time.time() - t1) * 1000)
    finally:
        with _WAIT_LOCK:
            _WAIT["n"] -= 1
    out["waitMs"] = int((t1 - t0) * 1000)
    out["queued"] = ahead
    return out


# ---------- Nhận ra phiếu quét 2 lần (kể cả ở 2 bàn khác nhau) ----------
# Phiếu ẩn danh, không có mã, nên so "dấu vân tay" nét mực trong các ô (đã nắn thẳng theo 4 góc).
# Đo trên phiếu thật 07/11/2026: cùng 1 tờ chụp lại giống 0,998; nắn lệch ~0,5 mm vẫn 0,94.
# Điều kiện báo trùng: giống >= DUP_SIM VÀ STT đọc được trùng hết từng dòng. Chỉ cảnh báo, người duyệt quyết.
DUP_SIM = 0.90


def fingerprint(page):
    vs = []
    for row in LAYOUT["rows"]:
        for box, size in [(c, (12, 12)) for c in row["stt_cells"]] + [(row["name_box"], (96, 14))]:
            g = cv2.cvtColor(crop(page, box, INSET + 1.0), cv2.COLOR_BGR2GRAY).astype(np.float32)
            bg = np.percentile(g, 85)
            m = cv2.GaussianBlur(np.clip((bg - g - 25) / 60, 0, 1), (0, 0), 5)
            vs.append(cv2.resize(m, size, interpolation=cv2.INTER_AREA).ravel())
    v = np.concatenate(vs).astype(np.float32)
    return v


def similar(a, b):
    a = a - a.mean()
    b = b - b.mean()
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    return float(a @ b / (na * nb)) if na > 1e-6 and nb > 1e-6 else 0.0


# ---------- Kho phiếu chung của phiên (lưu ra ổ đĩa sau mỗi thay đổi) ----------
SESSION = Path(os.environ.get("KP_SESSION") or ROOT / "out" / "session")  # KP_SESSION: thư mục khác khi chạy thử
STATE_FILE = SESSION / "state.json"
SCAN_ID = re.compile(r"\d{8}-\d{6}(-\d+)?")


class Store:
    """Một phiên kiểm phiếu dùng chung cho mọi bàn. rev tăng sau mỗi thay đổi; bàn nào hỏi /state?since=rev
    chỉ nhận phần thay đổi. epoch đổi khi xóa phiên để các bàn biết mà tải lại từ đầu."""

    def __init__(self):
        self.lock = threading.Lock()
        self.fps = {}  # scanId -> (vân tay, [STT từng dòng], số phiếu in trên giấy hoặc None)
        try:
            self.s = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            self.s = None
        if not self.s:
            self.s = self._empty()
        for b in self.s["ballots"].values():
            self._load_fp(b.get("scanId"))

    @staticmethod
    def _empty():
        return {"epoch": int(time.time() * 1000), "rev": 0, "nextNo": 1, "cfg": None, "cands": None,
                "locked": None, "ballots": {}, "log": []}

    def _load_fp(self, scan):
        if scan and scan not in self.fps and SCAN_ID.fullmatch(scan):
            try:
                d = SCANS / scan
                fp = np.load(d / "fp.npy")
                res = json.loads((d / "result.json").read_text(encoding="utf-8"))
                self.fps[scan] = (fp, [r.get("stt", "") for r in res.get("rows", [])], res.get("sheet"))
            except Exception:  # noqa: BLE001
                pass

    def _save(self):
        SESSION.mkdir(parents=True, exist_ok=True)
        tmp = STATE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.s, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, STATE_FILE)

    def _bump(self, text=None, who=""):
        self.s["rev"] += 1
        if text:
            self.s["log"].insert(0, {"t": int(time.time() * 1000), "who": who, "text": text})
            del self.s["log"][500:]
        self._save()
        return self.s["rev"]

    def snapshot(self, since=0, epoch=None):
        with self.lock:
            s = self.s
            full = epoch != s["epoch"]
            bs = [b for b in s["ballots"].values() if full or b.get("rev", 0) > since]
            return {"epoch": s["epoch"], "rev": s["rev"], "full": full, "nextNo": s["nextNo"], "cfg": s["cfg"],
                    "cands": s["cands"], "locked": s["locked"], "ballots": bs, "log": s["log"][:200]}

    def next_no(self):
        """Mã cho phiếu không đọc được số in trên giấy. Lấy từ FREE_NO trở lên để không đụng số phiếu in sẵn."""
        with self.lock:
            n = max(self.s["nextNo"], FREE_NO)
            self.s["nextNo"] = n + 1
            self._bump()
            return n

    def put_ballot(self, b, who):
        """Ghi phiếu đã duyệt. version của phiếu gửi lên phải đúng bằng bản trên máy chủ + 1, không thì có bàn
        khác vừa sửa phiếu này -> từ chối (409) và trả bản hiện có để bàn này tải lại."""
        with self.lock:
            if self.s["locked"]:
                return 423, {"error": "Phiên đã chốt kết quả, không ghi nhận thêm."}
            no = str(int(b["no"]))
            cur = self.s["ballots"].get(no)
            have = cur["version"] if cur else 0
            if cur and int(b.get("version", 1)) == 1:  # phiếu mới mà mã đã có: cùng 1 tờ giấy quét 2 lần
                return 409, {"error": f"Phiếu #{int(no):03d} đã được ghi nhận ({cur.get('station', '')}). Tờ này quét trùng, không tính lần 2.",
                             "current": cur}
            if int(b.get("version", 1)) != have + 1:
                return 409, {"error": "Phiếu này vừa được bàn khác sửa.", "current": cur}
            b = {k: v for k, v in b.items() if k not in ("composite", "crops", "raw", "snapshot", "reopened",
                                                          "pending", "reading", "rescanning", "cropping")}
            if b.get("scanId") and SCAN_ID.fullmatch(str(b["scanId"])) and str(b.get("photo", "")).startswith("data:"):
                d = SCANS / b["scanId"]
                b["photo"] = f"/scans/{b['scanId']}/{'page' if (d / 'page.jpg').exists() else 'frame'}.jpg"
            self.s["nextNo"] = max(self.s["nextNo"], int(no) + 1)
            self._load_fp(b.get("scanId"))
            b["sheet"] = (self.fps.get(b.get("scanId")) or (None, None, None))[2]  # lấy từ bản quét, không tin máy gửi lên
            b["rev"] = self.s["rev"] + 1
            self.s["ballots"][no] = b
            self._bump(f"{'Ghi nhận' if not cur else 'Sửa'} phiếu #{int(no):03d} ({b.get('station', '')}): {b.get('status')}"
                       + (" · gắn cờ nhờ duyệt" if b.get("flag") and not (b["flag"] or {}).get("done") else ""), who)
            return 200, {"ok": True, "rev": self.s["rev"], "photo": b.get("photo")}

    def set_flag(self, body, who):
        """Cờ "nhờ máy tính duyệt" do điện thoại gắn lên phiếu. Máy tính duyệt xong thì ghi done (ai, lúc nào);
        bỏ duyệt thì xóa done. Không đổi version phiếu (nội dung phiếu không đổi), chỉ tăng rev để các bàn cập nhật."""
        with self.lock:
            no = str(int(body["no"]))
            b = self.s["ballots"].get(no)
            if not b or not b.get("flag"):
                return 404, {"error": "Phiếu này không có cờ."}
            b["flag"]["done"] = {"by": who, "at": int(time.time() * 1000)} if body.get("done") else None
            b["rev"] = self.s["rev"] + 1
            self._bump(f"{'Duyệt cờ' if body.get('done') else 'Bỏ duyệt cờ'} phiếu #{int(no):03d}", who)
            return 200, {"ok": True, "flag": b["flag"]}

    def put_cfg(self, body, who):
        with self.lock:
            s = self.s
            if "cands" in body and body["cands"] != s["cands"]:
                if s["ballots"] and s["cands"] is not None:
                    return 409, {"error": "Đã có phiếu, không sửa danh sách được."}
                s["cands"] = body["cands"]
            if "cfg" in body:
                s["cfg"] = body["cfg"]
            if "locked" in body:
                s["locked"] = body["locked"]
            return 200, {"ok": True, "rev": self._bump(body.get("note"), who)}

    def wipe(self, who):
        with self.lock:
            keep = {"cfg": self.s["cfg"], "cands": self.s["cands"]}
            if self.s["ballots"]:
                SESSION.mkdir(parents=True, exist_ok=True)
                (SESSION / f"state-xoa-{time.strftime('%Y%m%d-%H%M%S')}.json").write_text(
                    json.dumps(self.s, ensure_ascii=False), encoding="utf-8")  # giữ bản cũ phòng xóa nhầm
            self.s = self._empty()
            self.s.update(keep)
            self._bump("Xóa dữ liệu phiên", who)
            return 200, {"ok": True}

    def find_dup(self, fp, stts, scan, no, sheet=None, editing=False):
        """Phiếu đã ghi nhận nào trùng phiếu vừa quét.
        Có số phiếu in trên giấy: trùng số là trùng chắc chắn ("exact"), trừ khi đang mở lại chính phiếu đó để sửa (editing).
        Không có số: so vân tay nét mực như trước, bỏ qua chính phiếu đang quét lại (cùng mã phiếu no)."""
        with self.lock:
            if sheet is not None:
                for b in self.s["ballots"].values():
                    if b.get("sheet") == sheet and not (editing and str(b.get("no")) == str(no)):
                        return {"no": b["no"], "station": b.get("station", ""), "sim": 1.0, "exact": True}
            if fp is None or not any(stts):
                return None  # phiếu trắng tờ nào cũng giống nhau, không so
            best = None
            for b in self.s["ballots"].values():
                if str(b.get("no")) == str(no) or not b.get("scanId") or b["scanId"] == scan:
                    continue
                hit = self.fps.get(b["scanId"])
                if not hit or hit[1] != stts:
                    continue
                if sheet is not None and hit[2] is not None:
                    continue  # 2 tờ đều có số và số khác nhau: chắc chắn là 2 tờ giấy khác nhau
                sim = similar(fp, hit[0])
                if sim >= DUP_SIM and (best is None or sim > best["sim"]):
                    best = {"no": b["no"], "station": b.get("station", ""), "sim": round(sim, 3)}
            return best


STORE = None
# Mã cấp cho phiếu không có / không đọc được số in: bắt đầu sau dải số in sẵn (in 1..200 -> cấp từ 1001)
FREE_NO = (SHEET["last"] // 1000 + 1) * 1000 + 1 if SHEET else 1

# ---------- Các máy đang kết nối ----------
# Mỗi máy (điện thoại/máy tính) hỏi /state 1,5–2 giây/lần, kèm tên máy (X-Station). Im quá ONLINE_S giây = đã ngắt.
ONLINE_S = 10
DEVICES = {}  # (tên, IP) -> {name, ip, kind, first, last}
DEV_LOCK = threading.Lock()


def seen(name, ip, ua):
    now = int(time.time() * 1000)
    with DEV_LOCK:
        d = DEVICES.setdefault((name, ip), {"name": name, "ip": ip, "first": now})
        d["last"] = now
        d["kind"] = "phone" if re.search(r"Mobile|Android|iPhone|iPad", ua or "") else "desktop"


def devices():
    now = int(time.time() * 1000)
    with DEV_LOCK:
        for k in [k for k, d in DEVICES.items() if now - d["last"] > 6 * 3600 * 1000]:
            del DEVICES[k]  # quên máy đã ngắt lâu
        out = [dict(d, online=now - d["last"] <= ONLINE_S * 1000) for d in DEVICES.values()]
    names = [d["name"] for d in out if d["online"]]
    for d in out:
        d["dupName"] = d["online"] and names.count(d["name"]) > 1  # 2 máy cùng tên -> khó biết phiếu do máy nào quét
    return sorted(out, key=lambda d: (not d["online"], d["kind"] != "phone", d["name"]))


# ---------- Mã QR để điện thoại vào nhanh ----------
def lan_ip():
    """IP máy Mac trong mạng nội bộ (Wi-Fi en0, dây en1...). Không có mạng thì trả None."""
    import subprocess
    for nic in ("en0", "en1", "en2", "en3"):
        try:
            ip = subprocess.run(["ipconfig", "getifaddr", nic], capture_output=True, text=True, timeout=2).stdout.strip()
        except Exception:  # noqa: BLE001
            ip = ""
        if ip:
            return ip
    return None


def phone_url():
    ip = lan_ip()
    return f"https://{ip}:{HTTPS_PORT}/" if ip else None


def qr_png(text, scale=10, quiet=4):
    """Ảnh PNG mã QR (dùng bộ tạo QR có sẵn trong OpenCV, không cần thư viện thêm)."""
    q = cv2.QRCodeEncoder.create().encode(text)
    q = cv2.copyMakeBorder(q, quiet, quiet, quiet, quiet, cv2.BORDER_CONSTANT, value=255)
    q = cv2.resize(q, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
    return cv2.imencode(".png", q)[1].tobytes()


# ---------- HTTP ----------
WEB = ROOT / "docs" / "ballot-scan" / "html-design"
HOME = "/ballot-scan-prototype.html"
PHONE = "/ballot-scan-phone.html"


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path):
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", (mimetypes.guess_type(path.name)[0] or "application/octet-stream")
                         + ("; charset=utf-8" if path.suffix in (".html", ".js", ".css") else ""))
        self.send_header("Cache-Control", "no-store" if path.suffix == ".html" else "max-age=3600")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")

    def _who(self):
        return urllib.parse.unquote(self.headers.get("X-Station", "")) or self.client_address[0]

    def do_OPTIONS(self):
        self.send_response(204)
        for k, v in (("Access-Control-Allow-Origin", "*"), ("Access-Control-Allow-Methods", "POST, GET, OPTIONS"),
                     ("Access-Control-Allow-Headers", "Content-Type, X-Station"), ("Access-Control-Allow-Private-Network", "true"),
                     ("Content-Length", "0")):
            self.send_header(k, v)
        self.end_headers()

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        if u.path.startswith("/health"):
            return self._send(200, {"ok": True, "engine": "none", "shared": True})
        if u.path == "/names":
            return self._send(200, names_result(q.get("scan", [""])[0]))
        if u.path == "/phone-url":
            return self._send(200, {"url": phone_url(), "https": CERT.exists() and KEY.exists()})
        if u.path == "/qr.png":
            url = phone_url()
            if not url:
                return self._send(503, {"error": "Máy Mac chưa nối mạng nội bộ"})
            data = qr_png(url)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return self.wfile.write(data)
        if u.path == "/state":
            ep = q.get("epoch", [None])[0]
            name = urllib.parse.unquote(self.headers.get("X-Station", "")).strip()
            if name:
                seen(name, self.client_address[0], self.headers.get("User-Agent", ""))
            snap = STORE.snapshot(int(q.get("since", ["0"])[0] or 0), int(ep) if ep else None)
            snap["devices"] = devices()
            return self._send(200, snap)
        if u.path == "/":
            # Điện thoại vào địa chỉ gốc -> trang quét cho điện thoại; máy tính -> trang tổng hợp/duyệt đầy đủ.
            mobile = re.search(r"Mobile|Android|iPhone|iPad", self.headers.get("User-Agent", ""))
            self.send_response(302)
            self.send_header("Location", PHONE if mobile else HOME)
            self.send_header("Content-Length", "0")
            return self.end_headers()
        m = re.fullmatch(r"/scans/(\d{8}-\d{6}(?:-\d+)?)/(page|frame)\.jpg", u.path)
        if m and (SCANS / m[1] / f"{m[2]}.jpg").is_file():
            return self._file(SCANS / m[1] / f"{m[2]}.jpg")
        name = u.path.lstrip("/")
        if re.fullmatch(r"[\w.\-]+\.(html|js|css|png|jpg|svg|ico)", name) and (WEB / name).is_file():
            return self._file(WEB / name)
        self._send(404, {"error": "not found"})

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        try:
            if self.path.startswith("/detect"):  # ảnh JPEG thô (không base64) để gửi nhanh nhiều lần/giây
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
                if img is None:
                    return self._send(400, {"error": "ảnh hỏng"})
                return self._send(200, detect_corners(img))
            # Luôn đọc hết phần thân trước: kết nối giữ mở (keep-alive), phần thân còn sót sẽ dính vào yêu cầu sau.
            body = self._body()
            if self.path.startswith("/label"):
                save_label(body)
                return self._send(200, {"ok": True})
            if self.path.startswith("/next"):
                return self._send(200, {"no": STORE.next_no()})
            if self.path.startswith("/ballot"):
                return self._send(*STORE.put_ballot(body["ballot"], self._who()))
            if self.path.startswith("/flag"):
                return self._send(*STORE.set_flag(body, self._who()))
            if self.path.startswith("/cfg"):
                return self._send(*STORE.put_cfg(body, self._who()))
            if self.path.startswith("/wipe"):
                return self._send(*STORE.wipe(self._who()))
            if not self.path.startswith("/read"):
                return self._send(404, {"error": "not found"})
            img = decode(body["image"])
            out = read_queued(img, body.get("engine", "none"), body.get("stts"), body.get("cands"))
            out["scan"] = save_scan(img, out, out.get("nameEngine", body.get("engine")))
            if out.get("aligned") and out.get("page") and out["scan"]:
                page = cv2.imdecode(np.frombuffer(base64.b64decode(out["page"].split(",", 1)[1]), np.uint8), cv2.IMREAD_COLOR)
                fp = fingerprint(page)
                np.save(SCANS / out["scan"] / "fp.npy", fp)
                out["dupOf"] = STORE.find_dup(fp, [r["stt"] for r in out["rows"]], out["scan"], body.get("no"),
                                              out.get("sheet"), bool(body.get("editing")))
                out["below"] = outside_ink.below_rows(page, LAYOUT)
                out["names"] = queue_name_check(out["scan"], page, out["rows"], STORE.s.get("cands"))
            self._send(200, out)
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def log_message(self, fmt, *a):
        if self.path.startswith(("/health", "/state", "/names", "/qr.png", "/phone-url", "/scans", "/ballot-scan", "/detect")):  # hỏi thăm/tải ảnh liên tục, không cần ghi
            return
        sys.stderr.write("[ocr] " + fmt % a + "\n")


HTTPS_PORT = int(os.environ.get("KP_HTTPS_PORT", 8443))
CERT, KEY = ROOT / "config" / "cert.pem", ROOT / "config" / "key.pem"


HANDSHAKE_S = 10  # máy nào mở kết nối https rồi im quá chừng này giây thì bỏ kết nối đó


class TLSServer(ThreadingHTTPServer):
    """Bắt tay https trong luồng riêng của từng kết nối. Bắt tay ngay lúc nhận kết nối (cách cũ) thì 1 điện thoại
    sóng yếu / rớt mạng giữa chừng sẽ chặn mọi máy khác mở kết nối mới cho tới khi nó đóng."""
    ctx = None

    def finish_request(self, request, client_address):
        try:
            request.settimeout(HANDSHAKE_S)
            tls = self.ctx.wrap_socket(request, server_side=True)
            tls.settimeout(None)
        except (OSError, ssl.SSLError):
            return  # máy khách bỏ giữa chừng hoặc chưa tin chứng chỉ: bỏ qua, không ảnh hưởng máy khác
        try:
            self.RequestHandlerClass(tls, client_address, self)
        finally:
            try:
                tls.close()
            except OSError:
                pass

    def handle_error(self, request, client_address):
        if not isinstance(sys.exc_info()[1], (ConnectionError, ssl.SSLError, TimeoutError)):  # máy khách ngắt: chuyện thường
            super().handle_error(request, client_address)


def serve(host, port, ctx=None):
    srv = (TLSServer if ctx else ThreadingHTTPServer)((host, port), H)
    srv.daemon_threads = True
    srv.ctx = ctx
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


if __name__ == "__main__":
    # Tự kiểm: chạy với đường dẫn ảnh -> in kết quả đọc
    if len(sys.argv) > 1:
        print(json.dumps(read_page(cv2.imread(sys.argv[1])), ensure_ascii=False, indent=1))
        sys.exit()
    STORE = Store()
    digit_net()  # nạp sẵn mạng chữ số để phiếu đầu tiên không phải chờ
    start_name_workers()
    serve("127.0.0.1", PORT)
    print(f"Máy này mở:        http://localhost:{PORT}/")
    if CERT.exists() and KEY.exists():
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(CERT, KEY)
        serve("0.0.0.0", HTTPS_PORT, ctx)
        print(f"Các bàn khác mở:   https://<IP máy Mac>:{HTTPS_PORT}/  (xem IP bằng: ipconfig getifaddr en0)")
    else:
        print("Chưa có chứng chỉ (config/cert.pem): các bàn khác chưa vào được. Chạy tools/make_cert.sh trước.")
    print(f"Kho phiếu chung: {STATE_FILE} · đã có {len(STORE.s['ballots'])} phiếu")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
