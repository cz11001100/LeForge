# LeForge Windows 升级脚本
#
# 一键升级（cmd / PowerShell 里直接粘贴）：
#   powershell -ExecutionPolicy Bypass -NoProfile -Command "irm https://raw.githubusercontent.com/cz11001100/LeForge/main/upgrade.ps1 -OutFile $env:TEMP\leforge-upgrade.ps1; & $env:TEMP\leforge-upgrade.ps1"
#
# 做的事：把已安装的 LeForge 代码 / 脚本 / 前端 dist 拉到 main 最新，
# 然后重跑 install.ps1 -Upgrade，更新 Python 依赖（复用已有环境，不重建）。
# 已经是最新时只做一次依赖校验。
# 已安装目录按顺序找：%USERPROFILE%\LeForge → leforge 启动器指向的目录 → 当前目录。
#
# 参数（以文件方式运行时可用）：
#   -Cpu       同时把 torch 固定在 CPU 版（轻量档安装的机器升级时带上）
#   -RepoPath  代码目录，不给就按上面的顺序自动找

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
    # pull 显式写 origin <分支>：没设 upstream 的仓库（重新 init / reset 过）也能拉。
    $branch = "main"
    $bo = [System.IO.Path]::GetTempFileName()
    $be = [System.IO.Path]::GetTempFileName()
    $bp = Start-Process -FilePath "git" -ArgumentList @("-C", $Dir, "rev-parse", "--abbrev-ref", "HEAD") `
        -NoNewWindow -Wait -PassThru -RedirectStandardOutput $bo -RedirectStandardError $be
    $b = Get-Content $bo -ErrorAction SilentlyContinue | Select-Object -First 1
    Remove-Item $bo, $be -ErrorAction SilentlyContinue
    if ($bp.ExitCode -eq 0 -and $b) { $branch = $b.Trim() }

    $quoted = @("-c", "http.version=HTTP/1.1", "-c", "http.lowSpeedLimit=0", "-C", $Dir, "pull", "--ff-only", "origin", $branch) |
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

# 找回已安装的目录：默认目录 → leforge.cmd 启动器指向的目录 → 当前目录。
# 启动器里记着代码的真实位置，装在别的盘也能找回来（与 install.sh 的行为一致）。
function Find-InstalledRepo {
    $cands = @()
    if ($env:USERPROFILE) { $cands += (Join-Path $env:USERPROFILE "LeForge") }
    $launcher = Join-Path $env:USERPROFILE ".local\bin\leforge.cmd"
    if (Test-Path $launcher) {
        $m = Select-String -Path $launcher -Pattern '-File\s+"([^"]+)"' -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($m) { $cands += (Split-Path -Parent $m.Matches[0].Groups[1].Value) }
    }
    $cands += $PWD.Path
    $cands += (Join-Path $PWD.Path "LeForge")
    foreach ($c in $cands) {
        if ((Test-Path (Join-Path $c "install.ps1")) -and (Test-Path (Join-Path $c "leforge\pyproject.toml"))) { return $c }
    }
    return $null
}

if (-not $RepoPath) { $RepoPath = Find-InstalledRepo }
if (-not $RepoPath) {
    Fail "没有找到已安装的 LeForge（找过 %USERPROFILE%\LeForge、leforge 启动器指向的目录、当前目录）。先运行一键安装命令；代码在别的目录就加 -RepoPath <路径>。"
}
$Installer = Join-Path $RepoPath "install.ps1"

if (-not (Test-Path $Installer)) {
    Fail "$RepoPath 里没有 install.ps1，不像 LeForge 安装目录。用 -RepoPath 指定正确位置。"
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
# 子进程会把 uv 的进度写到 stderr；父脚本是 Stop 模式时，只要输出被重定向
# （upgrade.ps1 > log）就会被当成终止错误。这里临时放宽，退出码单独取。
$PrevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& powershell @ChildArgs
$code = $LASTEXITCODE
$ErrorActionPreference = $PrevEap
exit $code
