# LeForge Windows 安装 / 升级脚本（PowerShell）
#
# 三种用法：
#   一键安装（干净机器，PowerShell 里直接粘贴；代码会落到 %USERPROFILE%\LeForge）：
#       powershell -ExecutionPolicy Bypass -NoProfile -Command "irm https://raw.githubusercontent.com/cz11001100/LeForge/main/install.ps1 | iex"
#   在仓库目录里安装 / 修复（解压包也行，不需要 git）：
#       powershell -ExecutionPolicy Bypass -File .\install.ps1
#   升级到 main 最新（等价于仓库里的 upgrade.ps1）：
#       powershell -ExecutionPolicy Bypass -File .\install.ps1 -Upgrade
#
# 参数：
#   -Cpu            强制装 CPU 版 torch（默认检测到 NVIDIA GPU 就装 cu128 版）
#   -Upgrade        先 git pull，再用 --upgrade 重装依赖；脚本、依赖、前端 dist 一起更新
#   -Remote         即使当前目录是完整仓库，也走"从 GitHub 拉代码再安装"的在线模式
#   -SkipSelfCheck  跳过装完后的模块自检
#   -RepoPath       在线模式使用的代码目录（默认 %USERPROFILE%\LeForge）
#
# torch 档位与 Linux 的 install.sh 一致：检测到 NVIDIA GPU 就装 cu128 版（RTX 50 系
# 必须 cu128，否则跑 kernel 报 no kernel image），否则装 PyPI 的 CPU 版。
#
# 与 Linux 的 install.sh 的差异（Windows 取舍，详见 README 的 Windows 一节）：
#   * 不装 placo：它依赖 cmeel 二进制轮子，PyPI 上没有 Windows 版本，源码编译
#     cmeel-boost 必然失败，而且会把整条安装拖垮。代价是 keyboard_ee（没有主臂时
#     用键盘做 IK 末端遥操）在 Windows 不可用；接主臂遥操不受影响。
#   * 不装 torchcodec：win_amd64 轮子要求 torch>=2.8，与本项目的 torch 2.7.x 不兼容；
#     视频统一走 PyAV 软解。
#
# 可重复执行：既是安装，也是修复 / 升级。

param(
    [switch]$Cpu,
    [switch]$Remote,
    [switch]$Upgrade,
    [switch]$SkipSelfCheck,
    [string]$RepoPath
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$GitRepo = "https://github.com/cz11001100/LeForge.git"
$UvBin   = Join-Path $env:USERPROFILE ".local\bin"

function Say($m)  { Write-Host "[INFO] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "[WARN] $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "[ERROR] $m" -ForegroundColor Red; exit 1 }

# 跑一段 Python 并回收输出。走 Start-Process 而不是 `& py ... 2>&1`：PS 5.1 会把原生
# 命令的 stderr 包成 ErrorRecord，在 $ErrorActionPreference = "Stop" 下直接终止脚本 ——
# torch 那句 "Redirects are currently not supported in Windows or MacOs" 就足以打断安装。
function Run-Python($PythonExe, $ScriptPath) {
    $outFile = [System.IO.Path]::GetTempFileName()
    $errFile = [System.IO.Path]::GetTempFileName()
    $proc = Start-Process -FilePath $PythonExe -ArgumentList @($ScriptPath) -NoNewWindow -Wait -PassThru `
        -RedirectStandardOutput $outFile -RedirectStandardError $errFile
    $text = @(Get-Content -Path $errFile -ErrorAction SilentlyContinue) +
            @(Get-Content -Path $outFile -ErrorAction SilentlyContinue)
    Remove-Item $outFile, $errFile -ErrorAction SilentlyContinue
    return [pscustomobject]@{ Code = $proc.ExitCode; Text = $text }
}

# 在线模式要用 git 拉代码；干净机器上没装时用 winget 静默装一份。
function Ensure-Git {
    $gitCmd = Join-Path $env:ProgramFiles "Git\cmd"
    if (Get-Command git -ErrorAction SilentlyContinue) { return }
    if (Test-Path (Join-Path $gitCmd "git.exe")) { $env:Path = "$gitCmd;$env:Path"; return }
    Say "未找到 git，用 winget 安装（约 60MB，安装期间请稍候）..."
    $out = [System.IO.Path]::GetTempFileName()
    $err = [System.IO.Path]::GetTempFileName()
    try {
        Start-Process -FilePath "winget" -NoNewWindow -Wait -RedirectStandardOutput $out -RedirectStandardError $err `
            -ArgumentList @("install", "--id", "Git.Git", "-e", "--source", "winget",
                            "--accept-package-agreements", "--accept-source-agreements", "--silent") | Out-Null
    } catch {
        Warn "  调 winget 失败：$_"
    }
    Remove-Item $out, $err -ErrorAction SilentlyContinue
    if (Test-Path (Join-Path $gitCmd "git.exe")) { $env:Path = "$gitCmd;$env:Path"; return }
    Fail "无法自动安装 git。请手动执行： winget install --id Git.Git -e ，装完重开 PowerShell 再跑本命令。"
}

