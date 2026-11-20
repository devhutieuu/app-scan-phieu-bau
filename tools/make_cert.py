"""Tạo chứng chỉ tự ký cho https (bản chạy được trên Windows; trên Mac vẫn dùng tools/make_cert.sh như cũ).

  .venv\\Scripts\\python.exe tools\\make_cert.py                 # tự lấy IP hiện tại
  .venv\\Scripts\\python.exe tools\\make_cert.py 192.168.1.10    # hoặc ghi IP cố định
Ra config/key.pem, config/cert.pem, config/kiem-phieu-cert.crt (hạn 2 năm).
"""
import datetime
import ipaddress
import shutil
import socket
import sys
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

ROOT = Path(__file__).resolve().parent.parent
CONF = ROOT / "config"


def lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except Exception:  # noqa: BLE001
        return None


def main():
    ip = sys.argv[1] if len(sys.argv) > 1 else lan_ip()
    if not ip or ip.startswith("127."):
        sys.exit("Không thấy IP máy. Nối Wi-Fi/router rồi chạy lại, hoặc ghi IP: make_cert.py 192.168.1.10")
    host = socket.gethostname()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"Kiem phieu ({host})")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=730))
            .add_extension(x509.SubjectAlternativeName([
                x509.IPAddress(ipaddress.ip_address(ip)), x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                x509.DNSName("localhost"), x509.DNSName(host)]), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, content_commitment=False,
                                         key_encipherment=False, data_encipherment=False, key_agreement=False,
                                         crl_sign=False, encipher_only=False, decipher_only=False), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(key, hashes.SHA256()))
    CONF.mkdir(exist_ok=True)
    (CONF / "key.pem").write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                                                      serialization.NoEncryption()))
    (CONF / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    shutil.copy(CONF / "cert.pem", CONF / "kiem-phieu-cert.crt")
    print(f"Đã tạo chứng chỉ cho IP {ip} ({host}).")
    print(f"Các bàn khác mở: https://{ip}:8443/")
    print("Cài config/kiem-phieu-cert.crt lên từng máy quét (xem docs/ballot-scan/huong-dan-nhieu-ban.md).")


if __name__ == "__main__":
    main()
