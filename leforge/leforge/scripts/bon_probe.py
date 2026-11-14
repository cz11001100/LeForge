# Copyright 2025 The HuggingFace Inc. team. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Offline Best-of-N preflight: does BoN help this checkpoint on this dataset?

Runs without the robot: fits the aim verifier, overlays the policy's implied
aim on the true ball (aim.probe), then replays the BoN decision offline —
sample N perturbed chunks per frame, score them with the verifier, and compare
the best candidate's aim error against the greedy mean chunk's.

    python -m lelab.scripts.bon_probe --repo_id user/demo \
        --checkpoint /path/to/pretrained_model --camera up --colors red

Without --checkpoint only the verifier calibration is checked (R² gate).
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _load_dataset(repo_id: str, horizon: int, cfg=None):
    from lerobot.datasets.lerobot_dataset import LeRobotDataset, LeRobotDatasetMetadata

    ds_meta = LeRobotDatasetMetadata(repo_id)
    if cfg is not None:
        from lerobot.datasets.factory import resolve_delta_timestamps

        delta = resolve_delta_timestamps(cfg, ds_meta)
    else:
        fps = float(ds_meta.fps)
        delta = {"action": [i / fps for i in range(horizon)]}
    dataset = LeRobotDataset(repo_id, delta_timestamps=delta)
    return ds_meta, dataset


def _camera_key(ds_meta, camera: str) -> str | None:
    want = camera if camera.startswith("observation.images.") else f"observation.images.{camera}"
    return next((k for k in ds_meta.camera_keys if k.lower() == want.lower()), None)


