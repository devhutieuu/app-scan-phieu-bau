"""Sinh phiếu đề cử (PDF) và file cấu hình tọa độ (JSON).

Chạy:  .venv/bin/python tools/make_ballot.py
Đầu ra: out/phieu-de-cu.pdf (bản in), out/phieu-mau.pdf + .docx, config/ballot_layout.json
        Bật BALLOT_NUMBERED thì bản in là out/phieu-de-cu-001-200.pdf, mỗi tờ 1 số phiếu.

Đánh số phiếu (BALLOT_NUMBERED, đang TẮT): số phiếu in ở góc trên phải bằng chữ số và bằng 1 mã máy đọc (ArUco 5x5, id = số phiếu) để hệ thống
định danh tờ phiếu: chống quét trùng, truy vết lỗi. Mã này khác bộ với 4 mã góc nên không lẫn khi nắn phiếu.

Mọi tọa độ tính bằng mm, gốc ở góc trên trái trang, trục y hướng xuống.
Code nhận phiếu đọc config/ballot_layout.json, không tự giữ tọa độ riêng.
"""
import json
from pathlib import Path

import cv2
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent.parent

# ---- Tham số phiếu (đổi ở đây rồi chạy lại) -------------------------------
ORG_1 = "HỘI THÁNH TIN LÀNH VIỆT NAM (MIỀN NAM)"
ORG_2 = "HỘI THÁNH TIN LÀNH LINH XUÂN"
TITLE = "PHIẾU ĐỀ CỬ"
LOGO = ROOT / "config" / "logo.png"
LOGO_SIZE = 12.0
SUBTITLE = "Ghi đủ số thứ tự và họ tên người được chọn. Có thể chọn ít hơn số dòng hoặc để trống."
NUM_ROWS = 18          # số dòng điền trên phiếu
STT_DIGITS = 3         # số chữ số tối đa của STT (danh sách đến 999)
PAGE_W, PAGE_H = 210.0, 297.0   # A4 dọc

MARKER_SIZE = 10.0     # cạnh ô đen của marker (chưa tính viền trắng)
MARKER_MARGIN = 6.0    # khoảng từ mép giấy tới ô đen marker
ARUCO_DICT = cv2.aruco.DICT_4X4_50
MARKER_IDS = {"tl": 0, "tr": 1, "br": 2, "bl": 3}

# Số phiếu: mỗi tờ 1 số, in bằng chữ số + mã máy đọc (id của mã = số phiếu)
# Tắt thì phiếu không in số, ballot_layout.json không có "ballot_id" -> máy chủ tự bỏ việc đọc số phiếu,
# quay về cấp mã phiếu lần lượt và nghi trùng theo nét mực. Đổi xong chạy lại file này rồi khởi động lại máy chủ.
BALLOT_NUMBERED = False
BALLOT_FIRST, BALLOT_LAST = 1, 200
ID_DICT_NAME = "DICT_5X5_250"   # khác bộ với mã góc (4x4); chứa id 0..249
ID_SIZE = 10.0                  # cạnh ô đen của mã số phiếu
ID_X = 179.0                    # mép phải trùng mép phải ô họ tên (189 mm)
ID_Y = 19.0                     # ngang hàng logo

TABLE_X = 20.0
TABLE_Y = 62.0
ROW_H = 12.0
LINE_NO_W = 8.0
CELL_W, CELL_H = 9.0, 10.0
GAP = 3.0
NAME_W = 128.0         # chiều rộng ô họ tên
NAME_H = 10.0
# ----------------------------------------------------------------------------

FONT_REG = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"


def marker_origin(corner: str) -> tuple[float, float]:
    left = MARKER_MARGIN
    right = PAGE_W - MARKER_MARGIN - MARKER_SIZE
    top = MARKER_MARGIN
    bottom = PAGE_H - MARKER_MARGIN - MARKER_SIZE
    return {
        "tl": (left, top), "tr": (right, top),
        "br": (right, bottom), "bl": (left, bottom),
    }[corner]


