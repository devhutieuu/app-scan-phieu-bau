"""Tinh chỉnh (fine-tune) mạng nhận dạng chữ số STT trên chính các ô viết tay thật của phiếu.

Chạy:  .venv/bin/python tools/finetune_digits.py [--holdout SCAN_ID ...] [--dry]
  --holdout SCAN_ID ...  các bản quét giữ lại làm tập kiểm tra (không dùng để huấn luyện) -> điểm trung thực.
                         Không đưa --holdout thì kiểm tra ngay trên dữ liệu đã học (điểm KHÔNG trung thực).
  --dry                  chỉ thử: lưu ra tools/models/digits_cnn_try.pt, không đụng digits_cnn.pt.

Nguồn dữ liệu:
  1. Phiếu đã được người duyệt bấm Chấp nhận: out/scans/<id>/truth.json (các dòng có STT đủ 3 chữ số).
  2. File gán nhãn tay tools/models/digit_labels.json: {"<scan_id>": ["001","111",...]} (mỗi phần tử là STT
     của 1 dòng từ dòng 1, "" = bỏ qua). File này ghi đè truth.json cho bản quét tương ứng.
  3. Kho phiếu dùng chung của máy chủ (STATE_FILE = out/session/state.json, phiếu nhận trên điện thoại không có
     truth.json). Chỉ lấy dòng đã được kiểm chứng: STT đủ 3 chữ số VÀ (người duyệt đã sửa tay: o0.stt khác stt,
     HOẶC STT nằm trong danh sách ứng viên cands). Số ngoài danh sách mà không ai sửa (vd "000") bị bỏ vì có thể
     chỉ là dòng người duyệt để trống. Bản quét trùng nhiều phiếu thì lấy phiếu mới nhất.
  Ưu tiên: digit_labels.json > truth.json > state.json (theo từng bản quét).
Mỗi ô STT có mực được đưa qua to_mnist() của ocr_server.py (đúng dạng máy chủ đọc), trộn với một phần MNIST
để mạng không quên chữ số chuẩn. Có mẫu phiếu mới được duyệt thì chạy lại để mạng khá dần.
Bản gốc (MNIST thuần) được sao lưu 1 lần ở tools/models/digits_cnn_mnist.pt.
"""
import argparse
import json
import random
import shutil
import sys
from collections import Counter
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))
_argv = sys.argv
sys.argv = sys.argv[:1]  # ocr_server không đọc tham số khi import, nhưng đề phòng
import cv2  # noqa: E402
import numpy as np  # noqa: E402
import torch  # noqa: E402
import torch.nn.functional as F  # noqa: E402
from torchvision import datasets, transforms  # noqa: E402

from ocr_server import align, crop, snap_cells, LAYOUT, INSET, ink, to_mnist, SCANS, STATE_FILE  # noqa: E402
from train_digits import DigitNet, Thickness  # noqa: E402
sys.argv = _argv

MODELS = TOOLS / "models"
CUR = MODELS / "digits_cnn.pt"
BACKUP = MODELS / "digits_cnn_mnist.pt"
TRY = MODELS / "digits_cnn_try.pt"
MANUAL = MODELS / "digit_labels.json"
MEAN, STD = 0.1307, 0.3081  # ocr_server.to_mnist trả ảnh đã chuẩn hóa theo MNIST


def labels_from_state(skip_ids):
    """Nhãn từ kho phiếu chung. Trả (dict scan_id -> list STT, số dòng bị bỏ vì chưa kiểm chứng)."""
    try:
        st = json.loads(Path(STATE_FILE).read_text(encoding="utf-8"))
    except Exception:
        return {}, 0
    cands = set()
    for c in st.get("cands", []):
        try:
            cands.add(f"{int(c.get('stt')):03d}")
        except Exception:
            pass
    latest = {}  # scan_id -> phiếu mới nhất
    for k, b in (st.get("ballots") or {}).items():
        sid = b.get("scanId")
        if not sid:
            continue
        try:
            key = (b.get("capturedAt") or 0, int(b.get("no") or k))
        except Exception:
            key = (b.get("capturedAt") or 0, 0)
        if sid not in latest or key >= latest[sid][0]:
            latest[sid] = (key, b)
    out, skipped = {}, 0
    for sid, (_, b) in latest.items():
        if sid in skip_ids or not (Path(SCANS) / sid / "frame.jpg").exists():
            continue
        labs = []
        for r in b.get("rows", []):
            s = r.get("stt")
            if not (isinstance(s, str) and len(s) == 3 and s.isdigit()):
                labs.append("")
                continue
            o0 = (r.get("o0") or {}).get("stt")
            corrected = o0 is not None and o0 != s
            if corrected or s in cands:
                labs.append(s)
            else:
                labs.append("")
                skipped += 1
        out[sid] = labs
    return out, skipped