def _predict_item_factory(policy, preprocessor, postprocessor, device, image_rename):
    import torch
    from torch.utils.data import default_collate

    def predict_item(item):
        batch = default_collate([item])
        batch = {image_rename.get(k, k): v for k, v in batch.items()}
        with torch.inference_mode():
            processed = preprocessor(dict(batch))
            obs = {k: v for k, v in processed.items() if k != "action"}
            pred = policy.predict_action_chunk(obs)
            if not torch.is_tensor(pred):
                pred = pred["action"]
            chunk = postprocessor(pred.to(device)).float().cpu()
        state = batch["observation.state"].float().reshape(-1)
        chunk = chunk[0, :, : state.shape[0]]
        return chunk, state

    return predict_item


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="bon_probe", description=__doc__)
    parser.add_argument("--repo_id", required=True)
    parser.add_argument("--checkpoint", default="", help="pretrained_model dir; omit for verifier-only check")
    parser.add_argument("--camera", default="up")
    parser.add_argument("--colors", default="red")
    parser.add_argument("--horizon", type=int, default=25)
    parser.add_argument("--n", type=int, default=8)
    parser.add_argument("--sigma", type=float, default=0.15)
    parser.add_argument("--frames", type=int, default=8)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--device", default="")
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)

    import numpy as np

    from .. import aim
    from ..saliency import _to_uint8_hwc, find_ball

    colors = [c for c in args.colors.split(",") if c]
    out_dir = Path(args.out) if args.out else Path.home() / ".cache" / "huggingface" / "lerobot" / f"bon_probe_{int(time.time())}"

    cfg = None
    if args.checkpoint:
        import torch
        from lerobot.configs.policies import PreTrainedConfig
        from lerobot.policies.factory import make_policy, make_pre_post_processors

        device = torch.device(args.device or ("cuda" if torch.cuda.is_available() else "cpu"))
        cfg = PreTrainedConfig.from_pretrained(args.checkpoint)
        cfg.pretrained_path = args.checkpoint
        cfg.device = str(device)
    else:
        device = None

    ds_meta, dataset = _load_dataset(args.repo_id, args.horizon, cfg)
    cam_key = _camera_key(ds_meta, args.camera)
    if cam_key is None:
        logger.error("相机 %s 不在数据集里：%s", args.camera, ds_meta.camera_keys)
        return 1

    fit = aim.fit(dataset, cam_key, colors, horizon=args.horizon)
    if fit is None:
        logger.error("verifier 拟合失败：可用帧不足")
        return 1
    aim.save_calibration(Path(dataset.root), fit)
    summary: dict = {
        "repo_id": args.repo_id,
        "camera": cam_key,
        "calibration_r2_xy": fit["r2_xy"],
        "mean_r2": fit["mean_r2"],
        "verifier_usable": aim.verifier_usable(fit),
    }
    logger.info("verifier R²=%s usable=%s", fit["r2_xy"], summary["verifier_usable"])
    if not args.checkpoint:
        summary["verdict"] = (
            "verifier 可用，可以上机跑 BoN" if summary["verifier_usable"]
            else "verifier R² 低于 0.5，BoN 会退回 greedy —— 先换相机/颜色或补数据"
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0

    # Camera keys may differ only by case between dataset and checkpoint.
    want = {k.lower(): k for k in cfg.input_features if k.startswith("observation.images.")}
    image_rename = {k: want[k.lower()] for k in ds_meta.camera_keys if k.lower() in want and want[k.lower()] != k}
    policy = make_policy(cfg=cfg, ds_meta=ds_meta, rename_map=image_rename or None)
    policy.eval()
    preprocessor, postprocessor = make_pre_post_processors(
        policy_cfg=cfg,
        pretrained_path=args.checkpoint,
        preprocessor_overrides={"device_processor": {"device": str(device)}},
    )
    predict_item = _predict_item_factory(policy, preprocessor, postprocessor, device, image_rename)

    pool = list(range(len(dataset)))
    random.Random(args.seed).shuffle(pool)
    indices = pool[: max(args.frames * 4, 40)]

    import importlib.util

    if importlib.util.find_spec("matplotlib") is not None:
        probe = aim.probe(dataset, predict_item, indices[: args.frames], fit, colors, out_dir / "aim")
        summary["aim_probe"] = {k: probe[k] for k in ("mean_aim_error_model_px", "mean_aim_error_human_px", "verdict") if k in probe}
    else:
        summary["aim_probe"] = {"verdict": "matplotlib 未安装，跳过 aim 叠加图（pip install matplotlib 后可出图）"}

    # Offline BoN replay: greedy mean chunk vs best-of-N under the verifier.
    samples = []
    for index in indices:
        if len(samples) >= args.frames:
            break
        item = dataset[int(index)]
        frame = _to_uint8_hwc(item[cam_key])
        ball = find_ball(frame, colors)
        if not ball:
            continue
        chunk, state = predict_item(item)
        h = max(1, min(args.horizon, chunk.shape[0]))
        samples.append((frame, ball, chunk[h - 1].numpy(), state.numpy()))

    greedy_errs, bon_errs, wins = [], [], 0
    if len(samples) >= 2:
        std = np.maximum(np.std(np.stack([s[2] for s in samples]), axis=0), 1e-3) * args.sigma
        rng = np.random.default_rng(args.seed)
        for frame, ball, mu, state in samples:
            center = (ball["cx"], ball["cy"])
            g_px = aim.aim_point(fit, mu, state, frame.shape[:2])
            if g_px is None:
                continue
            g_err = float(np.hypot(g_px[0] - center[0], g_px[1] - center[1]))
            cands = mu + (rng.standard_normal((args.n, mu.shape[0])) * std).clip(-4 * std, 4 * std)
            scores = [aim.score_chunk(fit, c, state, center, frame.shape[:2]) for c in cands]
            best = cands[int(np.argmax(scores))]
            b_px = aim.aim_point(fit, best, state, frame.shape[:2])
            b_err = float(np.hypot(b_px[0] - center[0], b_px[1] - center[1]))
            greedy_errs.append(g_err)
            bon_errs.append(b_err)
            wins += b_err < g_err
    if greedy_errs:
        g, b = float(np.mean(greedy_errs)), float(np.mean(bon_errs))
        summary["offline_bon"] = {
            "frames": len(greedy_errs),
            "n": args.n,
            "sigma_scale": args.sigma,
            "greedy_aim_err_px": round(g, 1),
            "bon_aim_err_px": round(b, 1),
            "win_rate": round(wins / len(greedy_errs), 2),
        }
        if not summary["verifier_usable"]:
            summary["verdict"] = "verifier 不可用，离线对照只作参考；上机 BoN 会退回 greedy"
        elif b < g * 0.9:
            summary["verdict"] = f"离线 BoN 把指向偏差从 {g:.0f}px 降到 {b:.0f}px（胜率 {wins}/{len(greedy_errs)}）→ 值得上机"
        else:
            summary["verdict"] = f"离线 BoN 收益有限（{g:.0f}px → {b:.0f}px）→ 先调 σ/N 或检查 verifier"
    else:
        summary["verdict"] = "没有足够帧做离线对照"

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    logger.info("charts + summary → %s", out_dir)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
