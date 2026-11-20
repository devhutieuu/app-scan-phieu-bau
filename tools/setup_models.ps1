# Tải model đọc họ tên về máy Windows (làm 1 lần, cần Internet). Bản Windows không có Qwen (chỉ chạy trên chip Apple).
#   powershell -ExecutionPolicy Bypass -File tools\setup_models.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
New-Item -ItemType Directory -Force tools\models | Out-Null
function Get-Model($path, $url) {
  if ((Test-Path $path) -and (Get-Item $path).Length -gt 0) { Write-Host "Đã có: $path"; return }
  Write-Host "Tải: $path"
  curl.exe -L --fail --progress-bar -o $path $url
  if ($LASTEXITCODE -ne 0) { throw "Tải lỗi: $url" }
}
Get-Model "tools\models\vgg_transformer.pth" "https://vocr.vn/data/vietocr/vgg_transformer.pth"
Get-Model "tools\models\crnn_vi_cinnamon.hdf5" "https://github.com/TomHuynhSG/vietnamese-handwriting-recognition-ocr/raw/main/model_checkpoint_weights.hdf5"
Write-Host "Xong."
