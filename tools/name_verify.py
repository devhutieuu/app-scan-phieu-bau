"""Đối chiếu ô họ tên với danh sách ứng viên: ghép 3 máy đọc cục bộ rồi kiểm chéo với STT. BẢN THỬ, chưa gắn máy chủ.

Ý chính: không tin riêng máy nào. Mỗi máy cho 1 bảng điểm "ô này giống từng người trong danh sách tới đâu":
  - CRNN      chấm thẳng từng tên trong danh sách (xác suất CTC của chuỗi, trừ đi cách đọc tự do tốt nhất)
  - VietOCR   chấm thẳng từng tên (ép mô hình "đọc" đúng chuỗi đó rồi xem nó chịu tới đâu)
  - Qwen-VL   chép tự do ra chữ, rồi so chữ đó với từng tên (bỏ dấu, tính số ký tự lệch)
Chuẩn hóa từng bảng theo ô (z-score) rồi cộng lại: fuse(). Sau đó check(): người mang STT đọc được có nằm trong
nhóm tên khớp nhất không. Khớp -> dòng xanh; lệch -> tô vàng cho người duyệt.

Đo ngày 14/11/2026 trên 206 ô họ tên của 19 phiếu đã duyệt (tools/bench_verify.py eval):
  tìm đúng người chỉ từ chữ viết (1 trong 201):  CRNN 66% · VietOCR 52% · Qwen 84% · ghép cả ba 92%
  kiểm chéo với STT (TOP_K = 2): 94% dòng đúng được cho qua, bắt được 13/13 dòng STT và tên là 2 người khác nhau
Đã thử mà không hơn, nên không dùng: cho phần "tên" nặng điểm hơn đệm và họ (80% so với 84% khi so đều cả chuỗi),
và chấm riêng đuôi tên bằng CTC với phần đầu tự do (CRNN 19%). Máy đọc sai rải đều các chữ, không chừa phần tên.
"""
import unicodedata

import numpy as np

NEG = -1e30
W_LIST = 2.0   # trọng số của (CRNN + W_VIET * VietOCR) so với Qwen
W_VIET = 2.0
TOP_K = 2      # người theo STT phải nằm trong TOP_K tên khớp nhất thì dòng được cho qua


def _lse(a, b):
    m = np.maximum(a, b)
    return m + np.log1p(np.exp(-np.abs(a - b)))


class CtcScorer:
    """Chấm các chuỗi trên bảng log-xác suất CTC của 1 ô (T khung x (C ký tự + 1 ô trống))."""

    def __init__(self, chars):
        self.chars = chars
        self.blank = len(chars)
        self.pad = len(chars) + 1

    def encode(self, text):
        out = []
        for c in text:
            if c in self.chars:
                out.append(self.chars.index(c))
            elif c.lower() in self.chars:
                out.append(self.chars.index(c.lower()))
        return out

    def _ext(self, texts):
        exts = []
        for t in texts:
            e = [self.blank]
            for k in self.encode(t):
                e += [k, self.blank]
            exts.append(e)
        N, S = len(exts), max(len(e) for e in exts)
        ext = np.full((N, S), self.pad)
        for i, e in enumerate(exts):
            ext[i, :len(e)] = e
        lens = np.array([len(e) for e in exts])
        skip = np.zeros((N, S), bool)  # được nhảy từ s-2 sang s: khác ký tự và không phải ô trống
        skip[:, 2:] = (ext[:, 2:] != self.blank) & (ext[:, 2:] != ext[:, :-2])
        return ext, lens, skip

    def score(self, logp, texts):
        """log P(chuỗi | ảnh) - log P(cách đọc tự do tốt nhất | ảnh) cho từng chuỗi. Trả mảng (N,), <= 0."""
        return self.score_many(logp[None], texts)[0]

    def score_many(self, logps, texts):
        """Như score() cho nhiều ô cùng lúc (các ô của 1 phiếu): logps (B, T, C) -> (B, N). Cùng phép tính, chỉ gộp
        vòng lặp theo khung hình nên nhanh hơn gọi từng ô."""
        B, T = logps.shape[:2]
        best = logps.max(2)
        lp = np.concatenate([logps, np.full((B, T, 1), NEG, np.float32)], 2)  # cột đệm cho chuỗi ngắn hơn
        ext, lens, skip = self._ext(texts)
        N, S = ext.shape
        a = np.full((B, N, S), NEG)
        a[:, :, :2] = lp[:, 0][:, ext[:, :2]]
        for t in range(1, T):
            v = a.copy()
            v[:, :, 1:] = _lse(v[:, :, 1:], a[:, :, :-1])
            v[:, :, 2:] = np.where(skip[:, 2:], _lse(v[:, :, 2:], a[:, :, :-2]), v[:, :, 2:])
            a = v + lp[:, t][:, ext]
        r = np.arange(N)
        return _lse(a[:, r, lens - 1], a[:, r, np.maximum(lens - 2, 0)]) - best.sum(1)[:, None]


def plain(s):
    """Bỏ dấu, chữ thường, chỉ giữ chữ và số."""
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").replace("đ", "d").replace("Đ", "D").lower()
    return " ".join("".join(c if c.isascii() and c.isalnum() else " " for c in s).split())


def sim(a, b):
    """Độ giống 0..1 của 2 chuỗi sau khi bỏ dấu (1 - khoảng cách sửa / độ dài chuỗi dài hơn)."""
    a, b = plain(a), plain(b)
    if not a or not b:
        return 0.0
    p = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        c = [i]
        for j in range(1, len(b) + 1):
            c.append(min(p[j] + 1, c[j - 1] + 1, p[j - 1] + (a[i - 1] != b[j - 1])))
        p = c
    return 1 - p[-1] / max(len(a), len(b))


def _z(s):
    s = np.asarray(s, float)
    return (s - s.mean()) / (s.std() + 1e-9)


def fuse(crnn, viet, qwen_text, names):
    """Điểm ghép của từng ứng viên cho 1 ô. crnn, viet: điểm chấm danh sách (N,); qwen_text: chữ Qwen chép được."""
    q = np.array([sim(qwen_text, n) for n in names])
    return _z(q) + W_LIST * _z(np.asarray(crnn) + W_VIET * np.asarray(viet))


def check(score, stt_index, top_k=TOP_K):
    """Kiểm 1 dòng. stt_index: vị trí trong danh sách của người mang STT đọc được (None nếu không có STT hợp lệ).
    Trả {"ok": tên khớp với STT?, "rank": hạng của người theo STT (1 = khớp nhất), "best": vị trí người khớp tên nhất}."""
    best = int(np.argmax(score))
    if stt_index is None:
        return {"ok": False, "rank": None, "best": best}
    rank = int((score > score[stt_index]).sum()) + 1
    return {"ok": rank <= top_k, "rank": rank, "best": best}