# ---------- 判断安装模式 ----------
$Root = $PSScriptRoot
if (-not $Root -and $MyInvocation.MyCommand.Path) {
    $Root = Split-Path -Parent $MyInvocation.MyCommand.Path
}

$LocalRepo = $false
if ($Root -and -not $Remote) {
    if ((Test-Path (Join-Path $Root "leforge\pyproject.toml")) -and
        (Test-Path (Join-Path $Root "lerobot\pyproject.toml"))) {
        $LocalRepo = $true
    }
}

# ---------- uv ----------
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    $candidate = Join-Path $UvBin "uv.exe"
    if (Test-Path $candidate) {
        $env:Path = "$UvBin;$env:Path"
    } else {
        Say "安装 uv ..."
        try {
            irm https://astral.sh/uv/install.ps1 | iex
        } catch {
            Fail "uv 自动安装失败：$_ 。手动装： winget install --id astral-sh.uv -e，然后重开 PowerShell 再跑本脚本。"
        }
        $env:Path = "$UvBin;$env:Path"
    }
}
$Uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $Uv) { Fail "uv 装好了但当前窗口还找不到它 —— 请新开一个 PowerShell 窗口，重新运行本脚本。" }
Say "uv 就绪：$(& $Uv.Source --version)"
$env:UV_HTTP_TIMEOUT = "600"  # 大包（torch/torchvision）在网络差时默认超时偏短

