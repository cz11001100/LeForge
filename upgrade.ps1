# LeForge Windows 升级脚本
#
# 一键升级（PowerShell 里直接粘贴）：
#   powershell -ExecutionPolicy Bypass -NoProfile -Command "irm https://raw.githubusercontent.com/cz11001100/LeForge/main/upgrade.ps1 | iex"
#
# 做的事：把 %USERPROFILE%\LeForge 里的代码 / 脚本 / 前端 dist 拉到 main 最新，
# 然后重跑 install.ps1 -Upgrade，更新 Python 依赖（复用已有环境，不重建）。
# 已经是最新时只做一次依赖校验。
#
# 参数（直接以文件方式运行时可用）：
#   -Cpu       同时把 torch 固定在 CPU 版（本机没有 N 卡时本来就是 CPU 版）
#   -RepoPath  代码目录，默认 %USERPROFILE%\LeForge

param(
    [switch]$Cpu,
    [string]$RepoPath
)

$ErrorActionPreference = "Stop"

function Say($m)  { Write-Host "[INFO] $m" -ForegroundColor Green }
function Fail($m) { Write-Host "[ERROR] $m" -ForegroundColor Red; exit 1 }

function Invoke-GitPull([string]$Dir) {
    # PS 5.1 在 $ErrorActionPreference="Stop" 下会把 git 写到 stderr 的内容当成终止错误，
    # 所以走 Start-Process 重定向，再按普通文本打印。
    $quoted = @("-c", "http.version=HTTP/1.1", "-c", "http.lowSpeedLimit=0", "-C", $Dir, "pull", "--ff-only") |
        ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }
    $out = [System.IO.Path]::GetTempFileName()
    $err = [System.IO.Path]::GetTempFileName()
    $p = Start-Process -FilePath "git" -ArgumentList $quoted -NoNewWindow -Wait -PassThru `
        -RedirectStandardOutput $out -RedirectStandardError $err
    Get-Content $out -ErrorAction SilentlyContinue | Where-Object { $_ -match '\S' } | ForEach-Object { Write-Host "  $_" }
    Get-Content $err -ErrorAction SilentlyContinue | Where-Object { $_ -match '\S' } | ForEach-Object { Write-Host "  $_" }
    Remove-Item $out, $err -ErrorAction SilentlyContinue
    return $p.ExitCode
}

if (-not $RepoPath) { $RepoPath = Join-Path $env:USERPROFILE "LeForge" }
$Installer = Join-Path $RepoPath "install.ps1"

if (-not (Test-Path $Installer)) {
    Fail "没有找到已安装的 LeForge（$RepoPath）。先运行一键安装命令；代码在别的目录就加 -RepoPath 指定。"
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Fail "找不到 git —— 升级需要它。装： winget install --id Git.Git -e ，然后重开 PowerShell。"
}

Say "更新代码：$RepoPath"
$code = Invoke-GitPull $RepoPath
if ($code -ne 0) {
    Fail "git pull 失败（退出码 $code）。本地若有未提交改动，先提交或撤销；网络问题请重试。"
}

Say "重装依赖与前端产物 ..."
$ChildArgs = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $Installer, "-Upgrade")
if ($Cpu) { $ChildArgs += "-Cpu" }
& powershell @ChildArgs
exit $LASTEXITCODE
