#!/bin/bash
# Tạo chứng chỉ tự ký để các bàn khác (máy Windows) mở trang kiểm phiếu qua https và dùng được webcam.
# Trình duyệt chỉ cho dùng camera khi trang là https (hoặc localhost), nên bước này bắt buộc với các bàn khác.
# Chạy lại mỗi khi IP máy Mac đổi (vd đổi sang router khác). Hạn dùng 2 năm.
#   bash tools/make_cert.sh                # tự lấy IP hiện tại của máy Mac
#   bash tools/make_cert.sh 192.168.1.10   # hoặc ghi IP cố định (đặt IP tĩnh trên router thì tốt nhất)
cd "$(dirname "$0")/.."
IP="${1:-$(ipconfig getifaddr en0 || ipconfig getifaddr en1)}"
HOST="$(scutil --get LocalHostName 2>/dev/null || hostname -s)"
if [ -z "$IP" ]; then echo "Không thấy IP máy Mac. Nối Wi-Fi/router rồi chạy lại, hoặc ghi IP: bash tools/make_cert.sh 192.168.1.10"; exit 1; fi
mkdir -p config
openssl req -x509 -newkey rsa:2048 -nodes -days 730 \
  -keyout config/key.pem -out config/cert.pem \
  -subj "/CN=Kiem phieu ($HOST)" \
  -addext "subjectAltName=IP:$IP,IP:127.0.0.1,DNS:localhost,DNS:$HOST.local" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,digitalSignature,keyCertSign" \
  -addext "extendedKeyUsage=serverAuth" 2>/dev/null || { echo "Tạo chứng chỉ lỗi"; exit 1; }
cp config/cert.pem "config/kiem-phieu-cert.crt"
echo "Đã tạo chứng chỉ cho IP $IP ($HOST.local)."
echo "Các bàn khác mở: https://$IP:8443/"
echo "Để máy Windows không báo 'không an toàn': chép config/kiem-phieu-cert.crt sang máy đó, bấm đúp > Install Certificate"
echo "  > Local Machine > Place all certificates in: Trusted Root Certification Authorities > Finish. (Xem docs/ballot-scan/huong-dan-nhieu-ban.md)"