if ($LocalRepo) {
    # ================= 本地仓库模式 =================
    Say "检测到完整仓库：$Root"
    Say "  从本地代码安装（不需要 git，也不会走网络拉源码）"

    # -Upgrade：先把代码 / 脚本 / 前端 dist 拉到 main 最新。解压包没有 .git 就跳过这一步，
    # 仅按现有代码重装依赖。
    if ($Upgrade -and (Test-Path (Join-Path $Root ".git"))) {
        Say "更新代码到 main 最新..."
        & git -C $Root pull --ff-only
        if ($LASTEXITCODE -ne 0) {
            Warn "git pull 失败（本地有改动或网络不通），继续用当前代码安装"
        }
    }

    $Venv   = Join-Path $Root "lerobot-env"
    $VenvPy = Join-Path $Venv "Scripts\python.exe"

    if (Test-Path $VenvPy) {
        Say "复用已有环境：$Venv"
    } else {
        Say "创建虚拟环境 lerobot-env（Python 3.12，与 Linux 侧一致）..."
        Warn "  首次会由 uv 下载独立 Python 解释器，日志停在 Downloading cpython-3.12 属正常"
        $VenvArgs = @("venv", $Venv, "--python", "3.12")
        if (Test-Path (Join-Path $Venv "pyvenv.cfg")) {
            # 上次中断留下半个环境：有 pyvenv.cfg 却没有 python.exe
            Warn "  $Venv 是残缺环境（有 pyvenv.cfg 没 python.exe），用 --clear 重建"
            $VenvArgs += "--clear"
        } elseif (Test-Path $Venv) {
            # uv 拉 Python 失败时只留下 .gitignore / CACHEDIR.TAG / README.md 三个骨架文件。
            # 除此之外的内容可能是用户自己的东西，宁可报错让人确认。
            $stub = @(".gitignore", "CACHEDIR.TAG", "README.md")
            $extra = @(Get-ChildItem -Force $Venv | Where-Object { $stub -notcontains $_.Name })
            if ($extra.Count -gt 0) {
                Fail "$Venv 已存在但不是虚拟环境，里面有：$($extra.Name -join ', ')。确认后可手动删除再重跑。"
            }
            Warn "  $Venv 里只有 uv 骨架（$($stub -join ', ')），删掉重建"
            Remove-Item -Recurse -Force $Venv
        }
        & $Uv.Source @VenvArgs
        if ($LASTEXITCODE -ne 0) {
            Fail "虚拟环境创建失败（退出码 $LASTEXITCODE）。网络慢可先设置 `$env:UV_PYTHON_INSTALL_MIRROR='https://registry.npmmirror.com/-/binary/python-build-standalone' 再重跑。"
        }
    }

    $Pip = @("pip", "install", "--python", $VenvPy)
    if ($Upgrade) { $Pip += "--upgrade" }  # 升级时把依赖也拉到版本区间内的最新

    # ---------- torch ----------
    # 与 install.sh 同一套判断：有 NVIDIA 显卡就走 cu128（RTX 50 系只认 cu128），
    # 否则用 PyPI 的 CPU 版。uv 缓存过的话第二次跑几乎不花时间。
    $HasNvidia = $false
    if (-not $Cpu) {
        try {
            $null = & nvidia-smi -L 2> $null
            $HasNvidia = ($LASTEXITCODE -eq 0)
        } catch {
            $HasNvidia = $false
        }
    }

    if ($HasNvidia) {
        $gpuName = ""
        try { $gpuName = (& nvidia-smi --query-gpu=name --format=csv,noheader 2> $null | Select-Object -First 1) } catch { $gpuName = "" }
        Say "检测到 NVIDIA GPU（$gpuName）：装 cu128 版 torch / torchvision（约 3GB）..."
        Say "  只要 CPU（例如显存太小）就加 -Cpu 重跑"
        & $Uv.Source @Pip --default-index https://download.pytorch.org/whl/cu128 "torch==2.7.1+cu128" "torchvision==0.22.1+cu128"
    } else {
        Say "安装 CPU 版 torch / torchvision（没检测到 NVIDIA GPU 或指定了 -Cpu）..."
        & $Uv.Source @Pip "torch>=2.7,<2.8.0" "torchvision>=0.22.0,<0.23.0"
    }
    if ($LASTEXITCODE -ne 0) { Fail "torch 安装失败（退出码 $LASTEXITCODE）。检查网络或代理后重跑本脚本。" }

    # ---------- lerobot ----------
    # 少一个 placo-dep：Windows 上没有可用的 placo 轮子（见文件头说明）。
    Say "安装本仓库的 lerobot（feetech 电机 / SmolVLA / 训练）..."
    Say "  这步要下不少大包，约 5-15 分钟，请耐心等"
    & $Uv.Source @Pip -e "$Root\lerobot[core_scripts,feetech,smolvla,training]"
    if ($LASTEXITCODE -ne 0) {
        Fail "lerobot 安装失败（退出码 $LASTEXITCODE）。若是编译类报错，多半是缺 Visual C++ 运行库；网络问题就重跑。"
    }

    # lerobot 自己钉的是 numpy>=2,<2.3（pyarrow 21+ 要求 numpy 2.x）。Linux 版 install.sh
    # 里那句 numpy<2.0 是给老训练依赖留的，Windows 上照抄会让数据集导入直接炸。
    Say "对齐 numpy（>=2.0,<2.3）..."
    & $Uv.Source @Pip "numpy>=2.0,<2.3"
    if ($LASTEXITCODE -ne 0) { Fail "numpy 安装失败（退出码 $LASTEXITCODE）。" }

    # ---------- leforge ----------
    # --no-deps 与 install.sh 同法：leforge 的 pyproject 把 lerobot 声明成 git 依赖，
    # 走依赖解析会绕过上面装好的本地 lerobot，把 GitHub 上的另一份装进来。
    Say "安装 LeForge 运行依赖..."
    & $Uv.Source @Pip "fastapi[standard]>=0.115.12" "websockets>=15.0.1" "uvicorn>=0.24.0" `
        "psutil>=5.9.0" "paramiko>=3.4.0" "mujoco>=3.3.0,<4" "gymnasium>=0.29" `
        "imageio>=2.31" "h5py>=3.10" "zarr>=2.18,<3" "pygrabber>=0.2"
    if ($LASTEXITCODE -ne 0) { Fail "LeForge 依赖安装失败（退出码 $LASTEXITCODE）。" }

    Say "安装 LeForge 本体（可编辑模式，改代码即时生效）..."
    & $Uv.Source @Pip --no-deps -e "$Root\leforge"
    if ($LASTEXITCODE -ne 0) { Fail "LeForge 安装失败（退出码 $LASTEXITCODE）。" }

    # ---------- 视频解码后端 ----------
    # Windows 上 torchcodec 配不上：lerobot 钉 torch>=2.7,<2.8，而 win_amd64 轮子从
    # 0.7.0 起就要求 torch>=2.8，装上后 import 直接 WinError 127（缺 caffe2 符号），
    # 连不经过自动探测的地方也会炸。这里确保它不存在，让 PyAV 成为唯一解码路径。
    $tcProbe = Join-Path $env:TEMP "leforge-torchcodec-probe.py"
    Set-Content -Path $tcProbe -Value "import importlib.util as u, sys`nsys.exit(0 if u.find_spec('torchcodec') else 1)" -Encoding ASCII
    $tcRun = Run-Python $VenvPy $tcProbe
    Remove-Item $tcProbe -ErrorAction SilentlyContinue
    if ($tcRun.Code -eq 0) {
        Warn "检测到 torchcodec（与本项目的 torch 2.7 不匹配），卸载，视频改走 PyAV..."
        & $Uv.Source pip uninstall --python $VenvPy torchcodec
    }
    Say "视频解码：PyAV 软解（Windows 不装 torchcodec）"

    # RealSense 深度相机可选，与 install.sh 第 4 步对齐：失败只警告。
    Say "安装 pyrealsense2（可选，仅 Intel RealSense 深度相机需要）..."
    & $Uv.Source @Pip "pyrealsense2>=2.55.1.6486,<2.57.0"
    if ($LASTEXITCODE -ne 0) { Warn "  跳过 pyrealsense2 —— 普通 USB 摄像头不受影响" }

    # lerobot / leforge 的 torch 都写成版本区间，解析器可能把 cu128 版换回 PyPI 的
    # CPU 或 cu126 版（cu126 在 RTX 50 系上跑 kernel 直接报 no kernel image）。
    # install.sh 里也有同样的兜底。
    if ($HasNvidia) {
        $verProbe = Join-Path $env:TEMP "leforge-torch-probe.py"
        Set-Content -Path $verProbe -Value "import torch; print(torch.__version__)" -Encoding ASCII
        $verRun = Run-Python $VenvPy $verProbe
        Remove-Item $verProbe -ErrorAction SilentlyContinue
        $torchVer = ($verRun.Text | Select-Object -Last 1)
        if ($torchVer -and ($torchVer -notlike "*+cu128*")) {
            Warn "torch 被解析成 $torchVer，不是 cu128 版 —— 重新装回 cu128..."
            & $Uv.Source @Pip --reinstall-package torch --reinstall-package torchvision `
                --default-index https://download.pytorch.org/whl/cu128 "torch==2.7.1+cu128" "torchvision==0.22.1+cu128"
            if ($LASTEXITCODE -ne 0) { Warn "cu128 版 torch 重装失败，训练会退回 CPU" }
        }
    }

    # ---------- 自检 ----------
    if (-not $SkipSelfCheck) {
        Say "自检关键模块..."
        $AllOk = $true
        function Check($label, $expr) {
            $pyFile = Join-Path $env:TEMP ("leforge-check-{0}.py" -f [guid]::NewGuid().ToString("N"))
            Set-Content -Path $pyFile -Value $expr -Encoding ASCII
            $run = Run-Python $VenvPy $pyFile
            Remove-Item $pyFile -ErrorAction SilentlyContinue
            if ($run.Code -eq 0) {
                Write-Host "  [OK] $label"
            } else {
                Warn "  [X] $label"
                $run.Text | Select-Object -Last 4 | ForEach-Object { Write-Host "        $_" }
                $script:AllOk = $false
            }
        }
        Check "paramiko（SSH 远程训练 / 装环境）" "import paramiko"
        Check "lerobot 采集与数据集模块"          "from lerobot.scripts.lerobot_record import DatasetRecordConfig; from lerobot.datasets.lerobot_dataset import LeRobotDataset"
        Check "SO-101 机械臂配置"                 "from lerobot.robots.so_follower import SO101FollowerConfig"
        Check "rewards（RA-BC 打分）"              "from lerobot.rewards.robometer import compute_rabc_weights"
        Check "LeForge 后端（启动入口）"           "import leforge.server"
        Check "MuJoCo 仿真评测"                    "import mujoco, gymnasium"
        Check "Windows 摄像头枚举（pygrabber）"    "import pygrabber.dshow_graph"

        # 内置仿真场景：sim/ 必须跟代码在一起，否则仿真评测只剩 Hub 下载一条路。
        $SceneProbe = Join-Path $env:TEMP "leforge-scene-probe.py"
        @'
from leforge.sim_eval import builtin_scene_dir
scene = builtin_scene_dir()
assert scene is not None, "sim/so101-tabletop-mujoco not found next to the repo"
print(scene)
'@ | Set-Content -Path $SceneProbe -Encoding ASCII
        $sceneRun = Run-Python $VenvPy $SceneProbe
        Remove-Item $SceneProbe -ErrorAction SilentlyContinue
        if ($sceneRun.Code -eq 0) {
            Write-Host "  [OK] 内置仿真场景（$($sceneRun.Text | Select-Object -Last 1)）"
        } else {
            Warn "  [X] 内置仿真场景（sim/so101-tabletop-mujoco 缺失）"
            $sceneRun.Text | Select-Object -Last 4 | ForEach-Object { Write-Host "        $_" }
            $AllOk = $false
        }

        # 摄像头枚举：DirectShow 名字是前端把设备对到浏览器 deviceId 的前提。
        $CamProbe = Join-Path $env:TEMP "leforge-cam-probe.py"
        @'
from leforge.server import get_available_cameras
cams = get_available_cameras()["cameras"]
print(", ".join(f"{c.get('name')}(#{c.get('index')})" for c in cams) or "no camera detected")
'@ | Set-Content -Path $CamProbe -Encoding ASCII
        $camRun = Run-Python $VenvPy $CamProbe
        Remove-Item $CamProbe -ErrorAction SilentlyContinue
        if ($camRun.Code -eq 0) {
            Write-Host "  [OK] 摄像头枚举（$($camRun.Text | Select-Object -Last 1)）"
        } else {
            Warn "  [X] 摄像头枚举失败（界面里拿不到摄像头的真实名字）"
            $camRun.Text | Select-Object -Last 4 | ForEach-Object { Write-Host "        $_" }
            $AllOk = $false
        }

        # MuJoCo 离屏渲染：Linux 用 EGL，Windows 用 WGL（没有 EGL）。
        $MjProbe = Join-Path $env:TEMP "leforge-mj-probe.py"
        @'
import mujoco
m = mujoco.MjModel.from_xml_string('<mujoco><worldbody><geom type="plane" size="1 1 .1"/></worldbody></mujoco>')
d = mujoco.MjData(m)
r = mujoco.Renderer(m, 64, 64)
r.update_scene(d)
r.render()
print("wgl ok")
'@ | Set-Content -Path $MjProbe -Encoding ASCII
        $env:MUJOCO_GL = "wgl"
        $mjRun = Run-Python $VenvPy $MjProbe
        Remove-Item $MjProbe -ErrorAction SilentlyContinue
        Remove-Item Env:\MUJOCO_GL -ErrorAction SilentlyContinue
        if ($mjRun.Code -eq 0) {
            Write-Host "  [OK] MuJoCo 离屏渲染（WGL）"
        } else {
            Warn "  [X] MuJoCo 离屏渲染（WGL）—— 仿真评测会失败，其余功能不受影响"
            $mjRun.Text | Select-Object -Last 4 | ForEach-Object { Write-Host "        $_" }
            Warn "      多为显卡驱动过旧或远程桌面会话限制；更新显卡驱动，或改 MUJOCO_GL=glfw 用窗口渲染再试"
            $AllOk = $false
        }

        # 视频解码：Windows 走 PyAV（不装 torchcodec）。现编一段 mp4 再按时间戳解回来，
        # 确认数据回放 / 数据集可视化真能用，而不只是 import 得动。
        $VidProbe = Join-Path $env:TEMP "leforge-video-probe.py"
        @'
import os
import tempfile

import av
import numpy as np

from lerobot.datasets.video_utils import decode_video_frames
from lerobot.utils.import_utils import get_safe_default_video_backend

backend = get_safe_default_video_backend()
path = os.path.join(tempfile.gettempdir(), "leforge_selftest.mp4")
container = av.open(path, "w")
stream = container.add_stream("mpeg4", rate=30)
stream.width, stream.height, stream.pix_fmt = 128, 96, "yuv420p"
rng = np.random.default_rng(0)
for _ in range(30):
    img = rng.integers(0, 255, (96, 128, 3), dtype=np.uint8)
    frame = av.VideoFrame.from_ndarray(img, format="rgb24").reformat(format="yuv420p")
    for packet in stream.encode(frame):
        container.mux(packet)
for packet in stream.encode():
    container.mux(packet)
container.close()

frames = decode_video_frames(path, [0.0, 0.5], tolerance_s=0.2, backend=backend)
assert tuple(frames.shape) == (2, 3, 96, 128), f"decoded shape {tuple(frames.shape)}, expected (2, 3, 96, 128)"
print(f"{backend} {tuple(frames.shape)}")
'@ | Set-Content -Path $VidProbe -Encoding ASCII
        $vidRun = Run-Python $VenvPy $VidProbe
        Remove-Item $VidProbe -ErrorAction SilentlyContinue
        if ($vidRun.Code -eq 0) {
            Write-Host "  [OK] 视频解码（$($vidRun.Text | Select-Object -Last 1)）"
        } else {
            Warn "  [X] 视频解码（数据回放 / 数据集可视化会失败）"
            $vidRun.Text | Select-Object -Last 6 | ForEach-Object { Write-Host "        $_" }
            $AllOk = $false
        }

        if ($HasNvidia) {
            # import torch 成功 ≠ CUDA 能跑：装错 CUDA 档位时 import 正常但 kernel 崩。
            # 这里真的跑一次 GPU 运算，确认训练能落到显卡上。
            $CudaProbe = Join-Path $env:TEMP "leforge-cuda-probe.py"
            @'
import torch
assert torch.cuda.is_available(), "torch.cuda.is_available() is False"
t = torch.zeros(64, 64, device="cuda")
print(float((t + 1).sum()))
'@ | Set-Content -Path $CudaProbe -Encoding ASCII
            $cudaRun = Run-Python $VenvPy $CudaProbe
            Remove-Item $CudaProbe -ErrorAction SilentlyContinue
            if ($cudaRun.Code -eq 0) {
                Write-Host "  [OK] CUDA 计算（GPU 训练可用）"
            } else {
                Warn "  [X] CUDA 计算（GPU 训练可用）—— 训练会退回 CPU"
                $cudaRun.Text | Select-Object -Last 4 | ForEach-Object { Write-Host "        $_" }
                Warn "      RTX 50 系必须 cu128 版：uv pip install --python `"$VenvPy`" --default-index https://download.pytorch.org/whl/cu128 torch==2.7.1+cu128"
                $AllOk = $false
            }
        }

        if (-not (Test-Path (Join-Path $Root "leforge\frontend\dist\index.html"))) {
            Warn "  未找到 leforge\frontend\dist\index.html —— 浏览器打开会是空白页"
            $AllOk = $false
        }
        if ($AllOk) { Say "自检通过" } else { Warn "自检有失败项，见上面 [X] 行" }
    }

    # ---------- 启动器 ----------
    # 仓库自带 leforge-run.ps1；只有缺失时才生成，避免把受版本控制的文件改脏。
    $Runner = Join-Path $Root "leforge-run.ps1"
    if (-not (Test-Path $Runner)) {
        @'
# 启动 LeForge（代码与环境均来自本仓库）
$Root = $PSScriptRoot
$Venv = Join-Path $Root "lerobot-env"
$Py = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $Py)) { Write-Host "[ERROR] 未找到环境，先运行 .\install.ps1" -ForegroundColor Red; exit 1 }
Set-Location $Root
& $Py -m leforge.scripts.leforge @args
exit $LASTEXITCODE
'@ | Set-Content -Path $Runner -Encoding UTF8
    }

    # 把启动器挂到 PATH 里的 leforge.cmd（对应 Linux 侧的 ~/.local/bin/leforge）
    # 必须显式经 powershell 调用：.ps1 在 cmd 里的默认关联是记事本，直接执行只会打开文件。
    New-Item -ItemType Directory -Force -Path $UvBin | Out-Null
    $Shim = Join-Path $UvBin "leforge.cmd"
    $ShimBody = "@echo off`r`npowershell -NoProfile -ExecutionPolicy Bypass -File `"$Runner`" %*`r`n"
    [System.IO.File]::WriteAllText($Shim, $ShimBody)

    Write-Host ""
    Write-Host "=========================================="
    Say "安装完成"
    Write-Host "=========================================="
    Write-Host ""
    Write-Host "启动（任选一种）："
    Write-Host "    .\leforge-run.ps1"
    Write-Host "    leforge            # 新开一个 PowerShell 窗口，PATH 才会带上 $UvBin"
    Write-Host "  浏览器打开 http://localhost:8000"
    Write-Host ""
    Write-Host "环境位置：$Venv"
    Write-Host "修复：重跑 .\install.ps1    升级：.\install.ps1 -Upgrade 或 upgrade.ps1"
    Write-Host ""
} else {
    # ================= 在线模式（一键安装） =================
    # 没有本地仓库（例如 `irm ... | iex`）：先在 %USERPROFILE%\LeForge 落地一份代码，
    # 再交给这份代码里的 install.ps1 按本地模式安装。脚本、源码、前端 dist 都在同一个
    # git 工作树里，所以升级时一次 git pull 就能全部更新。
    if (-not $RepoPath) { $RepoPath = Join-Path $env:USERPROFILE "LeForge" }
    Ensure-Git

    if (Test-Path (Join-Path $RepoPath ".git")) {
        Say "复用已有代码：$RepoPath"
        & git -C $RepoPath pull --ff-only
        if ($LASTEXITCODE -ne 0) { Warn "git pull 失败（本地有改动或网络不通），继续用现有代码安装" }
    } else {
        if (Test-Path $RepoPath) {
            $existing = @(Get-ChildItem -Force $RepoPath | Select-Object -ExpandProperty Name)
            if ($existing.Count -gt 0) {
                Fail "$RepoPath 已存在但不是 git 仓库（$($existing -join ', ')）。换个目录：加 -RepoPath <路径>，或先把该目录清空。"
            }
            Remove-Item $RepoPath -Force
        }
        Say "下载 LeForge 源码到 $RepoPath ..."
        & git clone --depth 1 $GitRepo $RepoPath
        if ($LASTEXITCODE -ne 0) { Fail "git clone 失败（退出码 $LASTEXITCODE）。检查网络 / 代理后重跑本命令。" }
    }

    $Forward = @()
    if ($Cpu)           { $Forward += "-Cpu" }
    if ($Upgrade)       { $Forward += "-Upgrade" }
    if ($SkipSelfCheck) { $Forward += "-SkipSelfCheck" }

    Say "代码就绪，按本地模式继续安装 ..."
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $RepoPath "install.ps1") @Forward
    exit $LASTEXITCODE
}

Write-Host "Windows 注意："
Write-Host "  机械臂：装 CH340/CP2102 驱动；端口号在设备管理器里看（常见 COM3），界面里手动选"
Write-Host "  摄像头：LeForge 走 DirectShow；被 Zoom / Teams 占用时拿不到画面"
Write-Host "  键盘 IK 遥操（keyboard_ee）：Windows 装不了 placo，该功能不可用；接 leader 主臂即可"
Write-Host "  本地训练：有 NVIDIA 显卡时装的是 cu128 版 torch，直接走 GPU；显存不够用 -Cpu 重装"
Write-Host "  视频解码：Windows 不装 torchcodec（没有匹配 torch 2.7 的二进制），统一走 PyAV 软解"