def collect_labels():
    """Trả dict scan_id -> list STT theo dòng (từ dòng 1), "" = bỏ qua. Ưu tiên: tay > truth.json > state.json."""
    out = {}
    src = {}  # scan_id -> nguồn
    for d in sorted(Path(SCANS).glob("*/")):
        tf = d / "truth.json"
        if not tf.exists():
            continue
        try:
            rows = json.loads(tf.read_text(encoding="utf-8")).get("rows", [])
        except Exception:
            continue
        labs = []
        for r in rows:
            s = r.get("stt")
            labs.append(s if isinstance(s, str) and len(s) == 3 and s.isdigit() else "")
        out[d.name] = labs
        src[d.name] = "truth.json"
    if MANUAL.exists():
        for k, v in json.loads(MANUAL.read_text(encoding="utf-8")).items():
            out[k] = v
            src[k] = "digit_labels.json"
    st, skipped = labels_from_state(set(out))
    for k, v in st.items():
        out[k] = v
        src[k] = "state.json"
    n = {"digit_labels.json": 0, "truth.json": 0, "state.json": 0}
    for k, v in out.items():
        n[src[k]] += sum(1 for x in v if len(x) == 3 and x.isdigit())
    print("Số dòng có nhãn theo nguồn:", n)
    print(f"Số dòng state.json bị bỏ vì chưa kiểm chứng (ngoài danh sách, không ai sửa): {skipped}")
    return out


def build_cells(labels):
    """Cắt các ô STT có nhãn. Trả list (ảnh 28x28 float32, chữ số, scan_id)."""
    cells = []
    for sid, labs in labels.items():
        fr = Path(SCANS) / sid / "frame.jpg"
        img = cv2.imread(str(fr)) if fr.exists() else None
        if img is None:
            print(f"  bỏ qua {sid}: không có frame.jpg")
            continue
        page, ok = align(img)
        if not ok:
            print(f"  bỏ qua {sid}: không nắn được phiếu")
            continue
        for row, stt in zip(LAYOUT["rows"], labs):
            if len(stt) != 3 or not stt.isdigit():
                continue
            for cell, dg in zip(snap_cells(page, row), stt):
                g = cv2.cvtColor(crop(page, cell, INSET + 0.6), cv2.COLOR_BGR2GRAY)
                if ink(g) < 0.003:
                    continue
                t = to_mnist(g)
                if t is None:
                    continue
                cells.append((t.astype(np.float32), int(dg), sid))
    return cells


def predict(net, cells, dev):
    x = torch.from_numpy(np.stack([c[0] for c in cells])[:, None]).float().to(dev)
    net.eval()
    with torch.no_grad():
        return torch.softmax(net(x), 1).cpu().numpy()


def evaluate(net, cells, dev, title):
    P = predict(net, cells, dev)
    pred = P.argmax(1)
    wrong = [(c[2], c[1], int(p), float(P[i, p])) for i, (c, p) in enumerate(zip(cells, pred)) if p != c[1]]
    acc = 1 - len(wrong) / len(cells)
    print(f"[{title}] độ chính xác {acc:.4f} ({len(cells) - len(wrong)}/{len(cells)})")
    for sid, t, p, pr in wrong:
        print(f"    sai: scan {sid}  đúng {t}  đọc {p}  xác suất {pr:.2f}")
    return acc, len(wrong)


