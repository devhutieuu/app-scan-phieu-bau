"""Nắn lại từng dòng của phiếu sau khi đã nắn theo 4 marker góc.

4 marker chỉ nắn đúng khi tờ giấy phẳng. Phiếu bị gấp đôi, cong hay xô thì phần giữa trang lệch vài mm
(đo 14/11/2026 trên phiếu gấp đôi: dòng lệch tới 6 mm, tức nửa dòng), ô STT cắt trúng dòng bên cạnh.
Cách sửa: tìm khung in sẵn của ô họ tên (và khung 3 ô STT) của từng dòng trên ảnh, rồi nắn riêng dải ảnh
của dòng đó cho khung về đúng vị trí chuẩn. Phần còn lại của trang (tiêu đề, vùng dưới dòng cuối) giữ nguyên.
Không tìm đủ khung của mọi dòng thì trả ảnh như cũ (không đoán).
"""
import cv2
import numpy as np


def _corners(cnt):
    """4 góc (trên-trái, trên-phải, dưới-phải, dưới-trái) của 1 khung gần như nằm ngang."""
    p = cnt.reshape(-1, 2).astype(np.float32)
    s, d = p.sum(1), p[:, 0] - p[:, 1]
    return np.float32([p[s.argmin()], p[d.argmax()], p[s.argmax()], p[d.argmin()]])


def _line_ends(lab, i, st):
    """2 đầu mút (trái, phải) của 1 đường kẻ ngang: tâm của vài cột điểm ngoài cùng."""
    x, y, w, h = st[i][:4]
    m = lab[y:y + h, x:x + w] == i
    ys_l = np.where(m[:, :4].any(1))[0]
    ys_r = np.where(m[:, -4:].any(1))[0]
    return [x, y + ys_l.mean()], [x + w - 1, y + ys_r.mean()]


