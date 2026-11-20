# Bật máy chủ kiểm phiếu trên Windows: đọc STT + kiểm chéo họ tên (CRNN + VietOCR) + trang kiểm phiếu + kho phiếu chung. Dừng bằng Ctrl+C.
#   Máy này:       http://localhost:8766/
#   Các bàn khác:  https://<IP máy này>:8443/   (cần chứng chỉ: tools\make_cert.py tự chạy lần đầu)
#   powershell -ExecutionPolicy Bypass -File tools\start_prototype.ps1
Set-Location (Join-Path $PSScriptRoot "..")
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$py = ".venv\Scripts\python.exe"
$pyTf = ".venv-tf\Scripts\python.exe"
if (-not (Test-Path $py)) { Write-Host "Chưa có .venv. Xem README, mục Cài đặt trên Windows."; exit 1 }

function Busy($port) { [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) }

if (-not (Test-Path config\cert.pem)) { & $py tools\make_cert.py }
if (Busy 8766) {
  Write-Host "Máy chủ đã chạy sẵn ở cổng 8766. Muốn nạp bản mới thì tắt nó (Ctrl+C ở cửa sổ đang chạy) rồi chạy lại."
  Start-Process "http://localhost:8766/"; exit 0
}
New-Item -ItemType Directory -Force out | Out-Null
$procs = @()
# Dịch vụ CRNN đọc họ tên (kiểm chéo tên với STT). Thiếu .venv-tf thì bỏ qua: vẫn đọc STT, chỉ không tô vàng "tên không khớp STT".
if ((Test-Path $pyTf) -and -not (Busy 8768)) {
  $procs += Start-Process $pyTf -ArgumentList "tools\crnn_server.py" -RedirectStandardOutput out\crnn.log -RedirectStandardError out\crnn.err.log -PassThru -WindowStyle Hidden
}
try {
  $procs += Start-Process $py -ArgumentList "tools\ocr_server.py" -PassThru -NoNewWindow
  for ($i = 0; $i -lt 60; $i++) {
    try { Invoke-WebRequest -UseBasicParsing http://localhost:8766/health -TimeoutSec 1 | Out-Null; break } catch { Start-Sleep -Milliseconds 500 }
  }
  $ip = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -notmatch "Loopback|vEthernet|VirtualBox|VMware" -and $_.IPAddress -notlike "169.254.*" } | Select-Object -First 1).IPAddress
  Write-Host "Các bàn khác mở: https://$($ip):8443/"
  Start-Process "http://localhost:8766/"
  Wait-Process -Id $procs[-1].Id
} finally {
  foreach ($p in $procs) { if ($p -and -not $p.HasExited) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } }
}