class RealCells(torch.utils.data.Dataset):
    """Ô thật, tăng cường dữ liệu trên tensor. Ảnh chuẩn hóa MNIST -> đưa về [0,1] để biến dạng (nền = 0) rồi chuẩn hóa lại."""

    def __init__(self, cells, n):
        self.x = [torch.from_numpy(c[0] * STD + MEAN).clamp(0, 1).unsqueeze(0) for c in cells]
        self.y = [c[1] for c in cells]
        self.n = n
        self.aff = transforms.RandomAffine(degrees=12, translate=(0.1, 0.1), scale=(0.8, 1.15), shear=10)
        self.thick = Thickness()
        self.blur = transforms.RandomApply([transforms.GaussianBlur(3, sigma=(0.1, 0.9))], p=0.3)

    def __len__(self):
        return self.n

    def __getitem__(self, i):
        j = random.randrange(len(self.x))
        x = self.blur(self.thick(self.aff(self.x[j])))
        return (x - MEAN) / STD, self.y[j]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdout", nargs="*", default=[], help="scan_id dùng làm tập kiểm tra")
    ap.add_argument("--dry", action="store_true", help="lưu ra digits_cnn_try.pt, không ghi đè mô hình đang dùng")
    a = ap.parse_args()
    dev = torch.device("mps" if torch.backends.mps.is_available() else "cpu")

    labels = collect_labels()
    print(f"Số bản quét có nhãn: {len(labels)}")
    cells = build_cells(labels)
    if not cells:
        print("Không có ô nào dùng được.")
        return
    print("Số ô theo chữ số:", dict(sorted(Counter(c[1] for c in cells).items())))
    print("Số ô theo bản quét:", dict(sorted(Counter(c[2] for c in cells).items())))

    hold = set(a.holdout)
    train = [c for c in cells if c[2] not in hold]
    test = [c for c in cells if c[2] in hold]
    if not test:
        test = train
        print("CẢNH BÁO: không có --holdout, kiểm tra trên chính dữ liệu đã học nên điểm KHÔNG trung thực.")
    if not train:
        print("Không còn ô nào để huấn luyện (holdout lấy hết).")
        return
    print(f"Huấn luyện {len(train)} ô, kiểm tra {len(test)} ô")

    net = DigitNet().to(dev)
    net.load_state_dict(torch.load(CUR, map_location=dev))
    acc0, _ = evaluate(net, test, dev, "TRƯỚC")

    norm = transforms.Normalize((MEAN,), (STD,))
    aug = transforms.Compose([
        transforms.RandomAffine(degrees=12, translate=(0.08, 0.08), scale=(0.8, 1.1), shear=10),
        transforms.ToTensor(),
        Thickness(),
        transforms.RandomApply([transforms.GaussianBlur(3, sigma=(0.1, 0.9))], p=0.3),
        norm,
    ])
    mn = MODELS / "mnist"
    mtrain = datasets.MNIST(mn, train=True, download=False, transform=aug)
    mtest = datasets.MNIST(mn, train=False, download=False, transform=transforms.Compose([transforms.ToTensor(), norm]))
    vl = torch.utils.data.DataLoader(mtest, batch_size=1000)

    def mnist_acc():
        net.eval()
        ok = n = 0
        with torch.no_grad():
            for x, y in vl:
                ok += (net(x.to(dev)).argmax(1).cpu() == y).sum().item()
                n += len(y)
        return ok / n

    print(f"MNIST test trước khi tinh chỉnh: {mnist_acc():.4f}")
    real = RealCells(train, 3000)
    opt = torch.optim.AdamW(net.parameters(), lr=5e-4, weight_decay=1e-4)
    epochs = 8
    for ep in range(epochs):
        sub = torch.utils.data.Subset(mtrain, random.sample(range(len(mtrain)), 6000))
        dl = torch.utils.data.DataLoader(torch.utils.data.ConcatDataset([sub, real]), batch_size=128, shuffle=True, num_workers=0)
        net.train()
        tot = 0.0
        for x, y in dl:
            x, y = x.to(dev), torch.as_tensor(y).to(dev)
            loss = F.cross_entropy(net(x), y, label_smoothing=0.05)
            opt.zero_grad()
            loss.backward()
            opt.step()
            tot += loss.item() * len(y)
        print(f"epoch {ep + 1}/{epochs}  loss {tot / len(dl.dataset):.4f}", flush=True)
    print(f"MNIST test sau khi tinh chỉnh: {mnist_acc():.4f}")

    acc1, _ = evaluate(net, test, dev, "SAU")
    print(f"So sánh trên tập kiểm tra: trước {acc0:.4f}  ->  sau {acc1:.4f}")

    net = net.to("cpu")
    if a.dry:
        torch.save(net.state_dict(), TRY)
        print(f"Chạy thử: đã lưu {TRY} (digits_cnn.pt giữ nguyên)")
    else:
        if not BACKUP.exists():
            shutil.copy2(CUR, BACKUP)
            print(f"Đã sao lưu bản gốc: {BACKUP}")
        torch.save(net.state_dict(), CUR)
        print(f"Đã lưu {CUR}")


if __name__ == "__main__":
    main()
