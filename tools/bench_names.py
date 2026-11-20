"""Chấm điểm các engine đọc họ tên trên các bản quét thật đã có đáp án.

Chạy:  .venv/bin/python tools/bench_names.py [apple-vision vietocr qwen-vl]
(qwen-vl cần dịch vụ Qwen đang chạy: .venv-mlx/bin/python tools/qwen_server.py)

Dữ liệu: out/scans/<mã>/ có page.jpg (ảnh đã nắn) và truth.json (giao diện tự gửi khi bấm Chấp nhận).
Chỉ chấm các dòng người duyệt đã kết luận "tính cho 1 người" (result = ok), vì khi đó biết chắc người được ghi.

Tiêu chí:
- Khớp đúng người: chữ engine đọc ra, qua đúng logic khớp tên của giao diện (fits_name với người mang STT),
  có ra đúng người không. Đây là con số quyết định: sai thì dòng bị gạch oan hoặc người duyệt phải sửa.
- CER: tỉ lệ ký tự sai so với tên đầy đủ trong danh sách (bỏ dấu, chữ thường). Chỉ để tham khảo, vì
  người viết có thể viết tắt.
"""
import importlib.util
import json
import sys
import time
import unicodedata
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("ocr", ROOT / "tools" / "ocr_server.py")
ocr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ocr)


# ---- cùng logic khớp tên với giao diện (stripVN / matchScore / fitsName trong ballot-scan-prototype.html) ----
def strip_vn(s):
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").replace("đ", "d").replace("Đ", "D").lower()
    s = "".join(c if c.isascii() and (c.isalnum() or c == " ") else " " for c in s)
    return " ".join(s.split())


def lev(a, b):
    p = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        c = [i]
        for j in range(1, len(b) + 1):
            c.append(min(p[j] + 1, c[j - 1] + 1, p[j - 1] + (a[i - 1] != b[j - 1])))
        p = c
    return p[-1]


def simil(a, b):
    a, b = strip_vn(a), strip_vn(b)
    return 0.0 if not a or not b else 1 - lev(a, b) / max(len(a), len(b))


def match_score(read, name):
    s = simil(read, name)
    r, n = strip_vn(read).split(), strip_vn(name).split()
    if len(r) >= 2 and len(n) >= 2:
        t = simil(" ".join(r[-2:]), " ".join(n[-2:]))
        if t > 0.9 and len(r) < len(n):
            return max(s, 0.75 * t)
    return s


def fits_name(read, name):
    if match_score(read, name) >= 0.72:
        return True
    r, n = strip_vn(read).split(), strip_vn(name).split()
    if len(r) < 2 or simil(r[-1], n[-1]) < 0.8:
        return False
    j = 0
    for t in r[:-1]:
        while j < len(n) - 1 and not n[j].startswith(t):
            j += 1
        if j >= len(n) - 1:
            return False
        j += 1
    return True


def cer(read, name):
    a, b = strip_vn(read), strip_vn(name)
    return lev(a, b) / max(len(b), 1)


def main():
    engines = sys.argv[1:] or ["apple-vision", "vietocr", "qwen-vl", "crnn-vi", "vietocr-list", "crnn-vi-list"]
    cases = []
    for d in sorted((ROOT / "out" / "scans").glob("*/")):
        if not (d / "truth.json").exists():
            continue
        truth = json.loads((d / "truth.json").read_text(encoding="utf-8"))
        img = cv2.imread(str(d / ("page.jpg" if (d / "page.jpg").exists() else "frame.jpg")))
        page, _ = ocr.align(img)
        cands = {int(c["stt"]): c["name"] for c in truth.get("cands") or []}
        for r in truth["rows"]:
            if r.get("result") == "ok" and r.get("choice") in cands:
                cases.append((d.name, r["line"], page, cands[r["choice"]], list(cands.values())))
    if not cases:
        print("Chưa có bản quét nào có đáp án (truth.json). Quét vài phiếu thật rồi bấm Chấp nhận trên giao diện.")
        return
    print(f"{len(cases)} dòng có đáp án, từ {len({c[0] for c in cases})} bản quét.\n")
    # Lưu ý: biến thể *-list chọn trong danh sách nên CER = 0 khi chọn đúng; so sánh bằng cột "Khớp đúng người".
    row_of = {r["index"]: r for r in ocr.LAYOUT["rows"]}
    eng = ocr.ENGINES["apple-vision"]
    summary = []
    for e in engines:
        ok = 0
        cers, t0, errs = [], time.time(), []
        for scan, line, page, name, names in cases:
            row = row_of[line]
            try:
                if e in ocr.LIST_READERS:
                    text, _ = ocr.LIST_READERS[e](page, row, names)
                else:
                    text, _ = ocr.NAME_READERS.get(e, lambda p, r, en: ocr.read_name(p, r, en))(page, row, eng)
            except Exception as ex:  # noqa: BLE001
                errs.append(str(ex))
                text = ""
            hit = fits_name(text, name)
            ok += hit
            cers.append(cer(text, name))
            print(f"  [{e:12}] {scan} dòng {line:2}: {'ĐÚNG' if hit else 'SAI '}  đọc «{text}»  ← «{name}»")
        if errs:
            print(f"  [{e}] lỗi: {errs[0]}")
        n = len(cases)
        summary.append((e, ok, n, sum(cers) / n, (time.time() - t0) / n))
        print()
    print(f"{'Engine':14}{'Khớp đúng người':>18}{'CER TB':>10}{'Giây/dòng':>12}")
    for e, ok, n, c, t in summary:
        print(f"{e:14}{f'{ok}/{n} ({ok / n:.0%})':>18}{c:>10.2f}{t:>12.2f}")


if __name__ == "__main__":
    main()
