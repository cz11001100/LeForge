# LeForge 常见问题排查

## 启动类

### `leforge: command not found`

**原因：conda 环境覆盖了 PATH。** venv 激活后再执行 `conda activate xxx`，conda 会重置 PATH，把 venv 的 `bin/` 挤掉。

```bash
conda deactivate          # 退出所有 conda 环境
source lerobot-env/bin/activate
leforge
```

或直接用最省事的方式（脚本内部已处理 conda）：

```bash
./leforge-run.sh
```

### `Address already in use` / 端口 8000 被占用

之前有 LeForge 进程没退干净。

```bash
./leforge-run.sh --stop     # 杀掉占用 8000/8080 的残留进程
./leforge-run.sh
```

手动查占用：

```bash
ss -ltnp | grep 8000
```

### `ModuleNotFoundError: No module named 'lerobot.configs.dataset'`

**原因：leforge 里 import 路径写错。** 旧版指向 `lerobot.configs.dataset`，但该类实际在 `lerobot.scripts.lerobot_record`。

已在当前版本修复。若你手上是旧包，手动改：

```bash
sed -i 's/from lerobot.configs.dataset import DatasetRecordConfig/from lerobot.scripts.lerobot_record import DatasetRecordConfig/' leforge/leforge/record.py
```

### `ImportError: cannot import name 'LeRobotDataset' from 'lerobot.datasets'`

同样是 import 路径问题，实际在 `lerobot.datasets.lerobot_dataset`：

```bash
sed -i 's/from lerobot\.datasets import LeRobotDataset/from lerobot.datasets.lerobot_dataset import LeRobotDataset/g' leforge/leforge/record.py
sed -i 's/from lerobot\.datasets import CODEBASE_VERSION/from lerobot.datasets.lerobot_dataset import CODEBASE_VERSION/' leforge/leforge/record.py
```

### `ModuleNotFoundError: No module named 'paramiko'`

**原因：缺少 SSH 依赖，训练板块的远程安装/训练无法使用。**

```bash
uv pip install --python lerobot-env/bin/python "paramiko>=3.4.0"
```

### `Could not import realsense: No module named 'pyrealsense2'`

**这不是错误，是 INFO 级日志。** 代码用 `try/except` 捕获后打印，缺了不影响功能。

只有 **Intel RealSense 深度相机**（D435/D455）才需要 pyrealsense2。普通 USB 摄像头走 OpenCV 后端，完全不需要。

如果用 RealSense 相机：

```bash
uv pip install --python lerobot-env/bin/python "pyrealsense2>=2.55.1.6486,<2.57.0"
```

---

## 硬件类

### 连机械臂报 `Permission denied: '/dev/ttyACM0'`

**原因：当前用户不在 `dialout` 组，没有串口读写权限。**

```bash
sudo usermod -aG dialout $USER
```

**必须注销重新登录**才生效（不是重启终端，是注销整个会话）。

验证：

```bash
id -nG | grep dialout
```

### 找不到串口 / 机械臂不响应

```bash
ls /dev/ttyUSB* /dev/ttyACM*     # 看有没有设备
dmesg | tail -20                 # 看插入时的内核日志
```

- 检查 USB 线是否是数据线（有些是纯充电线）
- 换一个主板直插的 USB 口，避开 hub
- Windows 需装 CH340/CP2102 驱动

### 摄像头打不开 / 列表为空

```bash
ls /dev/video*                   # 确认设备存在
cat /sys/class/video4linux/video0/name
```

- 检查摄像头是否被其他程序占用（浏览器、OBS、Zoom）
- 确认用户在 `video` 组：`sudo usermod -aG video $USER`
- 部分摄像头只支持 YUYV 格式，需在界面里选对应格式

---

## 训练类

### SSH 远程安装环境时中途断连

**典型现象：Test 连接通过，但装环境到第 2 步（安装 pip）就断。**

**原因：SSH 连接没设 keepalive 心跳。** `apt-get install` 跑几分钟期间没有数据往来，防火墙/NAT 会静默断开空闲连接。

已在当前版本修复（加了 `transport.set_keepalive(30)`）。若手上是旧包：

```bash
# 在 ssh_remote_env.py 的 client.connect(**kw) 后面插入三行
python3 - <<'PY'
import re, pathlib
p = pathlib.Path("leforge/leforge/ssh_remote_env.py")
s = p.read_text()
if "set_keepalive" not in s:
    s = s.replace(
        "            client.connect(**kw)\n            return client",
        "            client.connect(**kw)\n"
        "            transport = client.get_transport()\n"
        "            if transport is not None:\n"
        "                transport.set_keepalive(30)\n"
        "            return client",
    )
    p.write_text(s)
    print("已修复")
else:
    print("已有 keepalive，无需修改")
PY
```

