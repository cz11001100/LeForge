# Copyright 2026 The LeForge Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
"""LeRobot v2 (v2.0 / v2.1) dataset reader for import into the v3 format.

Layout handled (matches lerobot v2.1):
  meta/info.json          codebase_version "v2.x", fps, features
  meta/tasks.jsonl        {"task_index": 0, "task": "..."}
  meta/episodes.jsonl     {"episode_index": 0, "length": N, "tasks": [...]}
  data/chunk-*/episode_*.parquet
                          action / observation.state lists, task_index,
                          and an image column holding the per-episode video path
  videos/chunk-*/<feature-key>/episode_*.mp4

Image frames are decoded with PyAV (the same backend lerobot falls back to when
torchcodec is unavailable).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np

from .common import Episode, natural_key, sanitize_name, to_rgb_uint8

logger = logging.getLogger(__name__)

V2_VERSION_PREFIX = "v2"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def looks_like_lerobot_v2(path: str | Path) -> bool:
    p = Path(path).expanduser()
    info = p / "meta" / "info.json"
    if not info.is_file():
        return False
    try:
        version = str(_load_json(info).get("codebase_version") or "")
    except (OSError, json.JSONDecodeError):
        return False
    return version.startswith(V2_VERSION_PREFIX)


def _episodes_meta(root: Path) -> list[dict[str, Any]]:
    path = root / "meta" / "episodes.jsonl"
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            logger.warning("Skipping malformed episodes.jsonl line: %s", line[:80])
    return out


def _tasks(root: Path) -> dict[int, str]:
    path = root / "meta" / "tasks.jsonl"
    out: dict[int, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        out[int(item.get("task_index", 0))] = str(item.get("task", ""))
    return out


def _image_keys(info: dict[str, Any]) -> list[str]:
    feats = info.get("features") or {}
    return [
        key
        for key, feat in feats.items()
        if key.startswith("observation.images.") and str(feat.get("dtype")) in ("video", "image")
    ]


def inspect(path: str | Path) -> dict[str, Any]:
    """Summarize a v2 dataset without converting it."""
    root = Path(path).expanduser()
    info = _load_json(root / "meta" / "info.json")
    episodes = _episodes_meta(root)
    feats = info.get("features") or {}
    lengths = [int(e.get("length", 0)) for e in episodes]
    cameras = []
    for key in _image_keys(info):
        feat = feats.get(key) or {}
        cameras.append({"source": key, "name": key.split(".")[-1], "shape": list(feat.get("shape") or [])})
    state_shape = list((feats.get("observation.state") or {}).get("shape") or [])
    action_shape = list((feats.get("action") or {}).get("shape") or [])
    files = sorted(root.glob("data/chunk-*/*.parquet"), key=lambda p: natural_key(p.name))
    warnings = []
    if not episodes:
        warnings.append("缺少 meta/episodes.jsonl，集数以 parquet 文件数推算")
    return {
        "episode_count": int(info.get("total_episodes") or len(files) or len(episodes)),
        "episode_lengths": lengths,
        "truncated": False,
        "total_frames": int(info.get("total_frames") or sum(lengths) or 0),
        "fps": info.get("fps"),
        "task": next(iter(_tasks(root).values()), None),
        "cameras": cameras,
        "state_dim": state_shape[0] if state_shape else None,
        "action_dim": action_shape[0] if action_shape else None,
        "state_key": "observation.state",
        "action_key": "action",
        "warnings": warnings,
        "files": [str(p) for p in files[:20]],
    }


def _decode_video(path: Path, limit: int) -> list[np.ndarray]:
    import av

    frames: list[np.ndarray] = []
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        for frame in container.decode(stream):
            frames.append(to_rgb_uint8(frame.to_ndarray(format="rgb24")))
            if len(frames) >= limit:
                break
    return frames


def _video_path_for(root: Path, df: Any, key: str, episode_index: int) -> Path | None:
    if key in df.columns and len(df):
        cell = df[key].iloc[0]
        if isinstance(cell, str) and cell:
            candidate = root / cell
            if candidate.is_file():
                return candidate
    for suffix in (".mp4", ".mkv", ".webm"):
        hits = sorted(root.glob(f"videos/chunk-*/{key}/episode_{episode_index:06d}{suffix}"))
        if hits:
            return hits[0]
    return None


def iter_episodes(
    path: str | Path,
    mapping_state_key: str | None = None,
    mapping_action_key: str | None = None,
) -> Iterator[Episode]:
    import pandas as pd

    root = Path(path).expanduser()
    info = _load_json(root / "meta" / "info.json")
    tasks = _tasks(root)
    fps = info.get("fps")
    image_keys = _image_keys(info)
    files = sorted(root.glob("data/chunk-*/*.parquet"), key=lambda p: natural_key(p.name))
    if not files:
        raise FileNotFoundError(f"{root} 下没有 data/chunk-*/*.parquet")
    state_key = mapping_state_key or "observation.state"
    action_key = mapping_action_key or "action"
    for index, file in enumerate(files):
        df = pd.read_parquet(file)
        if "frame_index" in df.columns:
            df = df.sort_values("frame_index").reset_index(drop=True)
        if state_key not in df.columns or action_key not in df.columns:
            raise KeyError(f"{file.name}: 缺少 {state_key} 或 {action_key} 列")
        state = np.stack(df[state_key].to_numpy()).astype(np.float32)
        action = np.stack(df[action_key].to_numpy()).astype(np.float32)
        length = int(min(len(state), len(action)))
        images: dict[str, list[np.ndarray]] = {}
        for key in image_keys:
            video = _video_path_for(root, df, key, index)
            if video is None:
                raise FileNotFoundError(f"LeRobot v2 视频缺失：{key} episode {index}（{root}）")
            frames = _decode_video(video, length)
            images[sanitize_name(key.split(".")[-1])] = frames[:length]
        task = ""
        if "task_index" in df.columns and len(df):
            task = tasks.get(int(df["task_index"].iloc[0]), "")
        yield Episode(
            index=index,
            state=state[:length],
            action=action[:length],
            images=images,
            task=task,
            fps=fps,
        ).cropped()