# Copyright 2025 The HuggingFace Inc. team. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Augmentation preview: apply the training image transforms to sample frames.

Uses the same transform configs as the training command (``augmentation_tfs``)
and lerobot's own ``ImageTransforms``, so what the operator sees is what the
dataloader will draw.
"""

from __future__ import annotations

import base64
import io
import logging

logger = logging.getLogger(__name__)


def _to_b64_jpeg(frame) -> str:
    from torchvision.transforms import ToPILImage

    img = ToPILImage()(frame.clamp(0, 1).cpu())
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=88)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _open_dataset(repo_id: str):
    """Open a local dataset; a Hub id (not cached) downloads via snapshot_download.

    The raw hub 404 is noisy and does not say what to do — turn "repo not
    found / private without access" into one actionable sentence.
    """
    from huggingface_hub.errors import RepositoryNotFoundError
    from lerobot.datasets import LeRobotDataset

    from .train import _resolve_video_backend

    repo_id = repo_id.strip()
    try:
        return LeRobotDataset(repo_id, video_backend=_resolve_video_backend(None))
    except RepositoryNotFoundError as exc:
        raise ValueError(
            f"Hub 上找不到数据集 {repo_id}：检查 ID 拼写，"
            "或该私有仓库需要用当前 HF 账号授权"
        ) from exc


def _diff_stats(orig, aug) -> dict:
    """Mean / max absolute change on the 0-255 scale — the honest strength number."""
    d = (aug - orig).abs().mean(0) * 255.0
    return {"mean": round(float(d.mean()), 1), "max": round(float(d.max()), 1)}


def _diff_b64(orig, aug, gain: int = 8) -> str:
    """Amplified difference map (amber on black) so subtle transforms are visible."""
    from PIL import Image

    d = ((aug - orig).abs().mean(0) * gain).clamp(0, 1).cpu().numpy()
    h, w = d.shape
    rgb = (d * 255.0).astype("uint8")[:, :, None] * [1.0, 0.67, 0.16]
    img = Image.fromarray(rgb.clip(0, 255).astype("uint8"), mode="RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def preview_augmentations(*, repo_id: str, request, n_frames: int = 3) -> dict:
    """Return original/augmented frame pairs from a local dataset.

    ``request`` carries the same augmentation_* fields as TrainingRequest.
    Frames are spread across the dataset so the preview is not one episode's
    first second.
    """
    from lerobot.transforms import ImageTransformConfig, ImageTransforms, ImageTransformsConfig

    from .train import augmentation_tfs

    tfs = augmentation_tfs(request)
    if not tfs:
        return {
            "camera": "",
            "original": [],
            "augmented": [],
            "pair_diffs": [],
            "transforms": [],
            "per_transform": [],
        }

    cfg = ImageTransformsConfig(
        enable=True,
        max_num_transforms=request.augmentation_max_num_transforms,
        random_order=request.augmentation_random_order,
        tfs={name: ImageTransformConfig(**spec) for name, spec in tfs.items()},
    )
    tf = ImageTransforms(cfg)
    dataset = _open_dataset(repo_id)
    camera = dataset.meta.camera_keys[0]
    n = len(dataset)
    count = max(1, min(n_frames, n))
    indices = sorted({round(i * (n - 1) / max(1, count - 1)) for i in range(count)})

    original, augmented, pair_diffs = [], [], []
    for i in indices:
        frame = dataset[i][camera]
        out = tf(frame)
        original.append(_to_b64_jpeg(frame))
        augmented.append(_to_b64_jpeg(out))
        pair_diffs.append(_diff_stats(frame, out))

    # One example per transform at its strongest setting, on the same reference
    # frame — a random combined draw can look subtle, this never does. The diff
    # map makes even near-invisible transforms (sharpness, hue) measurable.
    reference = dataset[indices[0]][camera]
    per_transform = []
    for name, spec in tfs.items():
        max_kwargs = {k: [v[1], v[1]] for k, v in spec["kwargs"].items()}
        single = ImageTransforms(
            ImageTransformsConfig(
                enable=True,
                max_num_transforms=1,
                tfs={
                    name: ImageTransformConfig(
                        weight=1.0, type=spec["type"], kwargs=max_kwargs
                    )
                },
            )
        )
        out = single(reference)
        per_transform.append(
            {
                "name": name,
                "image": _to_b64_jpeg(out),
                "diff": _diff_stats(reference, out),
                "diff_image": _diff_b64(reference, out),
            }
        )

    return {
        "camera": camera,
        "original": original,
        "augmented": augmented,
        "pair_diffs": pair_diffs,
        "transforms": list(tfs.keys()),
        "per_transform": per_transform,
    }