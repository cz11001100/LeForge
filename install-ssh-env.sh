#!/usr/bin/env bash
# LeForge 远端 SSH 训练环境安装（在 GPU pod 上执行）
#
#   bash install-ssh-env.sh            # 自动档：有 NVIDIA 卡走完整档
#   bash install-ssh-env.sh --cn      # 国内加速：PyPI/uv 走清华，torch 走 SJTU 镜像
#
# 做的事：apt 依赖（git/curl/ffmpeg）→ 克隆/更新本仓库 → 运行 install.sh --full
# （uv + PyTorch cu128 + 本仓库 lerobot 与 leforge + MuJoCo）→ 自检 → 探测策略工厂。
# 幂等：重复执行会复用已有 venv 并增量更新仓库。
#
# 输出协议（供 LeForge 安装器解析进度）：
#   [STEP k/6] 描述 / [OK k] 摘要 / [FAIL k] 原因 / LEFORGE_PY=<venv python> / [ALL-OK]

set -uo pipefail

CN=false
PROFILE="full"
for arg in "$@"; do
    case "$arg" in
        --cn) CN=true ;;
        --full) PROFILE="full" ;;
        --lite) PROFILE="lite" ;;
        *) echo "[WARN] 忽略未知参数：$arg" ;;
    esac
done

ROOT="${LEFORGE_ROOT:-$HOME/LeForge}"
REPO="https://github.com/cz11001100/LeForge.git"
PROXY="https://gh-proxy.com/$REPO"
PY="$ROOT/lerobot-env/bin/python"

fail() { echo "[FAIL $1] $2"; exit 1; }

# ---------- 1. GPU ----------
echo "[STEP 1/6] 检测 GPU"
GPU=$(nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>/dev/null || true)
if [ -z "$GPU" ]; then
    fail 1 "nvidia-smi 不可用：完整档需要 NVIDIA 驱动（重启实例挂载 GPU 后重试）"
fi
echo "[OK 1] ${GPU%%$'\n'*}"

# ---------- 2. 系统依赖 ----------
echo "[STEP 2/6] 系统依赖（git / curl / ffmpeg）"
APT=""
if [ "$(id -u)" = "0" ]; then APT="apt-get"; elif command -v sudo >/dev/null 2>&1; then APT="sudo -n apt-get"; fi
need_apt=false
for c in git curl ffmpeg; do command -v "$c" >/dev/null 2>&1 || need_apt=true; done
if $need_apt; then
    [ -n "$APT" ] || fail 2 "缺少 git/curl/ffmpeg 且当前用户无法执行 apt-get（非 root 且无 sudo）"
    $APT update -qq >/dev/null 2>&1 || fail 2 "apt-get update 失败（源不可用或 dpkg 锁被占用）"
    for c in git curl ffmpeg; do
        command -v "$c" >/dev/null 2>&1 || $APT install -y -qq "$c" >/dev/null 2>&1 || fail 2 "安装 $c 失败"
    done
fi
echo "[OK 2] git $(git --version 2>/dev/null | awk '{print $3}') / ffmpeg $(ffmpeg -version 2>/dev/null | head -1 | awk '{print $3}')"

# ---------- 3. 仓库 ----------
echo "[STEP 3/6] 准备仓库 $ROOT"
if [ -d "$ROOT/.git" ]; then
    UPDATE=$(cd "$ROOT" && { git pull --ff-only -q origin main 2>/dev/null || git pull --ff-only -q "$PROXY" main 2>/dev/null; } && echo updated || true)
    echo "[OK 3] $ROOT （${UPDATE:-沿用当前版本}）"
else
    rm -rf "$ROOT"
    if git clone --depth 1 -q "$REPO" "$ROOT" 2>/dev/null; then
        echo "[OK 3] $ROOT （直连克隆）"
    elif git clone --depth 1 -q "$PROXY" "$ROOT"; then
        echo "[OK 3] $ROOT （gh-proxy 克隆）"
    else
        fail 3 "GitHub 与 gh-proxy 都不可达：可在本机打包上传，或换网络后重试"
    fi
fi

# ---------- 4. install.sh ----------
echo "[STEP 4/6] 运行 install.sh --$PROFILE（uv + PyTorch + lerobot + LeForge）"
INSTALL_ENV=(LEFORGE_PROFILE="$PROFILE" HF_HUB_DISABLE_XET=1)
if $CN; then
    INSTALL_ENV+=(LEFORGE_TORCH_INDEX="https://mirror.sjtu.edu.cn/pytorch-wheels/cu128")
