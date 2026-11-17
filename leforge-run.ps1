# 启动 LeForge（代码与环境均来自本仓库）
#
#   .\leforge-run.ps1                  # 默认 http://localhost:8000
#   .\leforge-run.ps1 --dev            # Vite HMR :8080 + uvicorn --reload :8000
#   .\leforge-run.ps1 --stop           # 停掉占用 8000/8080 的旧实例
#
# 首次使用先跑 .\install.ps1。Linux 侧对应的是 leforge-run.sh。
# Windows 不需要 Linux 那套 LD_LIBRARY_PATH / FFmpeg shim：Windows 上不装
# torchcodec，视频解码统一走 PyAV（详见 install.ps1）。

$Root = $PSScriptRoot
$Venv = Join-Path $Root "lerobot-env"
$Py   = Join-Path $Venv "Scripts\python.exe"

if (-not (Test-Path $Py)) {
    Write-Host "[ERROR] 未找到虚拟环境：$Venv" -ForegroundColor Red
    Write-Host "        先运行 .\install.ps1" -ForegroundColor Red
    exit 1
}

# 传参给 Python 前先确保工作目录在仓库根，数据集 / 输出目录的相对路径才有可预期含义
Set-Location $Root
& $Py -m leforge.scripts.leforge @args
exit $LASTEXITCODE
