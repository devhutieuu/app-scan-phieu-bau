"""Huấn luyện mạng nhỏ nhận dạng 1 chữ số viết tay (0-9) cho ô STT trên phiếu.

Chạy 1 lần:  .venv/bin/python tools/train_digits.py
Đầu ra:      tools/models/digits_cnn.pt  (máy đọc tools/ocr_server.py tự nạp nếu có)

Dữ liệu: MNIST (tải về tools/models/mnist lần đầu, sau đó dùng offline). Ảnh ô STT trên phiếu được
đưa về đúng dạng MNIST (nét trắng trên nền đen, 28x28, căn giữa theo trọng tâm) bằng `to_mnist()`
trong ocr_server.py, nên khi huấn luyện chỉ cần thêm biến dạng (xoay, co giãn, nét dày/mảnh, mờ).
"""
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision import datasets, transforms

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "models" / "digits_cnn.pt"


class DigitNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.c1 = nn.Conv2d(1, 32, 3, padding=1)
        self.c2 = nn.Conv2d(32, 64, 3, padding=1)
        self.c3 = nn.Conv2d(64, 128, 3, padding=1)
        self.bn1, self.bn2, self.bn3 = nn.BatchNorm2d(32), nn.BatchNorm2d(64), nn.BatchNorm2d(128)
        self.fc1 = nn.Linear(128 * 3 * 3, 128)
        self.fc2 = nn.Linear(128, 10)
        self.drop = nn.Dropout(0.3)

    def forward(self, x):
        x = F.max_pool2d(F.relu(self.bn1(self.c1(x))), 2)  # 14
        x = F.max_pool2d(F.relu(self.bn2(self.c2(x))), 2)  # 7
        x = F.max_pool2d(F.relu(self.bn3(self.c3(x))), 2)  # 3
        x = self.drop(F.relu(self.fc1(x.flatten(1))))
        return self.fc2(x)


class Thickness:
    """Làm nét dày hoặc mảnh ngẫu nhiên (bút bi / bút lông)."""

    def __call__(self, x):
        r = torch.rand(1).item()
        if r < 0.3:  # dày hơn
            return F.max_pool2d(x.unsqueeze(0), 3, 1, 1).squeeze(0)
        if r < 0.45:  # mảnh hơn
            return -F.max_pool2d(-x.unsqueeze(0), 3, 1, 1).squeeze(0)
        return x


def main():
    dev = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    aug = transforms.Compose([
        transforms.RandomAffine(degrees=12, translate=(0.08, 0.08), scale=(0.8, 1.1), shear=10),
        transforms.ToTensor(),
        Thickness(),
        transforms.RandomApply([transforms.GaussianBlur(3, sigma=(0.1, 0.9))], p=0.3),
    ])
    plain = transforms.ToTensor()
    data = ROOT / "models" / "mnist"
    train = datasets.MNIST(data, train=True, download=True, transform=aug)
    test = datasets.MNIST(data, train=False, download=True, transform=plain)
    tl = torch.utils.data.DataLoader(train, batch_size=256, shuffle=True, num_workers=0)
    vl = torch.utils.data.DataLoader(test, batch_size=1000)

    net = DigitNet().to(dev)
    opt = torch.optim.AdamW(net.parameters(), lr=2e-3, weight_decay=1e-4)
    epochs = 6
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=3e-3, total_steps=epochs * len(tl))
    for ep in range(epochs):
        net.train()
        for x, y in tl:
            x, y = x.to(dev), y.to(dev)
            loss = F.cross_entropy(net(x), y, label_smoothing=0.05)
            opt.zero_grad()
            loss.backward()
            opt.step()
            sched.step()
        net.eval()
        ok = n = 0
        with torch.no_grad():
            for x, y in vl:
                p = net(x.to(dev)).argmax(1).cpu()
                ok += (p == y).sum().item()
                n += len(y)
        print(f"epoch {ep + 1}/{epochs}  độ chính xác MNIST test: {ok / n:.4f}", flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    torch.save(net.to("cpu").state_dict(), OUT)
    print(f"Đã lưu {OUT}")


if __name__ == "__main__":
    main()