fi
if ! (cd "$ROOT" && env "${INSTALL_ENV[@]}" bash install.sh "--$PROFILE" 2>&1 | tail -30); then
    fail 4 "install.sh 失败（看上面日志；磁盘需 ≥15GB，网络超时最常见）"
fi
echo "[OK 4] install.sh 完成"

# ---------- 5. 自检 ----------
echo "[STEP 5/6] 自检虚拟环境"
[ -x "$PY" ] || fail 5 "没有找到 $PY"

# torchcodec 按 torch 版本发布但元数据不钉 ABI：uv/pip 常装上不匹配的版本，
# 导入时报 undefined symbol: torch_xxx。逐个版本回退对齐（与安装器 step 5b 同思路）。
if ! "$PY" -c "from torchcodec.decoders import VideoDecoder" >/dev/null 2>&1; then
    echo "[INFO] torchcodec 与 torch ABI 不匹配，自动对齐…"
    TORCH_MINOR=$("$PY" -c 'import torch; print(torch.__version__.split(".")[1])' 2>/dev/null || echo 0)
    ALIGN=()
    if command -v uv >/dev/null 2>&1; then ALIGN=(uv pip install --python "$PY"); else ALIGN=("$PY" -m pip install); fi
    for v in $(seq "$TORCH_MINOR" -1 3); do
        "${ALIGN[@]}" -q --no-deps "torchcodec==0.$v" >/dev/null 2>&1 || true
        if "$PY" -c "from torchcodec.decoders import VideoDecoder" >/dev/null 2>&1; then
            echo "[INFO] torchcodec 已对齐到 0.$v"
            break
        fi
    done
fi
SELF=$( ("$PY" - <<'PY' 2>&1 || true
import json
import torch, lerobot, transformers
from torchcodec.decoders import VideoDecoder  # noqa: F401
print("VER|" + json.dumps({
    "torch": torch.__version__,
    "cuda": torch.cuda.is_available(),
    "cuda_ver": torch.version.cuda,
    "lerobot": getattr(lerobot, "__version__", "ok"),
    "transformers": transformers.__version__,
}))
PY
) )
VER_LINE=$(printf '%s\n' "$SELF" | grep '^VER|' | tail -1 || true)
[ -n "$VER_LINE" ] || fail 5 "venv 里 torch/lerobot/transformers/torchcodec 无法导入：$(printf '%s' "$SELF" | tail -3)"
echo "[OK 5] ${VER_LINE#VER|}"

# ---------- 6. 策略工厂 ----------
echo "[STEP 6/6] 验证策略工厂"
POLICY_OUT=$("$PY" - <<'PY' 2>&1 || true
import json
r = {"ready": [], "missing": []}
POL = ("act", "diffusion", "pi0", "pi0_fast", "smolvla", "groot", "tdmpc", "vqbet")
try:
    from lerobot.policies.factory import get_policy_class
    for t in POL:
        try:
            get_policy_class(t); r["ready"].append(t)
        except BaseException:
            r["missing"].append(t)
except BaseException as e:
    r["missing"] = list(POL); r["factory_error"] = f"{type(e).__name__}: {e}"
try:
    from lerobot.rewards.factory import get_reward_model_class
    get_reward_model_class("reward_classifier"); r["ready"].append("reward_classifier")
except BaseException:
    r["missing"].append("reward_classifier")
print("POL|" + json.dumps(r))
PY
)
POL_LINE=$(printf '%s\n' "$POLICY_OUT" | grep '^POL|' | tail -1 || true)
[ -n "$POL_LINE" ] || fail 6 "策略探测没有输出：$(printf '%s' "$POLICY_OUT" | tail -3)"
MISSING=$(printf '%s' "${POL_LINE#POL|}" | "$PY" -c 'import json,sys; d=json.load(sys.stdin); print(",".join(d.get("missing") or []))')
if [ -n "$MISSING" ]; then
    fail 6 "策略缺失：$MISSING（factory_error 见日志）"
fi
READY_COUNT=$(printf '%s' "${POL_LINE#POL|}" | "$PY" -c 'import json,sys; print(len(json.load(sys.stdin)["ready"]))')
echo "[OK 6] 策略 ${READY_COUNT} 个全部可用"

echo "LEFORGE_PY=$PY"
echo "[ALL-OK]"