另外远程服务器端也可放宽超时，编辑 `/etc/ssh/sshd_config`：

```
ClientAliveInterval 60
ClientAliveCountMax 10
```

然后 `sudo systemctl restart sshd`。

### SSH Test 连接不通过

逐项检查：

1. **终端里能否手动 SSH 上去？**
   ```bash
   ssh -p 端口 用户名@主机
   ```
   如果手动都不行，LeForge 也不行 —— 是网络/密钥/防火墙问题，不是 LeForge 的问题。

2. **用密码还是密钥？** LeForge 两种都支持，但密码登录要在服务器端确认 `PasswordAuthentication yes`。

3. **密钥路径**必须是服务器本机上的绝对路径（LeForge 跑在哪台机器，密钥就要在那台机器上）。

4. **主机名不要带 `~`**，`~/.ssh/id_rsa` 这种路径脚本会展开，但界面里填的时候注意别写错。

### `nvidia-smi` 有但训练报 CUDA 不可用

```bash
source lerobot-env/bin/activate
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.device_count())"
```

如果 `cuda_available` 是 False，说明装的是 CPU 版 torch。重装对应 CUDA 版本：

```bash
uv pip install --python lerobot-env/bin/python --force-reinstall torch torchvision --index-url https://download.pytorch.org/whl/cu121
```

（`cu121` 换成你实际的 CUDA 版本，用 `nvidia-smi` 右上角看）

### 训练卡在下载模型 / 网络很慢

模型权重与数据集从 HuggingFace 下载。`install.sh` 已经实测过官方站与 `hf-mirror.com` 的吞吐、谁快用谁，并把结果连同下面两个变量写进了启动配置，一般不用管。手动指定或临时切换：

```bash
LEFORGE_HF_ENDPOINT=https://hf-mirror.com bash install.sh   # 装的时候就钉死镜像
# 或临时一次：
export HF_ENDPOINT=https://hf-mirror.com HF_HUB_DISABLE_XET=1 HF_HUB_DOWNLOAD_TIMEOUT=60
./leforge-run.sh
```

**只设 `HF_ENDPOINT` 常常还是不生效**，两个原因：

- `huggingface_hub` 的新传输协议 Xet 不走这个端点，它直连 `cas-server.xethub.hf.co`，经镜像认证会 401 —— 必须 `HF_HUB_DISABLE_XET=1` 退回普通 HTTP
- 跨境链路常超过默认 10s 读超时，表现是反复"下载中→重试"，把 `HF_HUB_DOWNLOAD_TIMEOUT` 放宽到 60

数据集上传/下载同理走 `HF_ENDPOINT`；`HF_HOME`（默认 `~/.cache/huggingface`）决定缓存位置，lerobot 的数据集与模型都在下面。

---

## 环境类

### 轻薄本 / 没有独立显卡

用轻量档，别装 CUDA 版 torch：

```bash
curl -fsSL https://raw.githubusercontent.com/cz11001100/LeForge/main/install.sh | bash -s -- --lite
```

差别只在 torch：默认档从 PyPI 装 CUDA 版，连带 `nvidia-*` 那一整套 CUDA 运行库；轻量档从 PyTorch 的 CPU 索引装同版本区间的 CPU 版。遥操、采集、回放、评估、SSH 云端训练都不受影响，同一套依赖组合下环境从 6.5GB 降到 2.2GB（本机实测）。

已经装过默认档想减体积，得重建环境（换档不能只改参数，虚拟环境里已装好的 CUDA 库不会被自动删）：

```bash
rm -rf lerobot-env && bash install.sh --lite
```

反过来，日后插上/换成有 N 卡的机器要本地训练，同样重建：`rm -rf lerobot-env && bash install.sh`。

CPU 索引默认是 `https://download.pytorch.org/whl/cpu`，国内嫌慢可以换上交大镜像：

```bash
LEFORGE_TORCH_INDEX=https://mirror.sjtu.edu.cn/pytorch-wheels/cpu bash install.sh --lite
```

### 想彻底重装

```bash
rm -rf lerobot-env        # 删掉整个虚拟环境
bash install.sh           # 重新安装，选 y 确认
```

### 只想补装某个包

```bash
uv pip install --python lerobot-env/bin/python 包名
```