def build_layout() -> dict:
    markers = []
    for corner, mid in MARKER_IDS.items():
        x, y = marker_origin(corner)
        markers.append({
            "corner": corner, "id": mid, "x": x, "y": y, "size": MARKER_SIZE,
            "center": [x + MARKER_SIZE / 2, y + MARKER_SIZE / 2],
        })

    rows = []
    for i in range(NUM_ROWS):
        y = TABLE_Y + i * ROW_H
        box_y = y + (ROW_H - CELL_H) / 2
        stt_x0 = TABLE_X + LINE_NO_W + GAP
        cells = [
            {"x": stt_x0 + k * CELL_W, "y": box_y, "w": CELL_W, "h": CELL_H}
            for k in range(STT_DIGITS)
        ]
        name_x = stt_x0 + STT_DIGITS * CELL_W + GAP
        rows.append({
            "index": i + 1,
            "stt_cells": cells,
            "name_box": {"x": name_x, "y": box_y, "w": NAME_W, "h": NAME_H},
        })

    layout = {
        "page_mm": [PAGE_W, PAGE_H],
        "aruco_dict": "DICT_4X4_50",
        "markers": markers,
        "num_rows": NUM_ROWS,
        "stt_digits": STT_DIGITS,
        # ảnh chuẩn sau khi nắn phối cảnh: pixel = mm * px_per_mm
        "canonical_px_per_mm": 8.0,
        # cắt vào trong khung để loại viền in
        "crop_inset_mm": 0.8,
        "rows": rows,
    }
    if BALLOT_NUMBERED:  # mã số phiếu (ArUco, id = số phiếu) ở góc trên phải
        layout["ballot_id"] = {
            "aruco_dict": ID_DICT_NAME, "x": ID_X, "y": ID_Y, "size": ID_SIZE,
            "center": [ID_X + ID_SIZE / 2, ID_Y + ID_SIZE / 2],
            "first": BALLOT_FIRST, "last": BALLOT_LAST,
        }
    return layout


def draw_marker(c: canvas.Canvas, marker_id: int, x: float, y: float,
                dict_id: int = ARUCO_DICT, size: float = MARKER_SIZE) -> None:
    """Vẽ marker dạng vector: lưới (bit + 2) ô mỗi cạnh (viền đen 1 ô + các bit)."""
    dictionary = cv2.aruco.getPredefinedDictionary(dict_id)
    n = dictionary.markerSize + 2
    grid = cv2.aruco.generateImageMarker(dictionary, marker_id, n)
    cell = size / n
    c.setFillColorRGB(0, 0, 0)
    for r in range(n):
        for q in range(n):
            if grid[r, q] == 0:
                px = (x + q * cell) * mm
                py = (PAGE_H - (y + (r + 1) * cell)) * mm
                c.rect(px, py, cell * mm, cell * mm, stroke=0, fill=1)


def rect(c: canvas.Canvas, x: float, y: float, w: float, h: float) -> None:
    c.rect(x * mm, (PAGE_H - y - h) * mm, w * mm, h * mm, stroke=1, fill=0)


def text(c, s, x, y, font, size, align="left") -> None:
    c.setFont(font, size)
    px, py = x * mm, (PAGE_H - y) * mm
    {"left": c.drawString, "center": c.drawCentredString, "right": c.drawRightString}[align](px, py, s)


def make_pdf(layout: dict, path: Path, numbers=(None,)) -> None:
    """Mỗi phần tử của numbers là 1 trang; None = trang mẫu không có số phiếu."""
    pdfmetrics.registerFont(TTFont("Reg", FONT_REG))
    pdfmetrics.registerFont(TTFont("Bold", FONT_BOLD))
    c = canvas.Canvas(str(path), pagesize=(PAGE_W * mm, PAGE_H * mm))
    c.setTitle(TITLE)
    for number in numbers:
        draw_page(c, layout, number)
        c.showPage()
    c.save()


