"""Đọc họ tên trên phiếu bằng Gemini (Google AI Studio), chọn theo danh sách ứng viên. Bản THỬ, chưa gắn vào máy chủ.

Key: biến môi trường GEMINI_API_KEY, hoặc file config/gemini_key.txt (1 dòng).

Chạy:
  .venv/bin/python tools/llm_names.py --list-models          # xem key dùng được những mô hình nào
  .venv/bin/python tools/llm_names.py --model gemini-...      # đo trên các phiếu trong out/session/state.json
  thêm --limit N để chỉ thử N phiếu đầu, --show để in từng dòng sai.

Cách làm: mỗi phiếu gửi 1 lần: các dải ảnh ô họ tên có mực (đã nắn + cắt như máy chủ) kèm danh sách STT + tên.
Mô hình trả về STT của người mà nó cho là được ghi ở mỗi dòng (hoặc 0 nếu không rõ) và độ tin cậy.
Trả STT thay vì chữ để không phải so chính tả. STT trên phiếu vẫn do mạng chữ số đọc; tên chỉ để đối chiếu.

Đáp án để chấm: STT cuối cùng của dòng trong state.json (sau khi người duyệt sửa) -> tên trong danh sách.
Chỉ chấm dòng có STT nằm trong danh sách và ô tên có mực.
"""
import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path.insert(0, str(TOOLS))
_argv, sys.argv = sys.argv, sys.argv[:1]
import cv2  # noqa: E402
import numpy as np  # noqa: E402
from ocr_server import align, crop, ink, name_strip, LAYOUT, INSET, SCANS, STATE_FILE  # noqa: E402
sys.argv = _argv

API = "https://generativelanguage.googleapis.com/v1beta"


def api_key():
    k = os.environ.get("GEMINI_API_KEY", "").strip()
    f = ROOT / "config" / "gemini_key.txt"
    if not k and f.exists():
        k = f.read_text(encoding="utf-8").strip()
    if not k:
        sys.exit("Chưa có key: đặt GEMINI_API_KEY hoặc ghi key vào config/gemini_key.txt")
    return k


def _call(url, body=None, tries=5):
    # Key đi trong header, không đặt trên URL.
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
                                 headers={"Content-Type": "application/json", "x-goog-api-key": api_key()})
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=240) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="ignore")[:300]
            if e.code in (429, 500, 503) and i < tries - 1:
                wait = 15 * (i + 1)
                print(f"  API {e.code}, đợi {wait}s rồi thử lại...", flush=True)
                time.sleep(wait)
                continue
            raise RuntimeError(f"API lỗi {e.code}: {msg}")
        except TimeoutError:
            if i < tries - 1:
                print("  quá giờ, thử lại...", flush=True)
                continue
            raise RuntimeError("API quá giờ nhiều lần")
    raise RuntimeError("API không phản hồi")


def list_models():
    r = _call(f"{API}/models?pageSize=200")
    for m in r.get("models", []):
        if "generateContent" in m.get("supportedGenerationMethods", []):
            print(m["name"].removeprefix("models/"), "-", m.get("displayName", ""))


def name_strips(page):
    """[(dòng, png bytes)] cho các ô họ tên có mực."""
    out = []
    for row in LAYOUT["rows"]:
        g = cv2.cvtColor(crop(page, row["name_box"], INSET + 0.5), cv2.COLOR_BGR2GRAY)
        if ink(g) < 0.006:
            continue
        ok, buf = cv2.imencode(".png", name_strip(g))
        if ok:
            out.append((row["index"], buf.tobytes()))
    return out


PROMPT = """Đây là các ô "Họ và tên" viết tay trên một phiếu bầu cử tiếng Việt, mỗi ảnh là 1 dòng.
Mỗi dòng ghi tên 1 người trong DANH SÁCH ỨNG VIÊN bên dưới (người viết có thể viết tắt, thiếu dấu, sai chính tả nhẹ).
Với mỗi dòng, chọn người trong danh sách khớp nhất với chữ viết và trả STT của người đó.
Không đoán: nếu chữ không đọc được hoặc không giống ai rõ ràng thì trả stt = 0.
conf là độ chắc chắn 0..1. read là chữ anh/chị đọc được thô từ ảnh.

DANH SÁCH ỨNG VIÊN (STT. Họ tên):
{cands}
"""

SCHEMA = {
    "type": "OBJECT",
    "properties": {"rows": {"type": "ARRAY", "items": {
        "type": "OBJECT",
        "properties": {"line": {"type": "INTEGER"}, "read": {"type": "STRING"},
                       "stt": {"type": "INTEGER"}, "conf": {"type": "NUMBER"}},
        "required": ["line", "stt", "conf"]}}},
    "required": ["rows"],
}


OPTS = {"think": True, "stack": False}  # đổi qua tham số --no-think / --stack


def thinking_config(model):
    """Tắt (hoặc giảm tối đa) phần suy nghĩ trước khi trả lời: đây là phần làm chậm chính."""
    if "2.5" in model:
        return {"thinkingBudget": 0}
    return {"thinkingLevel": "minimal"}


