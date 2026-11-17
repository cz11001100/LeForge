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

## 更新日志

最近更新，完整历史见 [CHANGELOG.md](CHANGELOG.md)。

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

**2026-11-12**
- 新增 数据集查看器：界面直接看各 episode 视频与动作/状态曲线，不用下到本地
- 新增 图像增广预览：训练配置里预览增广效果再决定是否启用
- 新增 仿真评测：模型卡内启动/停止 EnvHub 闭环评测，看成功率、日志与产物
- 变更 训练页可选策略随 0.7 扩充：Cosmos3、DM05、EO1/EVO1、FLUX.3、LingBot、LongWAM 等，按策略自动带出依赖
- 修复 模型卡上传后的状态：状态标签直接显示“已上传”（同“已导入”样式），不再冗长显示 repo、也不再同时出现两个状态

## 许可与出处

Apache-2.0，基于 [LeLab](https://github.com/OneRobotAI/lelab) 与 [LeRobot](https://github.com/huggingface/lerobot) 修改；上游 LICENSE 与版权声明均已保留。