注意：用 `--python` 指定绝对路径，不依赖当前 shell 激活了哪个环境。

### 卡在 `Downloading cpython-3.12...`

不是卡死，多半是在跨境拉解释器。uv 会从 GitHub 下载约 32MB 的 CPython 并解压，国内网络下这一步可能耗十几分钟甚至重试。想确认它还在动：

```bash
du -sh ~/.local/share/uv/python       # 隔 20 秒看两次，数字在涨就正常
```

嫌慢的话，脚本已经会自动处理一部分：它先测一次 GitHub 的响应时间，超过 3 秒就把解释器下载切到加速前缀（`LEFORGE_GH_PROXY` 可换前缀）。不想依赖这个判断，就手动二选一：

```bash
# 1) 用系统自带的 3.12，uv 就不会下载
sudo apt install python3.12 python3.12-venv

# 2) 给解释器下载也走国内代理
export UV_PYTHON_INSTALL_MIRROR=https://gh-proxy.com/https://github.com/astral-sh/python-build-standalone/releases/download
```

### 开了 VPN，下载反而更慢

**现象**：挂上代理后 `install.sh` 卡在 `Downloading torch...`，比不开 VPN 还慢。

原因是脚本默认走清华镜像，而部分代理客户端（TUN 模式）会把国内域名也一起送出境，流量绕一圈回来。此时官方源直连反而更快 —— 但**谁快没有定论**，取决于代理节点和规则，同一台机器两次测的结果都能互换。

所以脚本不写死，装的时候会各测一次索引页响应时间，谁快用谁，并打印选中的源：

```
包索引: https://pypi.tuna.tsinghua.edu.cn/simple（VPN 下嫌国内源慢可设 LEFORGE_INDEX=off 重跑）
```

想手动指定，重跑前设一个环境变量即可：

```bash
LEFORGE_INDEX=off bash install.sh    # 强制官方源
LEFORGE_INDEX=https://mirrors.aliyun.com/pypi/simple bash install.sh   # 任意镜像
```

已经自己配好 `UV_INDEX_URL` / `UV_DEFAULT_INDEX` / `PIP_INDEX_URL` 的，脚本尊重你的设置，不再探测。

判断当前到底谁快，可以自己测（看 `time_total`，小的赢）：

```bash
for u in https://pypi.tuna.tsinghua.edu.cn/simple/paramiko/ https://pypi.org/simple/paramiko/; do
  echo "$(curl -m 8 -so /dev/null -w '%{time_total}' $u)  $u"
done
```

### uv 装不上 / 下载 Python 失败

脚本要 uv 自动下载独立 CPython，国内网络可能超时。先装系统 Python：

```bash
sudo apt install python3.12 python3.12-venv
```

再重跑 `bash install.sh`，uv 会优先用系统已有的 3.12。

---

##  still 不行？

把这几项信息发给开发者：

```bash
# 1. 自检结果
source lerobot-env/bin/activate
python -c "import leforge.server"

# 2. 环境与硬件
uname -sm; python --version; nvidia-smi --query-gpu=name,driver_version --format=csv,noheader
id -nG; ls /dev/ttyUSB* /dev/ttyACM* /dev/video* 2>&1

# 3. 完整报错（不要只截最后一行）
```

---

## Windows 专属

### `install.ps1` 跑不起来 / 提示禁止运行脚本

PowerShell 默认策略会拦 `.ps1`。用带 `-ExecutionPolicy Bypass` 的调用方式，不要改全局策略：

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

如果脚本里的中文显示成乱码，说明文件被编辑器存成了无 BOM 的 UTF-8；仓库里的 `.ps1` 自带 BOM，重新从仓库取一份即可。

### 提示装不了 `placo` / 编译 `cmeel-boost` 失败

Windows 上**故意不装 placo**：它依赖 cmeel 预编译轮子，PyPI 没有 Windows 版本，退回源码编译必然失败。因此 `keyboard_ee`（没有主臂时用键盘做 IK 末端遥操）在 Windows 不可用，接 leader 主臂的遥操、采集、训练都不受影响。

如果安装日志里仍在尝试编译 `cmeel-boost`，说明用的是旧版 `pyproject.toml`（依赖没按平台拆分），把仓库更新到最新再重装。

### 训练到最后报 `WinError 1314`（拒绝符号链接）

LeRobot 训练结束会建 `checkpoints/last` 软链，Windows 默认不允许普通用户建符号链接。当前版本已自动兜底：软链失败改写为**目录联接（junction）**，不需要任何权限，resume / 上传 / 界面列 checkpoint 的读法一致；junction 也建不了时只告警，训练照常结束、权重照常保存。

