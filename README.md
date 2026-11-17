# LeForge

SO-100 / SO-101 机械臂的 LeRobot 一体化 Web 工作台 —— 标定、遥操作、数据采集、训练、评估、部署全流程在浏览器里完成。单仓库同时包含界面（`leforge/`）与打过补丁的框架（`lerobot/`）。

**安装**

```bash
curl -fsSL https://raw.githubusercontent.com/cz11001100/LeForge/main/install.sh | bash
```

**最小安装**

```bash
curl -fsSL https://raw.githubusercontent.com/cz11001100/LeForge/main/install.sh | bash -s -- --lite
```

**升级**

```bash
curl -fsSL https://raw.githubusercontent.com/cz11001100/LeForge/main/install.sh | bash        # 轻量档加 -s -- --lite
```

**启动**

```bash
leforge
```

浏览器打开 http://localhost:8000。

## Windows

主流程在 Windows 10/11 上原生可用（无需 WSL2），Web 工作台、标定、遥操、采集、回放、数据集、本地训练、评估、MuJoCo 仿真评测、SSH / HF 云训练都保留。

一键安装（干净机器，PowerShell 里直接粘贴）：

```powershell
powershell -ExecutionPolicy Bypass -NoProfile -Command "irm https://raw.githubusercontent.com/cz11001100/LeForge/main/install.ps1 | iex"
```

一键升级（已经装过，更新到仓库最新）：

```powershell
powershell -ExecutionPolicy Bypass -NoProfile -Command "irm https://raw.githubusercontent.com/cz11001100/LeForge/main/upgrade.ps1 | iex"
```

两条命令都会把代码放在 `%USERPROFILE%\LeForge`，依赖装进其中的 `lerobot-env\`（缺 git / uv 时会自动安装）。升级会一起更新脚本、Python 依赖和前端产物（`frontend/dist` 随仓库发布，不需要 Node.js）。装完启动：

```powershell
%USERPROFILE%\LeForge\leforge-run.ps1
# 或新开一个 PowerShell 窗口后直接输入 leforge
```

已经有一份解压好的仓库？在仓库目录里跑 `.\install.ps1` 即可（不需要 git）；`.\install.ps1 -Upgrade` 与 `upgrade.ps1` 等价。

与 Linux 的差异（取舍）：

| 项 | Windows 上的做法 | 影响 |
|---|---|---|
| `placo`（IK） | 不安装：cmeel 二进制轮子没有 Windows 版，源码编译必然失败 | `keyboard_ee`（没有主臂时用键盘做 IK 末端遥操）不可用；接 leader 主臂遥操正常 |
| 渲染后端 | MuJoCo 用 WGL 离屏渲染（Linux 用 EGL） | 无，仿真评测照常 |
| 摄像头控制 | 走 DirectShow；不做 V4L2 曝光/增益 | 亮度/曝光要在摄像头驱动或系统设置里调 |
| 视频解码 | 不装 torchcodec（win 轮子要求 torch≥2.8，与本项目的 2.7.x 不兼容），统一走 PyAV 软解 | 无功能缺失；解码走 CPU，比硬解略慢 |
| 训练产物符号链接 | LeRobot 会建 `checkpoints/last` 软链；无权限时自动退回目录联接（junction） | 无；junction 也建不了时只告警，训练与权重不受影响 |
| torch 档位 | 检测到 NVIDIA 显卡就装 cu128 版（与 Linux 一致），`-Cpu` 强制 CPU | 无；CPU 档训练与推理会明显变慢 |

常见问题（串口驱动、摄像头占用、端口残留等）见 [TROUBLESHOOTING.md](TROUBLESHOOTING.md)。

## 更新日志

最近更新，完整历史见 [CHANGELOG.md](CHANGELOG.md)。

**2026-11-18**
- 新增 从 Hub 拉取数据集：界面里把 Hub 数据集拉到本地，带进度
- 变更 评测与仿真评测合并到一个弹窗；弹窗标题统一（DialogHeading）；暗色次要文字提亮

**2026-11-17**
- 新增 SSH 远端环境一键安装脚本 `install-ssh-env.sh`
- 新增 增广预览：放大差异图 + mean/max 像素差，细微增广也看得出
- 新增 界面文案中英双语（面板标题与关键提示）
- 变更 训练提速与远程环境修复；推理平滑状态（RTC / Chunk EMA 互斥）更清楚；页脚不再固定悬浮
- 变更 界面改深蓝暗色主题（新 Logo / SVG favicon / 深色壁纸，清理模板残留）；增广强度调宽，预览与训练里看得出效果
- 修复 HF 登录在代理环境下失败（剔除 httpx 用不了的代理）

**2026-11-14**
- 新增 BoN 数据飞轮：重规划采样 N 个动作块由 verifier 选优，目标框拖拽绘制、连续命中自动判成，失败集一键回灌续训；运行页实时调 N/k/σ、BoN/greedy 对照与候选日志
- 新增 仿真评测增强：本地场景新建 / MuJoCo 打开、环境仓库下拉、三视角录像与步级诊断、轨迹平滑与阴影柔化、时序集成按模型自适应
- 新增 仿真评测录像内存自适应：按步数×相机×分辨率估算，自动下调 batch 防撑爆内存
- 新增 相机手动曝光/增益：录制与推理按相机设定，画面一致
- 新增 键盘末端遥操：无主臂，键盘给末端增量经 IK 驱动 SO-101，遥操与采集可用
- 新增 数据集导入/导出：HDF5（ALOHA/ACT）与 Zarr ↔ LeRobotDataset 互转，界面选格式并看进度
- 新增 遥操模式切换：遥操页切 leader / keyboard_ee（无主臂），全局生效、刷新保留
- 变更 LeLab → LeForge：包名/命令/路径与安装地址全量重构，界面统一浅蓝主题
- 变更 一键安装加 placo（键盘末端遥操的 IK 依赖）
- 修复 新装环境 torchcodec 解析到 0.17 与 torch 2.7.1 ABI 不匹配 —— 钉到实测 0.5、漂移自愈，自检注入 FFmpeg shim 不再误报

## 许可与出处

Apache-2.0，基于 [LeLab](https://github.com/OneRobotAI/lelab) 与 [LeRobot](https://github.com/huggingface/lerobot) 修改；上游 LICENSE 与版权声明均已保留。
