"""Đo cách "đối chiếu tên" (tools/name_verify.py) trên các phiếu đã duyệt trong out/session/state.json.

Năm bước, mỗi máy đọc chạy trong môi trường riêng (kết quả trung gian nằm ở out/namebench/):
  .venv/bin/python     tools/bench_verify.py strips   # cắt ô họ tên có mực + STT sau khi người duyệt sửa
  .venv-tf/bin/python  tools/bench_verify.py crnn     # CRNN: lưu bảng xác suất từng ô
  .venv/bin/python     tools/bench_verify.py viet     # VietOCR: chấm từng tên trong danh sách
  .venv-mlx/bin/python tools/bench_verify.py qwen     # Qwen2.5-VL: chép tự do từng ô (~1 giây/ô)
  .venv/bin/python     tools/bench_verify.py eval     # chấm điểm

Đáp án "người thật sự được ghi tên": mặc định là người mang STT đã duyệt; riêng các ô mà chữ viết rõ ràng là người
khác thì sửa tay trong out/namebench/truth_fix.json ({mã ô: STT đúng, hoặc null nếu tên ngoài danh sách}).
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
OUT = ROOT / "out" / "namebench"
sys.path.insert(0, str(TOOLS))


def strips():
    _argv, sys.argv = sys.argv, sys.argv[:1]
    from ocr_server import align, crop, ink, name_strip, LAYOUT, INSET, SCANS, STATE_FILE
    sys.argv = _argv
    st = json.loads(Path(STATE_FILE).read_text(encoding="utf-8"))
    names = {f"{int(c['stt']):03d}": c["name"] for c in st["cands"]}
    latest = {}
    for b in (st.get("ballots") or {}).values():
        sid = b.get("scanId")
        if sid and (sid not in latest or (b.get("capturedAt") or 0) >= (latest[sid].get("capturedAt") or 0)):
            latest[sid] = b
    (OUT / "strips").mkdir(parents=True, exist_ok=True)
    items = []
    for sid, b in sorted(latest.items()):
        img = cv2.imread(str(Path(SCANS) / sid / "frame.jpg"))
        if img is None:
            continue
        page, ok = align(img)
        if not ok:
            continue
        rows = {r["index"]: r for r in LAYOUT["rows"]}
        for r in b.get("rows", []):
            stt = r.get("stt")
            if stt not in names or r["line"] not in rows:
                continue
            g = cv2.cvtColor(crop(page, rows[r["line"]]["name_box"], INSET + 0.5), cv2.COLOR_BGR2GRAY)
            if ink(g) < 0.006:
                continue
            key = f"{sid}_{r['line']:02d}"
            cv2.imwrite(str(OUT / "strips" / f"{key}.png"), name_strip(g))
            items.append({"key": key, "scan": sid, "line": r["line"], "stt": stt, "name": names[stt],
                          "sttRead": (r.get("ocr") or {}).get("stt", "")})
    (OUT / "labels.json").write_text(json.dumps({"cands": st["cands"], "items": items}, ensure_ascii=False, indent=1),
                                     encoding="utf-8")
    print(f"{len(items)} ô họ tên từ {len(latest)} phiếu -> {OUT}")


def crnn():
    import crnn_server as cs
    lab = json.loads((OUT / "labels.json").read_text(encoding="utf-8"))
    out = {}
    for it in lab["items"]:
        g = cv2.imread(str(OUT / "strips" / f"{it['key']}.png"), cv2.IMREAD_GRAYSCALE)
        p = cs.MODEL.predict(cs.prep(g), verbose=0)[0]
        out[it["key"]] = np.log(np.clip(p, 1e-12, 1)).astype(np.float32)
    np.savez_compressed(OUT / "crnn_logp.npz", **out)
    (OUT / "crnn_chars.json").write_text(json.dumps(cs.CHARS, ensure_ascii=False), encoding="utf-8")
    print(f"đã lưu bảng xác suất của {len(out)} ô")


def qwen():
    """Qwen2.5-VL (cục bộ, mlx) chép tự do từng ô -> out/namebench/qwen_free.json (ghi dần, chạy lại thì làm tiếp)."""
    import time
    from mlx_vlm import generate, load
    from mlx_vlm.prompt_utils import apply_chat_template
    from mlx_vlm.utils import load_config
    name = "mlx-community/Qwen2.5-VL-7B-Instruct-4bit"
    prompt_txt = ("Ảnh là một ô họ tên viết tay tiếng Việt trên phiếu bầu. Hãy chép lại chính xác họ tên được viết, "
                  "giữ đúng dấu tiếng Việt và đúng như chữ trên giấy, kể cả khi viết sai hoặc viết tắt. "
                  "Chỉ trả về họ tên, không giải thích.")
    model, proc = load(name)
    prompt = apply_chat_template(proc, load_config(name), prompt_txt, num_images=1)
    lab = json.loads((OUT / "labels.json").read_text(encoding="utf-8"))
    f = OUT / "qwen_free.json"
    res = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    for it in lab["items"]:
        if it["key"] in res:
            continue
        t0 = time.time()
        out = generate(model, proc, prompt, [str(OUT / "strips" / f"{it['key']}.png")], max_tokens=32,
                       temperature=0.0, verbose=False)
        text = " ".join(str(getattr(out, "text", out)).strip().strip('"').split())
        res[it["key"]] = {"text": text, "ms": int((time.time() - t0) * 1000)}
        print(it["name"], "|", text, "|", res[it["key"]]["ms"], "ms", flush=True)
        f.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


def viet():
    """VietOCR chấm từng tên (chữ thường lẫn CHỮ HOA, lấy điểm cao hơn), trừ điểm của chính chuỗi nó tự đọc ra."""
    import torch
    from PIL import Image
    _argv, sys.argv = sys.argv, sys.argv[:1]
    from ocr_server import vietocr_predictor
    sys.argv = _argv
    from vietocr.tool.translate import process_input, translate
    lab = json.loads((OUT / "labels.json").read_text(encoding="utf-8"))
    names = [c["name"] for c in lab["cands"]]
    p = vietocr_predictor()
    ds, V, m = p.config["dataset"], p.vocab, p.model
    variants = names + [n.upper() for n in names]
    out = {}
    with torch.no_grad():
        for it in lab["items"]:
            g = cv2.imread(str(OUT / "strips" / f"{it['key']}.png"), cv2.IMREAD_GRAYSCALE)
            img = process_input(Image.fromarray(g).convert("RGB"), ds["image_height"], ds["image_min_width"], ds["image_max_width"])
            mem = m.transformer.forward_encoder(m.cnn(img))
            free = V.decode(translate(img, m)[0][0].tolist())
            ids = [V.encode([ch for ch in t if ch in V.c2i]) for t in variants + [free]]
            A = torch.zeros(max(map(len, ids)), len(ids), dtype=torch.long)
            for i, x in enumerate(ids):
                A[:len(x), i] = torch.tensor(x)
            lp = torch.log_softmax(m.transformer.forward_decoder(A[:-1], mem.repeat(1, len(ids), 1))[0], -1)
            tgt = A[1:].T
            sc = (lp.gather(2, tgt.unsqueeze(-1)).squeeze(-1) * (tgt != 0)).sum(1).numpy()
            sc = sc[:-1] - sc[-1]
            out[it["key"]] = np.maximum(sc[:len(names)], sc[len(names):]).astype(np.float32)
    np.savez_compressed(OUT / "viet_scores.npz", **out)
    print(f"đã chấm {len(out)} ô")


def evaluate():
    from name_verify import CtcScorer, check, fuse, sim, TOP_K
    lab = json.loads((OUT / "labels.json").read_text(encoding="utf-8"))
    fix = json.loads((OUT / "truth_fix.json").read_text(encoding="utf-8")) if (OUT / "truth_fix.json").exists() else {}
    qw = json.loads((OUT / "qwen_free.json").read_text(encoding="utf-8"))
    Z, VS = np.load(OUT / "crnn_logp.npz"), np.load(OUT / "viet_scores.npz")
    ctc = CtcScorer(json.loads((OUT / "crnn_chars.json").read_text(encoding="utf-8")))
    names = [c["name"] for c in lab["cands"]]
    pos = {f"{int(c['stt']):03d}": i for i, c in enumerate(lab["cands"])}
    hit = {k: 0 for k in ("CRNN", "VietOCR", "Qwen", "ghép cả ba")}
    n_in = passed = same = caught = diff = 0
    missed, flagged = [], []
    for it in lab["items"]:
        k = it["key"]
        true = fix.get(k, it["stt"])
        c, v, text = ctc.score(Z[k], names), VS[k], qw[k]["text"]
        f = fuse(c, v, text, names)
        if true:
            n_in += 1
            t = pos[true]
            for label, s in (("CRNN", c), ("VietOCR", v), ("Qwen", np.array([sim(text, n) for n in names])), ("ghép cả ba", f)):
                hit[label] += int((s > s[t]).sum() == 0)
        r = check(f, pos[it["stt"]])
        if true == it["stt"]:
            same += 1
            passed += r["ok"]
            if not r["ok"]:
                flagged.append(f"  {k}: {it['name']} | Qwen đọc '{text}' | hạng {r['rank']}, khớp nhất {names[r['best']]}")
        else:
            diff += 1
            caught += not r["ok"]
            if r["ok"]:
                missed.append(k)
    print(f"{len(lab['items'])} ô họ tên, {n_in} ô ghi người trong danh sách\n")
    print("Tìm đúng người chỉ từ chữ viết (1 trong %d):" % len(names))
    for label, h in hit.items():
        print(f"  {label:12s} {h}/{n_in} = {h / n_in:.1%}")
    print(f"\nKiểm chéo với STT đã duyệt (cho qua khi người theo STT nằm trong {TOP_K} tên khớp nhất):")
    print(f"  dòng STT và tên là cùng 1 người: cho qua {passed}/{same} = {passed / same:.1%}, tô vàng oan {same - passed}")
    print(f"  dòng STT và tên là 2 người khác nhau (hoặc tên ngoài danh sách): bắt được {caught}/{diff}" + (f", lọt {missed}" if missed else ""))
    if "--show" in sys.argv:
        print("\nCác dòng đúng mà bị tô vàng:")
        print("\n".join(flagged))


if __name__ == "__main__":
    {"strips": strips, "crnn": crnn, "viet": viet, "qwen": qwen, "eval": evaluate}[sys.argv[1]]()
