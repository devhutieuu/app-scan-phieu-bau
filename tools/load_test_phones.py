"""Giả lập nhiều điện thoại quét phiếu cùng lúc, đúng nhịp trang ballot-scan-phone.html.

Mỗi điện thoại (qua https như máy thật):
  - hỏi /state 2 giây/lần (kèm tên máy)
  - lúc ngắm phiếu: gửi khung hình nhỏ lên /detect ~6 lần/giây
  - chụp: /read (ảnh 2400 px) -> /next -> hỏi /names 1,5 giây/lần trong lúc người duyệt xem phiếu -> /ballot (kèm ảnh đã nắn)

CHỈ chạy vào máy chủ thử (ghi phiếu giả vào kho):
  KP_PORT=18766 KP_HTTPS_PORT=18443 KP_SESSION=/tmp/kp/sess KP_SCANS=/tmp/kp/scans .venv/bin/python tools/ocr_server.py
  .venv/bin/python tools/load_test_phones.py --phones 10 --secs 120 out/scans/*/frame.jpg
"""
import argparse
import base64
import http.client
import json
import random
import ssl
import subprocess
import threading
import time
import urllib.parse

import cv2

CTX = ssl._create_unverified_context()


class Conn:
    """1 kết nối giữ mở (như trình duyệt); đứt thì nối lại."""

    def __init__(self, url, station):
        u = urllib.parse.urlparse(url)
        self.https, self.host, self.port, self.c = u.scheme == "https", u.hostname, u.port, None
        self.station = urllib.parse.quote(station)

    def call(self, method, path, body=None, ctype="application/json"):
        for attempt in (0, 1):
            try:
                if self.c is None:
                    self.c = (http.client.HTTPSConnection(self.host, self.port, timeout=120, context=CTX) if self.https
                              else http.client.HTTPConnection(self.host, self.port, timeout=120))
                self.c.request(method, path, body=body, headers={"Content-Type": ctype, "X-Station": self.station})
                r = self.c.getresponse()
                data = r.read()
                return r.status, (json.loads(data) if data else {})
            except (http.client.HTTPException, OSError):
                self.c = None
                if attempt:
                    raise