def draw_page(c: canvas.Canvas, layout: dict, number) -> None:
    if number is not None:
        bid = layout["ballot_id"]
        draw_marker(c, number, bid["x"], bid["y"], getattr(cv2.aruco, bid["aruco_dict"]), bid["size"])
        c.setFillColorRGB(0, 0, 0)
        tx_r = bid["x"] - 3.0
        text(c, "Số phiếu", tx_r, bid["y"] + 2.6, "Reg", 8, "right")
        text(c, f"{number:03d}", tx_r, bid["y"] + bid["size"], "Bold", 18, "right")

    for m in layout["markers"]:
        draw_marker(c, m["id"], m["x"], m["y"])

    c.setFillColorRGB(0, 0, 0)
    # cụm đầu phiếu: logo bên trái, 2 dòng tên Hội Thánh bên phải; cả cụm căn giữa
    org_w = max(pdfmetrics.stringWidth(t, "Bold", 11) for t in (ORG_1, ORG_2)) / mm
    gap = 4.0
    lx = (PAGE_W - (LOGO_SIZE + gap + org_w)) / 2
    logo_y = 18.0
    c.drawImage(str(LOGO), lx * mm, (PAGE_H - logo_y - LOGO_SIZE) * mm,
                LOGO_SIZE * mm, LOGO_SIZE * mm, mask="auto")
    tx = lx + LOGO_SIZE + gap
    mid = logo_y + LOGO_SIZE / 2
    text(c, ORG_1, tx, mid - 1.2, "Bold", 11)
    text(c, ORG_2, tx, mid + 4.2, "Bold", 11)
    text(c, TITLE, PAGE_W / 2, 46, "Bold", 18, "center")
    text(c, SUBTITLE, PAGE_W / 2, 52.5, "Reg", 8, "center")

    # tiêu đề cột
    head_y = TABLE_Y - 2
    stt_x0 = TABLE_X + LINE_NO_W + GAP
    name_x = stt_x0 + STT_DIGITS * CELL_W + GAP
    text(c, "Dòng", TABLE_X + LINE_NO_W / 2, head_y, "Bold", 8, "center")
    text(c, "Số thứ tự", stt_x0 + STT_DIGITS * CELL_W / 2, head_y, "Bold", 8, "center")
    text(c, "Họ và tên", name_x + NAME_W / 2, head_y, "Bold", 8, "center")

    c.setStrokeColorRGB(0.35, 0.35, 0.35)
    c.setLineWidth(0.5)
    for row in layout["rows"]:
        for cell in row["stt_cells"]:
            rect(c, cell["x"], cell["y"], cell["w"], cell["h"])
        nb = row["name_box"]
        rect(c, nb["x"], nb["y"], nb["w"], nb["h"])
        c.setFillColorRGB(0, 0, 0)
        text(c, str(row["index"]), TABLE_X + LINE_NO_W / 2,
             nb["y"] + nb["h"] / 2 + 1.5, "Reg", 9, "center")


def make_docx(pdf_path: Path, path: Path, dpi: int = 600) -> None:
    """Xuất phiếu sang Word: trang A5 lề 0, chèn nguyên trang phiếu dạng ảnh
    độ phân giải cao để giữ đúng tọa độ mm (mã góc + ô STT) khi in."""
    import io

    import fitz  # pymupdf
    from docx import Document
    from docx.shared import Mm

    page = fitz.open(str(pdf_path))[0]
    png = page.get_pixmap(dpi=dpi, alpha=False).tobytes("png")

    doc = Document()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Mm(PAGE_W), Mm(PAGE_H)
    sec.left_margin = sec.right_margin = Mm(0)
    sec.top_margin = sec.bottom_margin = Mm(0)
    sec.header_distance = sec.footer_distance = Mm(0)
    para = doc.paragraphs[0] if doc.paragraphs else doc.add_paragraph()
    pf = para.paragraph_format
    pf.space_before = pf.space_after = Mm(0)
    pf.line_spacing = 1.0
    para.add_run().add_picture(io.BytesIO(png), width=Mm(PAGE_W), height=Mm(PAGE_H))
    doc.core_properties.title = TITLE
    doc.save(str(path))


def main() -> None:
    layout = build_layout()
    (ROOT / "config").mkdir(exist_ok=True)
    (ROOT / "out").mkdir(exist_ok=True)
    cfg = ROOT / "config" / "ballot_layout.json"
    cfg.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    if BALLOT_NUMBERED:
        batch = ROOT / "out" / f"phieu-de-cu-{BALLOT_FIRST:03d}-{BALLOT_LAST:03d}.pdf"
        make_pdf(layout, batch, range(BALLOT_FIRST, BALLOT_LAST + 1))
    else:
        batch = ROOT / "out" / "phieu-de-cu.pdf"
        make_pdf(layout, batch)
    pdf = ROOT / "out" / "phieu-mau.pdf"
    make_pdf(layout, pdf)
    docx_path = ROOT / "out" / "phieu-mau.docx"
    make_docx(pdf, docx_path)
    print(f"Đã ghi {cfg}\nĐã ghi {batch}\nĐã ghi {pdf}\nĐã ghi {docx_path}")


if __name__ == "__main__":
    main()
