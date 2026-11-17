# LeForge

SO-100 / SO-101 机械臂的 LeRobot Web 工作台：在浏览器里完成标定、遥操作、数据采集与回放、训练、评估与仿真评测。

主要功能：leader 主臂遥操、键盘 IK 遥操、数据集管理（Hub 拉取 / HDF5、Zarr 导入导出）、本地与 SSH / HuggingFace 云训练、策略评估、MuJoCo 仿真评测、BoN 数据飞轮、相机曝光与增益调节。

## Linux

**一键安装**（Ubuntu 22.04+，装完运行 `leforge`，浏览器打开 http://localhost:8000）

```bash
curl -fsSL https://raw.githubusercontent.com/cz11001100/LeForge/main/install.sh | bash
```

**最小安装**

```bash
curl -fsSL https://raw.githubusercontent.com/cz11001100/LeForge/main/install.sh | bash -s -- --lite
```

**升级**（重跑安装命令，会自动拉取最新代码）

```bash
curl -fsSL https://raw.githubusercontent.com/cz11001100/LeForge/main/install.sh | bash      # 轻量档加 -s -- --lite
```

**适配硬件**

| 方式 | 适用配置 |
|---|---|
| 一键安装 | 有 NVIDIA 显卡（含 RTX 50 系）。装 cu128 版 torch，可本地训练与推理；占用约 6.5GB |
| 最小安装 | 无独显 / 轻薄本 / 纯 CPU。装 CPU 版 torch，占用约 2.2GB；遥操、采集、回放、评估照常，本地训练改走 SSH 云端 GPU |

## Windows

**一键安装**（Windows 10/11，无需 WSL2，PowerShell 里粘贴。代码落在 `%USERPROFILE%\LeForge`，装完运行 `%USERPROFILE%\LeForge\leforge-run.ps1`）

```powershell
powershell -ExecutionPolicy Bypass -NoProfile -Command "irm https://raw.githubusercontent.com/cz11001100/LeForge/main/install.ps1 | iex"
```

**最小安装**

```powershell
$env:LEFORGE_PROFILE="lite"; irm https://raw.githubusercontent.com/cz11001100/LeForge/main/install.ps1 | iex
```

**升级**（同步脚本、Python 依赖与前端产物；轻量档先执行 `$env:LEFORGE_PROFILE="lite"`）

```powershell
powershell -ExecutionPolicy Bypass -NoProfile -Command "irm https://raw.githubusercontent.com/cz11001100/LeForge/main/upgrade.ps1 | iex"
```

**适配硬件**

| 方式 | 适用配置 |
|---|---|
| 一键安装 | 有 NVIDIA 显卡（含 RTX 50 系）。装 cu128 版 torch，可本地训练与推理；占用约 6.5GB |
| 最小安装 | 无独显 / 轻薄本 / 纯 CPU。装 CPU 版 torch，占用约 2.2GB；遥操、采集、回放、评估照常，本地训练改走 SSH 云端 GPU |

Windows 不安装 `placo`，键盘 IK 遥操（keyboard_ee）不可用，接 leader 主臂遥操正常。
