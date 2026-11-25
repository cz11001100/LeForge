#!/usr/bin/env python3
"""Repeatable entry points for the three sim-RL paths.

The script only orchestrates tools that already live in this repo:

* path 4: ``lerobot_eval`` + ``SO101Env(initial_joints=...)`` from a recorded
  dataset's first frame (arm joints only; ball poses are still randomized).
* path 5: ``lerobot-edit-dataset`` crop/feature pruning -> ``lerobot_train``
  (TDMPC) -> ``lerobot_eval``.
* path 6: path 5 base policy -> recorded sim rollout -> merge rollout into the
  training set -> retrain -> evaluate. This is the data-flywheel version, not a
  gradient-level online trainer.

All runs are isolated under ``sim/out/rl_paths/<run-id>/`` and each subprocess
gets its own log; ``summary.json`` records checkpoints and metrics.

Examples::

    bash sim/run_rl_paths.sh 4
    bash sim/run_rl_paths.sh 5 --steps 10 --batch-size 8
    bash sim/run_rl_paths.sh 6 --rollout-steps 100
    bash sim/run_rl_paths.sh all --run-id smoke
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


SIM_DIR = Path(__file__).resolve().parent
REPO_ROOT = SIM_DIR.parent
LEROBOT_DIR = REPO_ROOT / "lerobot"
DEFAULT_SCENE = SIM_DIR / "so101-tabletop-mujoco"
DEFAULT_TASK = "grasp the red ball"
DEFAULT_WORK_ROOT = SIM_DIR / "out" / "rl_paths"


def fail(message: str) -> None:
    raise SystemExit(f"[ERROR] {message}")


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"读取失败 {path}: {exc}")


def compact_json(value) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def find_source_dataset(explicit: str | None) -> Path:
    """Pick the recorded sim-eval batch with the most frames.

    The recordings produced by ``lerobot_eval --eval.recording=true`` live under
    ``.../sim_eval/<timestamp>/recordings/<group>/batch_*/``.
    """
    if explicit:
        root = Path(explicit).expanduser().resolve()
        if not (root / "meta" / "info.json").is_file():
            fail(f"--source-dataset 不是 LeRobot 数据集根目录（缺 meta/info.json）：{root}")
        return root

    pattern = os.path.expanduser(
        "~/.cache/huggingface/lerobot/outputs/train/*/sim_eval/*/recordings/*/batch_*/meta/info.json"
    )
    candidates: list[tuple[int, float, Path]] = []
    for info_path in glob.glob(pattern):
        info = load_json(Path(info_path))
        features = info.get("features") or {}
        needed = {
            "observation.images.up",
            "observation.state",
            "action",
            "next.reward",
        }
        if not needed.issubset(features):
            continue
        if int(info.get("total_frames") or 0) < 50:
            continue
        candidates.append(
            (
                int(info.get("total_frames") or 0),
                Path(info_path).stat().st_mtime,
                Path(info_path).parent.parent,
            )
        )
    if not candidates:
        fail(
            "没找到可用的仿真录制数据。先在 LeForge 里跑一次带录制的仿真评测，"
            "或显式传 --source-dataset <数据集根目录>。"
        )
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][2]


def find_act3_model(explicit: str | None) -> Path:
    if explicit:
        model = Path(explicit).expanduser().resolve()
        if not (model / "config.json").is_file():
            fail(f"--act3-model 不是策略目录：{model}")
        return model

    patterns = [
        "~/.cache/huggingface/lerobot/outputs/train/imported_act_zgx0920_common_1115_1_*_s25000/model/config.json",
        "~/.cache/huggingface/lerobot/outputs/train/imported_act_*/model/config.json",
    ]
    candidates: list[tuple[float, Path]] = []
    for pattern in patterns:
        for config_path in glob.glob(os.path.expanduser(pattern)):
            cfg = load_json(Path(config_path))
            cameras = {
                key.removeprefix("observation.images.")
                for key in (cfg.get("input_features") or {})
                if key.startswith("observation.images.")
            }
            if str(cfg.get("type") or "").lower() != "act":
                continue
            if not {"up", "side", "wrist"}.issubset(cameras):
                continue
            candidates.append((Path(config_path).stat().st_mtime, Path(config_path).parent))
    if not candidates:
        fail(
            "没找到 ACT3 checkpoint（imported_act_zgx0920_common_1115_1_*_s25000）。"
            "显式传 --act3-model <model 目录>，或先用 LeForge 导入 ACT3。"
        )
    candidates.sort(reverse=True)
    return candidates[0][1]


def resolve_device(value: str) -> str:
    if value != "auto":
        return value
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def read_source_task(source: Path) -> str:
    """The task string recorded with the source dataset (e.g. red vs blue ball)."""
    try:
        from lerobot.datasets import LeRobotDataset

        dataset = LeRobotDataset(repo_id="eval_recording", root=str(source))
        return str(dataset[0].get("task") or DEFAULT_TASK)
    except Exception as exc:
        print(f"[warn] 读取源数据集 task 失败，回退 {DEFAULT_TASK!r}: {exc}")
        return DEFAULT_TASK


@dataclass
class Ctx:
    args: argparse.Namespace
    run_root: Path
    source: Path
    scene: Path
    act3_model: Path | None
    device: str
    task: str
    env: dict[str, str]

    @property
    def python(self) -> str:
        return sys.executable


def make_ctx(args: argparse.Namespace, *, need_act3: bool) -> Ctx:
    work_root = Path(args.work_root).expanduser().resolve() if args.work_root else DEFAULT_WORK_ROOT
    run_id = args.run_id or time.strftime("%Y%m%d_%H%M%S")
    run_root = work_root / run_id
    if run_root.exists() and any(run_root.iterdir()):
        fail(f"运行目录非空：{run_root}；换一个 --run-id，或先移走旧目录。")
    run_root.mkdir(parents=True, exist_ok=True)

    scene = Path(args.sim_scene).expanduser().resolve() if args.sim_scene else DEFAULT_SCENE
    if not (scene / "env.py").is_file():
        fail(f"仿真场景不完整（缺 env.py）：{scene}")

    source = find_source_dataset(args.source_dataset)
    act3 = find_act3_model(args.act3_model) if need_act3 else None
    device = resolve_device(args.device)
    task = args.task or read_source_task(source)

    env = os.environ.copy()
    env.setdefault("MUJOCO_GL", "egl")
    env.setdefault("HF_HUB_OFFLINE", "1")
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault("PYTHONPATH", str(LEROBOT_DIR / "src"))

    print(f"[run] root       {run_root}")
    print(f"[run] source     {source}")
    if act3 is not None:
        print(f"[run] act3       {act3}")
    print(f"[run] scene      {scene}")
    print(f"[run] task       {task}")
    print(f"[run] device     {device}")

    return Ctx(
        args=args,
        run_root=run_root,
        source=source,
        scene=scene,
        act3_model=act3,
        device=device,
        task=task,
        env=env,
    )


def run(cmd: list, ctx: Ctx, name: str) -> None:
    log_path = ctx.run_root / "logs" / f"{name}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    printable = " ".join(shlex.quote(str(part)) for part in cmd)
    print(f"\n$ {printable}")
    print(f"  log -> {log_path}")
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [str(part) for part in cmd],
            cwd=str(LEROBOT_DIR),
            env=ctx.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            log.write(line)
        proc.wait()
    if proc.returncode != 0:
        tail = "\n".join(log_path.read_text(errors="replace").splitlines()[-20:])
        fail(f"{name} 失败（退出码 {proc.returncode}），日志：{log_path}\n{tail}")


def read_metrics(eval_dir: Path) -> dict:
    info_path = eval_dir / "eval_info.json"
    if not info_path.is_file():
        return {"error": f"缺少 {info_path}"}
    info = load_json(info_path)
    overall = info.get("overall") or {}
    env_metrics = None
    for task in info.get("per_task") or []:
        measured = (task.get("metrics") or {}).get("env_metrics_mean")
        if isinstance(measured, dict):
            env_metrics = measured
            break
    return {
        "n_episodes": overall.get("n_episodes"),
        "n_success": overall.get("n_success"),
        "pc_success": overall.get("pc_success"),
        "env_metrics": env_metrics,
    }


def find_recording(eval_dir: Path) -> Path:
    infos = sorted(eval_dir.glob("recordings/*/batch_*/meta/info.json"))
    if not infos:
        fail(f"{eval_dir} 下没有录制数据（recordings/*/batch_*/meta/info.json）")
    return infos[0].parent.parent


def eval_cmd(
    ctx: Ctx,
    checkpoint: Path,
    out_dir: Path,
    *,
    make_env_kwargs: dict,
    n_episodes: int,
    max_steps: int,
    seed: int,
    recording: bool,
) -> list:
    cmd = [
        ctx.python,
        "-m",
        "lerobot.scripts.lerobot_eval",
        f"--policy.path={checkpoint}",
        "--env.type=envhub",
        f"--env.hub_path={ctx.scene}",
        "--trust_remote_code=true",
        f"--eval.n_episodes={n_episodes}",
        "--eval.batch_size=1",
        "--eval.use_async_envs=false",
        f"--eval.max_episode_steps={max_steps}",
        f"--output_dir={out_dir}",
        f"--seed={seed}",
        f"--env.make_env_kwargs={compact_json(make_env_kwargs)}",
    ]
    if recording:
        cmd.append("--eval.recording=true")
    return cmd


def path4(ctx: Ctx) -> dict:
    from lerobot.datasets import LeRobotDataset

    args = ctx.args
    if ctx.act3_model is None:
        fail("路径 4 需要 ACT3 checkpoint，但未找到")
    dataset = LeRobotDataset(repo_id="eval_recording", root=str(ctx.source))
    initial_joints = [round(float(value), 6) for value in dataset[0]["observation.state"]]
    out_dir = ctx.run_root / "path4_act3_init"
    kwargs = {
        "cameras": {"up": "top", "side": "front", "wrist": "wrist_cam"},
        "initial_joints": initial_joints,
        "episode_length": args.max_steps,
        "instruction": ctx.task,
        # The dataset's first frame is the exact pose we want; keep ball
        # randomization from layout.json but disable the ±2° joint jitter.
        "randomize": {"joints": 0.0},
    }
    run(
        eval_cmd(
            ctx,
            ctx.act3_model,
            out_dir,
            make_env_kwargs=kwargs,
            n_episodes=args.eval_episodes,
            max_steps=args.max_steps,
            seed=args.seed,
            recording=True,
        ),
        ctx,
        "path4_eval",
    )

    replay_delta = None
    recordings = sorted(out_dir.glob("recordings/*/batch_*/meta/info.json"))
    if recordings:
        record_root = recordings[0].parent.parent
        replay = LeRobotDataset(repo_id="eval_recording", root=str(record_root))
        replay_state = [float(value) for value in replay[0]["observation.state"]]
        replay_delta = max(abs(a - b) for a, b in zip(replay_state, initial_joints))
        print(f"[path4] 首帧关节最大偏差 {replay_delta:.4f}°")

    result = {
        "eval_dir": str(out_dir),
        "metrics": read_metrics(out_dir),
        "initial_joints": initial_joints,
        "replay_delta_deg": replay_delta,
        "note": "只对齐了机械臂初始关节；球位未写入数据集，仍按 layout 随机。",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def prepare_dataset(ctx: Ctx) -> Path:
    """Feature-prune to the up camera, then center-crop/resize to 128x128."""
    up_dir = ctx.run_root / "datasets" / "up"
    sq_dir = ctx.run_root / "dataset_sq"

    if not (up_dir / "meta" / "info.json").is_file():
        source_info = load_json(ctx.source / "meta" / "info.json")
        features = set((source_info.get("features") or {}).keys())
        drop = sorted(
            key
            for key in features
            if key.startswith("observation.images.") and key != "observation.images.up"
        )
        if "observation.images.up" not in features:
            fail(f"源数据集没有 observation.images.up：{ctx.source}")
        if drop:
            run(
                [
                    ctx.python,
                    "-m",
                    "lerobot.scripts.lerobot_edit_dataset",
                    "--repo_id=eval_recording",
                    f"--root={ctx.source}",
                    "--new_repo_id=sim_tdmpc_up",
                    f"--new_root={up_dir}",
                    "--operation.type=remove_feature",
                    f"--operation.feature_names={drop!r}",
                ],
                ctx,
                "path5_remove_feature",
            )
        else:
            # Already a single-camera dataset: copy so the crop output still
            # lands inside this run directory.
            shutil.copytree(ctx.source, up_dir)

    if not (sq_dir / "meta" / "info.json").is_file():
        info = load_json(up_dir / "meta" / "info.json")
        shape = ((info.get("features") or {}).get("observation.images.up") or {}).get("shape")
        if not shape or len(shape) < 2:
            fail(f"{up_dir} 缺少 up 相机尺寸信息")
        height, width = int(shape[0]), int(shape[1])
        side = min(height, width)
        crop_path = ctx.run_root / "crop_up_center.json"
        crop_path.write_text(
            json.dumps({"observation.images.up": [0, (width - side) // 2, side, side]})
        )
        run(
            [
                ctx.python,
                "-m",
                "lerobot.rl.crop_dataset_roi",
                "--repo-id=sim_tdmpc_up",
                f"--root={up_dir}",
                f"--crop-params-path={crop_path}",
                "--new-repo-id=dataset_sq",
                f"--task={ctx.task}",
            ],
            ctx,
            "path5_crop",
        )

    if not (sq_dir / "meta" / "info.json").is_file():
        fail(f"裁剪输出不在预期位置：{sq_dir}（crop 工具按 <up_dir>.parent.parent 落盘）")
    return sq_dir


def train_tdmpc(ctx: Ctx, dataset_root: Path, repo_id: str, out_dir: Path, name: str) -> Path:
    steps = ctx.args.steps
    checkpoint = out_dir / "checkpoints" / f"{steps:06d}" / "pretrained_model"
    if not checkpoint.is_dir():
        run(
            [
                ctx.python,
                "-m",
                "lerobot.scripts.lerobot_train",
                f"--dataset.repo_id={repo_id}",
                f"--dataset.root={dataset_root}",
                "--dataset.video_backend=pyav",
                "--policy.type=tdmpc",
                f"--policy.device={ctx.device}",
                "--policy.push_to_hub=false",
                f"--output_dir={out_dir}",
                f"--steps={steps}",
                f"--batch_size={ctx.args.batch_size}",
                f"--save_freq={steps}",
                f"--log_freq={max(1, steps // 5)}",
                "--num_workers=0",
            ],
            ctx,
            name,
        )
    if not checkpoint.is_dir():
        fail(f"训练结束但没找到 checkpoint：{checkpoint}")
    return checkpoint


def eval_tdmpc(
    ctx: Ctx,
    checkpoint: Path,
    out_dir: Path,
    *,
    seed: int,
    recording: bool,
    name: str,
) -> dict:
    max_steps = ctx.args.rollout_steps
    kwargs = {
        "cameras": {"up": "top"},
        "observation_height": 128,
        "observation_width": 128,
        "episode_length": max_steps,
    }
    run(
        eval_cmd(
            ctx,
            checkpoint,
            out_dir,
            make_env_kwargs=kwargs,
            n_episodes=ctx.args.eval_episodes,
            max_steps=max_steps,
            seed=seed,
            recording=recording,
        ),
        ctx,
        name,
    )
    return read_metrics(out_dir)


def path5(ctx: Ctx, *, evaluate: bool = True) -> tuple[Path, dict]:
    dataset_root = prepare_dataset(ctx)
    checkpoint = train_tdmpc(
        ctx, dataset_root, "dataset_sq", ctx.run_root / "path5_train", "path5_train"
    )
    result = {
        "dataset": str(dataset_root),
        "checkpoint": str(checkpoint),
    }
    if evaluate:
        eval_dir = ctx.run_root / "path5_eval"
        result["eval_dir"] = str(eval_dir)
        result["metrics"] = eval_tdmpc(
            ctx, checkpoint, eval_dir, seed=ctx.args.seed, recording=False, name="path5_eval"
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return checkpoint, result


def path6(ctx: Ctx, base_checkpoint: Path, base_dataset: Path) -> dict:
    rollout_dir = ctx.run_root / "path6_rollout"
    rollout_metrics = eval_tdmpc(
        ctx,
        base_checkpoint,
        rollout_dir,
        seed=ctx.args.seed + 1,
        recording=True,
        name="path6_rollout",
    )
    record_root = find_recording(rollout_dir)

    merged_dir = ctx.run_root / "dataset_flywheel"
    if not (merged_dir / "meta" / "info.json").is_file():
        run(
            [
                ctx.python,
                "-m",
                "lerobot.scripts.lerobot_edit_dataset",
                "--new_repo_id=dataset_flywheel",
                f"--new_root={merged_dir}",
                "--operation.type=merge",
                f"--operation.repo_ids={['dataset_sq', 'eval_recording']}",
                f"--operation.roots={[str(base_dataset), str(record_root)]}",
            ],
            ctx,
            "path6_merge",
        )
    if not (merged_dir / "meta" / "info.json").is_file():
        fail(f"合并数据集不存在：{merged_dir}")

    checkpoint = train_tdmpc(
        ctx, merged_dir, "dataset_flywheel", ctx.run_root / "path6_train", "path6_train"
    )
    eval_dir = ctx.run_root / "path6_eval"
    metrics = eval_tdmpc(
        ctx, checkpoint, eval_dir, seed=ctx.args.seed + 2, recording=False, name="path6_eval"
    )
    result = {
        "base_checkpoint": str(base_checkpoint),
        "rollout_dir": str(rollout_dir),
        "rollout_metrics": rollout_metrics,
        "recorded_dataset": str(record_root),
        "merged_dataset": str(merged_dir),
        "checkpoint": str(checkpoint),
        "eval_dir": str(eval_dir),
        "metrics": metrics,
        "note": "数据飞轮版：闭环采样 -> 回灌合并 -> 继续训；不是梯度级 online 更新。",
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the repeatable sim-RL paths (4/5/6) with existing LeRobot tools.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("path", choices=("4", "5", "6", "all"), help="要跑的路径")
    parser.add_argument("--run-id", help="输出子目录名；默认时间戳")
    parser.add_argument("--work-root", help=f"输出根目录；默认 {DEFAULT_WORK_ROOT}")
    parser.add_argument("--source-dataset", help="仿真录制数据集根目录；默认自动选帧数最多的一份")
    parser.add_argument("--act3-model", help="ACT3 checkpoint 目录；默认自动查找 imported_act_*_s25000")
    parser.add_argument("--sim-scene", help=f"仿真场景目录；默认 {DEFAULT_SCENE}")
    parser.add_argument("--device", default="auto", choices=("auto", "cuda", "cpu"))
    parser.add_argument("--task", help=f"数据集任务字符串；默认读取源数据集首帧（兜底 {DEFAULT_TASK!r}）")
    parser.add_argument("--steps", type=int, default=10, help="每次 TDMPC 训练步数")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--rollout-steps", type=int, default=100, help="TDMPC 闭环/录制步数")
    parser.add_argument("--eval-episodes", type=int, default=1)
    parser.add_argument("--max-steps", type=int, default=600, help="路径 4 的 ACT3 闭环步数")
    parser.add_argument("--seed", type=int, default=1000)
    args = parser.parse_args()
    if args.steps < 1 or args.batch_size < 1 or args.rollout_steps < 10 or args.max_steps < 10:
        parser.error("steps/batch-size 需 >=1，rollout-steps/max-steps 需 >=10")
    return args


def main() -> None:
    args = parse_args()
    ctx = make_ctx(args, need_act3=args.path in ("4", "all"))
    summary: dict = {
        "run_root": str(ctx.run_root),
        "source_dataset": str(ctx.source),
        "task": ctx.task,
        "device": ctx.device,
        "args": vars(args),
    }
    if ctx.act3_model is not None:
        summary["act3_model"] = str(ctx.act3_model)

    base_checkpoint: Path | None = None
    base_dataset: Path | None = None

    if args.path in ("4", "all"):
        summary["path4"] = path4(ctx)

    if args.path in ("5", "all"):
        base_checkpoint, path5_result = path5(ctx, evaluate=True)
        base_dataset = Path(path5_result["dataset"])
        summary["path5"] = path5_result
    elif args.path == "6":
        # Path 6 needs a base policy/dataset; reuse the same preparation pipeline
        # but skip the base evaluation to keep the single command short.
        base_checkpoint, path5_result = path5(ctx, evaluate=False)
        base_dataset = Path(path5_result["dataset"])
        summary["path5_base"] = path5_result

    if args.path in ("6", "all"):
        assert base_checkpoint is not None and base_dataset is not None
        summary["path6"] = path6(ctx, base_checkpoint, base_dataset)

    summary_path = ctx.run_root / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n[done] summary -> {summary_path}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()