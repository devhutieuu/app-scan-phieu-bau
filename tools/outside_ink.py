"""Phát hiện chữ ghi ở vùng trống bên dưới dòng cuối của phiếu (luật: ghi xuống dưới 18 dòng thì phiếu bất hợp lệ).

Đầu vào là ảnh phiếu đã nắn theo 4 marker (ocr_server.align). Vùng xét: từ dưới khung dòng cuối một khoảng hở
tới gần mép dưới tờ giấy, trừ 2 marker góc. Máy chỉ báo nghi ngờ kèm vị trí; người duyệt quyết định.

Kết quả "status":
  clean    vùng dưới sạch
  ink      có nét bút ở vùng dưới (kèm các khung "boxes", đơn vị mm trên phiếu)
  blocked  vùng dưới bị che / không phải giấy (ngón tay, mặt bàn, phiếu cong, nắn lệch) -> không kết luận được, nên quét lại

Những thứ cố ý KHÔNG tính là ghi ngoài ô:
  - nét thò xuống của chữ ở dòng cuối (g, y...): cụm nhỏ dính vào mép trên của vùng xét
  - vạch thẳng dài và mảnh: nếp gấp, mép giấy, đường kẻ khung bị xô lệch
"""
import cv2
import numpy as np

GAP_MM = 2.5         # khoảng hở dưới khung dòng cuối
EDGE_MM = 4.0        # bỏ sát mép giấy (ảnh chụp hay dính bóng / mặt bàn ở mép)
MARKER_PAD_MM = 4.0
MIN_STROKE_MM = 2.5  # cụm nét phải dài ít nhất chừng này (bỏ bụi, nhiễu ảnh)
MIN_INK_MM2 = 1.5    # tổng diện tích mực tối thiểu để báo
TAIL_H_MM, TAIL_W_MM = 6.0, 10.0   # nét thò từ dòng cuối: dính mép trên và nhỏ hơn cỡ này
LINE_THIN_MM, LINE_LONG_MM = 2.5, 8.0  # vạch thẳng: bề mảnh < 2,5 mm và dài > 8 mm
BLOCK_BLOB_MM = 3.0  # mảng "không phải giấy" phải to hơn cỡ này mới tính là bị che
BLOCK_FRAC = 0.02    # quá 2% vùng xét không phải giấy -> blocked


def below_rows(page, layout):
    ppm = layout.get("canonical_px_per_mm", 8.0)
    w_mm, h_mm = layout["page_mm"]
    last = max(layout["rows"], key=lambda r: r["index"])["name_box"]
    y0, y1 = last["y"] + last["h"] + GAP_MM, h_mm - EDGE_MM
    x0, x1 = EDGE_MM, w_mm - EDGE_MM
    X0, X1, Y0, Y1 = int(x0 * ppm), int(x1 * ppm), int(y0 * ppm), int(y1 * ppm)
    roi = page[Y0:Y1, X0:X1]
    valid = np.ones(roi.shape[:2], bool)
    for m in layout["markers"]:
        a, b = int((m["x"] - MARKER_PAD_MM) * ppm) - X0, int((m["y"] - MARKER_PAD_MM) * ppm) - Y0
        c, d = int((m["x"] + m["size"] + MARKER_PAD_MM) * ppm) - X0, int((m["y"] + m["size"] + MARKER_PAD_MM) * ppm) - Y0
        if d > 0 and c > 0:
            valid[max(b, 0):max(d, 0), max(a, 0):max(c, 0)] = False

    # --- vùng có còn là giấy không? (mảng to có màu đậm như da tay / gỗ, hoặc tối hẳn so với giấy)
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    paper_v = np.percentile(hsv[..., 2][valid], 70)
    notpaper = ((hsv[..., 1] > 70) | (hsv[..., 2] < 0.6 * paper_v)).astype(np.uint8)
    k = int(BLOCK_BLOB_MM * ppm)
    notpaper = cv2.morphologyEx(notpaper, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    blocked = float(notpaper[valid].mean())
    if blocked > BLOCK_FRAC:
        return {"status": "blocked", "ink_mm2": 0.0, "boxes": [], "blocked": round(blocked, 3)}

    # --- nét bút = tối hơn nền quanh nó (ngưỡng theo vùng nhỏ nên bóng đổ, giấy ngả màu không bị tính)
    gray = cv2.GaussianBlur(cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY), (3, 3), 0)
    bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 41, 18)
    bw[~valid] = 0
    n, _, stats, _ = cv2.connectedComponentsWithStats(cv2.dilate(bw, np.ones((5, 5), np.uint8)))
    boxes, area = [], 0.0
    for i in range(1, n):
        x, y, w, h, _ = stats[i]
        wm, hm = w / ppm, h / ppm
        if max(wm, hm) < MIN_STROKE_MM:
            continue
        if min(wm, hm) < LINE_THIN_MM and max(wm, hm) > LINE_LONG_MM:
            continue
        if y <= 0.5 * ppm and hm <= TAIL_H_MM and wm <= TAIL_W_MM:
            continue
        a = float((bw[y:y + h, x:x + w] > 0).sum()) / (ppm * ppm)
        area += a
        boxes.append({"x": round(float(x / ppm + x0), 1), "y": round(float(y / ppm + y0), 1),
                      "w": round(float(wm), 1), "h": round(float(hm), 1)})
    hit = area >= MIN_INK_MM2
    return {"status": "ink" if hit else "clean", "ink_mm2": round(area, 2), "boxes": boxes if hit else [],
            "blocked": round(blocked, 3)}