def pct(v, p):
    v = sorted(v)
    return v[min(len(v) - 1, int(len(v) * p))] if v else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://127.0.0.1:18443")
    ap.add_argument("--phones", type=int, default=10)
    ap.add_argument("--secs", type=int, default=120)
    ap.add_argument("--aim", type=float, default=3.0, help="giây đặt/ngắm phiếu trước khi máy tự chụp")
    ap.add_argument("--review", type=float, nargs=2, default=[6, 12], help="giây người duyệt xem 1 phiếu (từ, đến)")
    ap.add_argument("--pids", default="", help="PID các tiến trình cần đo CPU/RAM, cách nhau dấu phẩy")
    ap.add_argument("images", nargs="+")
    a = ap.parse_args()
    if ":8766" in a.url or ":8443" in a.url:
        raise SystemExit("Không chạy đo thử vào máy chủ thật (cổng 8766/8443). Bật máy chủ thử ở cổng khác.")

    frames = []
    for p in a.images:
        raw = open(p, "rb").read()
        im = cv2.imread(p)
        k = min(1, 800 / max(im.shape[:2]))
        small = cv2.imencode(".jpg", cv2.resize(im, None, fx=k, fy=k), [cv2.IMWRITE_JPEG_QUALITY, 70])[1].tobytes()
        frames.append(("data:image/jpeg;base64," + base64.b64encode(raw).decode(), small))

    M = {k: [] for k in ("detect", "read", "wait", "ms", "state", "ballot", "names", "errs")}
    C = {"ballots": 0, "noscan": 0, "names_late": 0, "names_ok": 0, "names_off": 0, "dup": 0}
    lock = threading.Lock()
    stop = time.time() + a.secs

    def rec(k, v):
        with lock:
            M[k].append(v)

    def timed(k, conn, *args):
        t = time.time()
        st, j = conn.call(*args)
        rec(k, (time.time() - t) * 1000)
        if st >= 400:
            raise RuntimeError(f"{args[1]} -> {st} {j.get('error')}")
        return j

    def poller(name):
        conn, rev, ep = Conn(a.url, name), 0, None
        while time.time() < stop:
            try:
                j = timed("state", conn, "GET", f"/state?since={rev}" + (f"&epoch={ep}" if ep else ""))
                rev, ep = j["rev"], j["epoch"]
            except Exception as e:  # noqa: BLE001
                rec("errs", "state: " + repr(e))
            time.sleep(2)

    def phone(k):
        name = f"ĐT {k + 1}"
        rnd = random.Random(k)
        conn = Conn(a.url, name)
        threading.Thread(target=poller, args=(name,), daemon=True).start()
        time.sleep(rnd.uniform(0, 5))
        i = k * 7
        while time.time() < stop:
            img, small = frames[i % len(frames)]
            i += 1
            try:
                t_end = time.time() + a.aim
                while time.time() < t_end:
                    t0 = time.time()
                    timed("detect", conn, "POST", "/detect", small, "image/jpeg")
                    time.sleep(max(0.06, 0.16 - (time.time() - t0)))
                t0 = time.time()
                r = timed("read", conn, "POST", "/read", json.dumps({"image": img, "engine": "none", "stts": list(range(1, 202))}))
                rec("wait", r.get("waitMs", 0))
                rec("ms", r.get("ms", 0))
                no = timed("ballot", conn, "POST", "/next", "{}")["no"]
                scan, names = r.get("scan"), r.get("names")
                with lock:
                    C["noscan"] += not scan
                    C["dup"] += bool(r.get("dupOf"))
                    C["names_off"] += names != "wait"
                t_accept, got = t0 + rnd.uniform(*a.review), names != "wait"
                while time.time() < t_accept:
                    time.sleep(min(1.5, max(0, t_accept - time.time())))
                    if not got and time.time() < t_accept:
                        j = timed("names", conn, "GET", f"/names?scan={scan}")
                        if j.get("state") != "wait":
                            got = True
                            rec("names", (time.time() - t0) * 1000)
                with lock:
                    if names == "wait":
                        C["names_ok" if got else "names_late"] += 1
                b = {"no": no, "version": 1, "status": "valid", "votes": [], "scanId": scan, "station": name, "source": "camera",
                     "rows": [{"stt": x.get("stt", "")} for x in r.get("rows", [])], "photo": r.get("page") or ""}
                timed("ballot", conn, "POST", "/ballot", json.dumps({"ballot": b}))
                with lock:
                    C["ballots"] += 1
            except Exception as e:  # noqa: BLE001
                rec("errs", repr(e))
                time.sleep(1)

    usage = {}

    def watch():
        pids = [p for p in a.pids.split(",") if p]
        while pids and time.time() < stop:
            out = subprocess.run(["ps", "-o", "pid=,%cpu=,rss=", "-p", ",".join(pids)], capture_output=True, text=True).stdout
            for line in out.splitlines():
                pid, cpu, rss = line.split()
                usage.setdefault(pid, []).append((float(cpu), int(rss) / 1024))
            time.sleep(2)

    t = time.time()
    th = [threading.Thread(target=phone, args=(k,)) for k in range(a.phones)] + [threading.Thread(target=watch)]
    [x.start() for x in th]
    [x.join() for x in th]
    total = time.time() - t

    print(f"\n{a.phones} điện thoại, {total:.0f} giây: ghi nhận {C['ballots']} phiếu ({C['ballots'] / total * 60:.0f} phiếu/phút), lỗi: {len(M['errs'])}")
    for k, label in (("detect", "Dò 4 góc (/detect)"), ("read", "Đọc phiếu (/read) gửi->về"), ("wait", "  trong đó chờ hàng đợi"),
                     ("ms", "  trong đó máy đọc"), ("ballot", "Xin số + ghi phiếu"), ("state", "Hỏi kho phiếu (/state)")):
        v = M[k]
        if v:
            print(f"{label:28s} {len(v):5d} lần · trung vị {pct(v, .5):6.0f} ms · 95% {pct(v, .95):6.0f} ms · lâu nhất {max(v):6.0f} ms")
    n = C["names_ok"] + C["names_late"]
    print(f"Kiểm tên: xếp hàng {n} phiếu · có kết quả trước khi người duyệt bấm: {C['names_ok']} · CHƯA có khi bấm: {C['names_late']}"
          f" · không kiểm (dịch vụ tắt/ảnh không nắn được): {C['names_off']}")
    if M["names"]:
        print(f"  thời gian chờ kiểm tên (từ lúc chụp): trung vị {pct(M['names'], .5) / 1000:.1f} giây · lâu nhất {max(M['names']) / 1000:.1f} giây")
    print(f"Bản quét không lưu được (scan rỗng): {C['noscan']} · báo trùng: {C['dup']}")
    for pid, v in usage.items():
        print(f"PID {pid}: CPU trung bình {sum(x[0] for x in v) / len(v):.0f}% · cao nhất {max(x[0] for x in v):.0f}% · RAM cao nhất {max(x[1] for x in v):.0f} MB")
    seen = {}
    for e in M["errs"]:
        seen[e] = seen.get(e, 0) + 1
    for e, c in sorted(seen.items(), key=lambda x: -x[1])[:6]:
        print(f"  lỗi x{c}: {e[:200]}")


if __name__ == "__main__":
    main()