想彻底消掉这条告警，可开启"开发者模式"（设置 → 系统 → 开发者选项），或以管理员身份运行。

### 端口 8000 被占用 / 关掉窗口后端口还占着

```powershell
.\leforge-run.ps1 --stop
```

`--stop` 会按 cmdline、端口监听、遗留 reload worker 三种信号找出属于 LeForge 的进程并连同子进程结束掉，不会误杀其他开发服务。

### 找不到串口 / 机械臂不响应

- 装 CH340 / CP2102 驱动；设备管理器里确认端口号（常见 `COM3`），界面里手动选
- 别用纯充电线，换主板直插的 USB 口
- 串口被别的程序（串口助手、Arduino IDE）占用时，LeForge 打不开

### 摄像头列表为空 / 打不开

- LeForge 在 Windows 走 DirectShow；被 Zoom / Teams / OBS 占用时拿不到画面
- Windows 默认允许桌面应用访问摄像头：设置 → 隐私 → 相机，确认已开启
- 摄像头名字由 pygrabber 读取；若列表里只有编号没有名字，重跑 `install.ps1` 补装 pygrabber

### 仿真评测报 MuJoCo 渲染失败

Windows 没有 EGL，LeForge 默认改用 `MUJOCO_GL=wgl`。仍失败时：

- 更新显卡驱动（WGL 依赖 OpenGL 3.1+）
- 远程桌面会话可能拿不到 OpenGL 上下文，改本机登录再试
- 兜底：`$env:MUJOCO_GL='glfw'` 再启动（走窗口渲染，需要桌面会话；Windows 不支持 `egl` / `osmesa`）

### 视频解码报 `torchcodec` / `WinError 127`

Windows 上**故意不装 torchcodec**：本项目的 torch 钉在 2.7.x，而 torchcodec 的 win_amd64 轮子从 0.7.0 起就要求 torch≥2.8，装上后 `import` 会因缺 `caffe2` 符号而失败（`WinError 127`）。`install.ps1` 会检测并卸载残留的 torchcodec，视频统一走 PyAV 软解。

如果自己手动装过，卸载即可：

```powershell
uv pip uninstall --python .\lerobot-env\Scripts\python.exe torchcodec
```

### `leforge` 命令找不到

本地解压包模式的环境在 `lerobot-env\`，启动器会挂到 `%USERPROFILE%\.local\bin\leforge.cmd`。新开 PowerShell 才会带上 PATH；或直接用 `.\leforge-run.ps1`。

---

## torchcodec 找不到 FFmpeg 共享库

**现象**：从 git 装好后报

```
Could not load libtorchcodec. Likely causes:
  1. Couldn't load FFmpeg shared libraries ...
FFmpeg version 7: libavcodec.so.61: cannot open shared object file
FFmpeg version 6: libavutil.so.58: ...
```

**原因**：torchcodec 按 7→6→5→4 顺序加载 `libtorchcodec_coreN.so`，每个都要求对应 FFmpeg 大版本的**普通 soname**（如 `libavcodec.so.61`）。新机器上没有系统 FFmpeg 就全失败。

**已自动处理**：`install.sh` 会调用 `python -m leforge.utils.ffmpeg_shim --ensure`，把 **PyAV 自带的 FFmpeg 7**（`site-packages/av.libs/`）接上。做法是建一个 shim 目录，同时链两种名字 —— 普通 soname 给 torchcodec 用，hash 名（`libdrm-b0291a67.so.2.4.0`）给这批库互相引用用。`leforge-run.sh` 与 `leforge` 命令会在启动前把它注入 `LD_LIBRARY_PATH`（必须启动前设，运行时改无效）。

**手动处理**（三选一）：

```bash
sudo apt install ffmpeg                     # 有 root 时最干净
conda install -y -c conda-forge ffmpeg      # 无 root；需把 $CONDA_PREFIX/lib 加进 LD_LIBRARY_PATH
python -m leforge.utils.ffmpeg_shim --ensure  # 无 root 无 conda，用 PyAV 自带的库
```

**不修也能用**：`leforge.utils.video_backend` 会探测到 torchcodec 不可用并自动退回 **pyav** 解码，训练/回放照常，只是慢一些。

**验证修好了**：

```bash
python -c "import json;from torchcodec._core.ops import _get_json_ffmpeg_library_versions as j;print(json.loads(j())['ffmpeg_version'])"
```

