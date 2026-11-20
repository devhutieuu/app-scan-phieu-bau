"""Đo thử nhiều bàn gửi phiếu cùng lúc tới máy chủ kiểm phiếu.

Mỗi bàn (1 luồng) lặp: xin mã phiếu (/next) -> gửi ảnh đọc STT (/read) -> lưu phiếu đã duyệt (/ballot).
Không có thời gian người duyệt, nên đây là mức tải NẶNG hơn thực tế nhiều (thực tế ~10 giây/phiếu/bàn).

CHỈ chạy vào máy chủ thử, không chạy vào phiên thật (sẽ ghi phiếu giả vào kho):
  KP_PORT=18766 KP_HTTPS_PORT=18443 KP_SESSION=/tmp/kp/sess KP_SCANS=/tmp/kp/scans .venv/bin/python tools/ocr_server.py
  .venv/bin/python tools/load_test.py --url http://127.0.0.1:18766 --stations 5 --per 20 out/scans/*/frame.jpg
"""
import argparse
import base64
import json
import statistics
import threading
import time
import urllib.request


def call(url, path, body):
    req = urllib.request.Request(url + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:18766")
    ap.add_argument("--stations", type=int, default=5)
    ap.add_argument("--per", type=int, default=20, help="số phiếu mỗi bàn")
    ap.add_argument("images", nargs="+")
    a = ap.parse_args()
    if a.url.rstrip("/").endswith(":8766"):
        raise SystemExit("Không chạy đo thử vào máy chủ thật (cổng 8766). Bật máy chủ thử ở cổng khác.")
    imgs = ["data:image/jpeg;base64," + base64.b64encode(open(p, "rb").read()).decode() for p in a.images]
    lat, wait, read_ms, errs = [], [], [], []
    lock = threading.Lock()

    def station(k):
        for i in range(a.per):
            try:
                t0 = time.time()
                no = call(a.url, "/next", {})["no"]
                r = call(a.url, "/read", {"image": imgs[(k + i) % len(imgs)], "engine": "none", "stts": [1, 2, 6, 111], "no": no})
                t1 = time.time()
                b = {"no": no, "version": 1, "status": "valid", "votes": [], "scanId": r.get("scan"), "station": f"Bàn {k + 1}",
                     "rows": [], "photo": ""}
                call(a.url, "/ballot", {"ballot": b})
                with lock:
                    lat.append((t1 - t0) * 1000)
                    wait.append(r.get("waitMs", 0))
                    read_ms.append(r.get("ms", 0))
            except Exception as e:  # noqa: BLE001
                with lock:
                    errs.append(repr(e))

    t = time.time()
    th = [threading.Thread(target=station, args=(k,)) for k in range(a.stations)]
    [x.start() for x in th]
    [x.join() for x in th]
    total = time.time() - t
    q = lambda v, p: sorted(v)[min(len(v) - 1, int(len(v) * p))] if v else 0  # noqa: E731
    print(f"{a.stations} bàn x {a.per} phiếu = {len(lat)} phiếu trong {total:.1f} giây ({len(lat) / total:.1f} phiếu/giây), lỗi: {len(errs)}")
    print(f"Máy đọc 1 phiếu:          trung vị {statistics.median(read_ms):.0f} ms, chậm nhất {max(read_ms):.0f} ms")
    print(f"Chờ trong hàng đợi:       trung vị {statistics.median(wait):.0f} ms, 95% {q(wait, .95):.0f} ms, lâu nhất {max(wait):.0f} ms")
    print(f"Bàn chờ kết quả (gửi->về): trung vị {statistics.median(lat):.0f} ms, 95% {q(lat, .95):.0f} ms, lâu nhất {max(lat):.0f} ms")
    for e in errs[:5]:
        print("  lỗi:", e)


if __name__ == "__main__":
    main()