def stacked_jpeg(strips):
    """Gộp các dải tên thành 1 ảnh, mỗi dải có số dòng in ở lề trái. 1 ảnh gửi nhanh hơn 18 ảnh rời."""
    h, gap, lab = 56, 10, 70
    imgs = [cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE) for _, png in strips]
    imgs = [cv2.resize(im, (max(1, int(im.shape[1] * h / im.shape[0])), h)) for im in imgs]
    w = lab + max(im.shape[1] for im in imgs) + 10
    canvas = np.full(((h + gap) * len(imgs) + gap, w), 255, np.uint8)
    for k, ((line, _), im) in enumerate(zip(strips, imgs)):
        y = gap + k * (h + gap)
        cv2.putText(canvas, str(line), (8, y + h - 16), cv2.FONT_HERSHEY_SIMPLEX, 1.1, 0, 2)
        canvas[y:y + h, lab:lab + im.shape[1]] = im
        cv2.line(canvas, (0, y + h + gap // 2), (w, y + h + gap // 2), 200, 1)
    ok, buf = cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return buf.tobytes()


def read_names(page, cands, model):
    """Trả {dòng: {"stt": int, "conf": float, "read": str}} cho các dòng có mực ở ô tên."""
    strips = name_strips(page)
    if not strips:
        return {}
    clist = "\n".join(f"{int(c['stt'])}. {c['name']}" for c in cands)
    parts = [{"text": PROMPT.format(cands=clist)}]
    if OPTS["stack"]:
        parts.append({"text": "Ảnh dưới gồm nhiều dòng xếp chồng; số in đậm ở lề trái là số dòng (line)."})
        parts.append({"inline_data": {"mime_type": "image/jpeg",
                                      "data": base64.b64encode(stacked_jpeg(strips)).decode()}})
    else:
        for line, png in strips:
            parts.append({"text": f"Dòng {line}:"})
            parts.append({"inline_data": {"mime_type": "image/png", "data": base64.b64encode(png).decode()}})
    gen = {"temperature": 0, "responseMimeType": "application/json", "responseSchema": SCHEMA}
    if not OPTS["think"]:
        gen["thinkingConfig"] = thinking_config(model)
    body = {"contents": [{"role": "user", "parts": parts}], "generationConfig": gen}
    try:
        r = _call(f"{API}/models/{model}:generateContent", body)
    except RuntimeError as e:
        if "thinking" not in str(e).lower() or "thinkingConfig" not in gen:
            raise
        gen["thinkingConfig"] = {"thinkingLevel": "low"}  # mô hình không cho "minimal" thì dùng mức thấp
        r = _call(f"{API}/models/{model}:generateContent", body)
    text = r["candidates"][0]["content"]["parts"][0]["text"]
    return {int(x["line"]): x for x in json.loads(text).get("rows", [])}


def bench(model, limit=None, show=False, pause=4.0):
    st = json.loads(Path(STATE_FILE).read_text(encoding="utf-8"))
    cands = st.get("cands", [])
    names = {f"{int(c['stt']):03d}": c["name"] for c in cands}
    latest = {}
    for b in (st.get("ballots") or {}).values():
        sid = b.get("scanId")
        if sid and (sid not in latest or (b.get("capturedAt") or 0) >= (latest[sid].get("capturedAt") or 0)):
            latest[sid] = b
    sids = sorted(latest)[:limit] if limit else sorted(latest)
    tot = ok = wrong = unsure = 0
    t_all = 0.0
    for sid in sids:
        fr = Path(SCANS) / sid / "frame.jpg"
        img = cv2.imread(str(fr)) if fr.exists() else None
        if img is None:
            continue
        page, aligned = align(img)
        if not aligned:
            print(f"{sid}: không nắn được, bỏ qua")
            continue
        truth = {r["line"]: r.get("stt") for r in latest[sid].get("rows", []) if r.get("stt") in names}
        t0 = time.time()
        try:
            got = read_names(page, cands, model)
        except RuntimeError as e:
            print(f"{sid}: {e}")
            break
        dt = time.time() - t0
        t_all += dt
        n = k = 0
        for line, stt in truth.items():
            if line not in got:
                continue  # ô tên không có mực
            g = got[line]
            n += 1
            if int(g.get("stt") or 0) == 0:
                unsure += 1
                res = "không rõ"
            elif f"{int(g['stt']):03d}" == stt:
                k += 1
                res = None
            else:
                wrong += 1
                res = f"chọn {int(g['stt']):03d} {names.get(f'{int(g['stt']):03d}', '?')}"
            if res and show:
                print(f"    dòng {line}: đúng {stt} {names[stt]} | {res} | đọc '{g.get('read', '')}' conf {g.get('conf')}")
        tot += n
        ok += k
        print(f"{sid}: {k}/{n} đúng  ({dt:.1f}s)", flush=True)
        time.sleep(pause)  # tier free giới hạn số lần gọi mỗi phút
    if tot:
        print(f"\n{model}: đúng {ok}/{tot} = {ok / tot:.1%} | chọn sai {wrong} | trả 'không rõ' {unsure}"
              f" | trung bình {t_all / max(len(sids), 1):.1f}s/phiếu")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list-models", action="store_true")
    ap.add_argument("--model", default="gemini-flash-lite-latest")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--no-think", action="store_true", help="tắt/giảm phần suy nghĩ của mô hình (nhanh hơn)")
    ap.add_argument("--stack", action="store_true", help="gộp các dòng thành 1 ảnh")
    a = ap.parse_args()
    OPTS["think"], OPTS["stack"] = not a.no_think, a.stack
    if a.list_models:
        list_models()
    else:
        bench(a.model, a.limit, a.show)


if __name__ == "__main__":
    main()