def find_frames(page, layout):
    """Tìm khung ô họ tên và khung STT in sẵn. Trả (name_quads, stt_quads), mỗi phần tử là 4 góc tính bằng px.
    Khung họ tên lấy từ 2 đường kẻ ngang dài trên/dưới của nó: chữ viết tay không tạo ra được đường thẳng dài cỡ đó,
    nên nét chữ thò qua khe giữa 2 dòng không làm 2 khung dính vào nhau. Khung STT (nhỏ, ít bị viết đè) lấy theo viền."""
    ppm = layout.get("canonical_px_per_mm", 8.0)
    row = layout["rows"][0]
    nb = row["name_box"]
    sw = sum(c["w"] for c in row["stt_cells"])
    gray = cv2.cvtColor(page, cv2.COLOR_BGR2GRAY)
    bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 10)
    hk = cv2.getStructuringElement(cv2.MORPH_RECT, (int(7 * ppm), 1))
    vk = cv2.getStructuringElement(cv2.MORPH_RECT, (1, int(5 * ppm)))
    hl = cv2.dilate(cv2.morphologyEx(bw, cv2.MORPH_OPEN, hk), np.ones((3, 3), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(hl, 8)
    long_lines = [i for i in range(1, n) if st[i][2] >= 0.9 * nb["w"] * ppm and st[i][3] <= 5 * ppm]
    long_lines.sort(key=lambda i: st[i][1] + st[i][3] / 2)
    # Ghép đường trên với đường dưới của cùng 1 khung: 2 đường liền nhau cách nhau cỡ chiều cao ô.
    # Đường lẻ loi (nếp gấp, mép giấy, đường kẻ bị đứt) thì bỏ qua, không làm hỏng cả trang.
    ends = [_line_ends(lab, i, st) for i in long_lines]
    names, k = [], 0
    while k + 1 < len(ends):
        (tl, tr), (bl, br) = ends[k], ends[k + 1]
        if 0.7 * nb["h"] * ppm <= (bl[1] - tl[1]) <= 1.4 * nb["h"] * ppm:
            names.append(np.float32([tl, tr, br, bl]))
            k += 2
        else:
            k += 1
    lines = cv2.dilate(hl | cv2.morphologyEx(bw, cv2.MORPH_OPEN, vk), np.ones((3, 3), np.uint8))
    cnts, _ = cv2.findContours(lines, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    stts = []
    for c in cnts:
        x, y, w, h = cv2.boundingRect(c)
        if 0.7 * nb["h"] <= h / ppm <= 1.8 * nb["h"] and 0.85 * sw <= w / ppm <= 1.15 * sw:
            stts.append(_corners(c))
    return names, stts


TOP_PAD_MM, BOTTOM_PAD_MM = 8.0, 2.5  # dòng đầu còn cộng thêm độ lệch đo được (tối đa 6 mm) để trùm hết hàng tiêu đề cũ
MAX_MISSING = 3  # số dòng tối đa không thấy khung (đường kẻ mờ ở nếp gấp...) mà vẫn nắn; không cho thiếu 2 dòng liền nhau


def _assign(quads, rows, ppm):
    """Gán các khung tìm được vào đúng dòng, kể cả khi thiếu vài khung. Trả list khung theo thứ tự dòng (khung thiếu được
    nội suy từ 2 dòng kề), hoặc None nếu không đủ tin cậy."""
    n = len(rows)
    if not n - MAX_MISSING <= len(quads) <= n:
        return None
    quads = sorted(quads, key=lambda q: q[:, 1].mean())
    pitch = (rows[1]["name_box"]["y"] - rows[0]["name_box"]["y"]) * ppm
    idx = [0]
    for a, b in zip(quads, quads[1:]):
        idx.append(idx[-1] + max(1, int(round((b[:, 1].mean() - a[:, 1].mean()) / pitch))))
    spare = n - 1 - idx[-1]
    if spare < 0:
        return None
    # còn dư chỗ thì thử các cách dịch (thiếu dòng đầu hay dòng cuối), chọn cách gần vị trí chuẩn nhất
    cy = [(r["name_box"]["y"] + r["name_box"]["h"] / 2) * ppm for r in rows]
    off = min(range(spare + 1), key=lambda o: sum(abs(q[:, 1].mean() - cy[i + o]) for q, i in zip(quads, idx)))
    slot = [None] * n
    for q, i in zip(quads, idx):
        slot[i + off] = q
    for i in range(n):
        if slot[i] is not None:
            continue
        up = slot[i - 1] if i > 0 else None
        dn = slot[i + 1] if i + 1 < n else None
        if up is not None and dn is not None:
            slot[i] = (up + dn) / 2
        elif up is not None and i >= 2 and slot[i - 2] is not None:
            slot[i] = up + (up - slot[i - 2])
        elif dn is not None and i + 2 < n and slot[i + 2] is not None:
            slot[i] = dn - (slot[i + 2] - dn)
        else:
            return None
    return [np.float32(q) for q in slot]


MIN_FIX_MM = 2.0  # phiếu phẳng lệch dưới mức này (đo trên các bản quét thật: 0,9-1,5 mm) thì giữ cách đọc cũ


def fix_rows(page, layout, raw=None, M=None):
    """Trả (ảnh đã nắn từng dòng, số dòng đã nắn, độ lệch lớn nhất tính bằng mm).
    raw, M: ảnh chụp gốc và phép nắn theo marker đã dùng để ra `page`. Có thì dải của từng dòng được lấy thẳng từ ảnh gốc
    (nắn 1 lần), không nắn chồng lên ảnh đã nắn: nét chữ không bị nhòe thêm, mạng chữ số đọc ổn hơn.
    Không tìm đủ khung -> (page, 0, 0.0). Phiếu gần như phẳng (lệch < MIN_FIX_MM) -> giữ nguyên, trả số dòng 0."""
    ppm = layout.get("canonical_px_per_mm", 8.0)
    rows = sorted(layout["rows"], key=lambda r: r["index"])
    names, stts = find_frames(page, layout)
    names = _assign(names, rows, ppm)
    if names is None:
        return page, 0, 0.0
    worst = max(float(np.abs(q - np.float32([[r["name_box"]["x"], r["name_box"]["y"]], [r["name_box"]["x"] + r["name_box"]["w"], r["name_box"]["y"]],
                                             [r["name_box"]["x"] + r["name_box"]["w"], r["name_box"]["y"] + r["name_box"]["h"]],
                                             [r["name_box"]["x"], r["name_box"]["y"] + r["name_box"]["h"]]]) * ppm).max()) / ppm
                for r, q in zip(rows, names))
    if worst < MIN_FIX_MM:
        return page, 0, round(worst, 1)
    out = page.copy()
    W = page.shape[1]
    def warp(H, y0, y1, x0, x1):
        T = np.array([[1, 0, -x0], [0, 1, -y0], [0, 0, 1]], np.float64)
        src, A = (raw, T @ H @ M) if raw is not None and M is not None else (page, T @ H)
        out[y0:y1, x0:x1] = cv2.warpPerspective(src, A, (x1 - x0, y1 - y0), flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255))

    for i, (row, q) in enumerate(zip(rows, names)):
        nb = row["name_box"]
        c0, c2 = row["stt_cells"][0], row["stt_cells"][-1]
        rect = lambda x0, y0, x1, y1: np.float32([[x0, y0], [x1, y0], [x1, y1], [x0, y1]]) * ppm  # noqa: E731
        Hn = cv2.getPerspectiveTransform(q, rect(nb["x"], nb["y"], nb["x"] + nb["w"], nb["y"] + nb["h"]))
        # khung STT cùng dòng: khung có tâm gần đường kéo dài của khung họ tên nhất. Phần STT nắn theo chính khung của nó
        # (giấy cong thì 2 khung không cùng 1 mặt phẳng, gộp chung sẽ lệch ô cả 2 bên); không thấy thì dùng chung phép nắn ô tên.
        cy_left = (q[0][1] + q[3][1]) / 2
        cand = [s for s in stts if abs(s[:, 1].mean() - cy_left) < 4 * ppm]
        Hs = Hn
        if cand:
            sq = min(cand, key=lambda s: abs(s[:, 1].mean() - cy_left))
            Hs = cv2.getPerspectiveTransform(sq, rect(c0["x"], c0["y"], c2["x"] + c2["w"], c2["y"] + c2["h"]))
        # dải của dòng này: từ giữa khe với dòng trên tới giữa khe với dòng dưới; chia đôi ở khe giữa ô STT và ô họ tên.
        # Dòng đầu lấy rộng lên trên (trùm cả hàng tiêu đề cột), dòng cuối lấy rộng xuống dưới, để không sót lại
        # mẩu khung cũ nằm lệch ngay sát bảng.
        top = nb["y"] - (TOP_PAD_MM + min(worst, 6.0) if i == 0 else (nb["y"] - (rows[i - 1]["name_box"]["y"] + rows[i - 1]["name_box"]["h"])) / 2)
        bot = nb["y"] + nb["h"] + (BOTTOM_PAD_MM if i == len(rows) - 1 else (rows[i + 1]["name_box"]["y"] - nb["y"] - nb["h"]) / 2)
        y0, y1 = int(round(top * ppm)), int(round(bot * ppm))
        xm = int(round((c2["x"] + c2["w"] + nb["x"]) / 2 * ppm))
        warp(Hs, y0, y1, 0, xm)
        warp(Hn, y0, y1, xm, W)
    return out, len(rows), round(worst, 1)
