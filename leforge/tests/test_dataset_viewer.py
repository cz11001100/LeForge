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
"""Tests for the local dataset viewer helpers and sim-eval plumbing."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest


def _make_v3_dataset(root: Path, repo_id: str) -> Path:
    d = root / repo_id
    (d / "meta").mkdir(parents=True)
    (d / "data" / "chunk-000").mkdir(parents=True)
    (d / "videos" / "observation.images.UP" / "chunk-000").mkdir(parents=True)
    info = {
        "codebase_version": "v3.0",
        "fps": 30,
        "features": {
            "action": {"dtype": "float32", "shape": [2], "names": ["j0.pos", "j1.pos"]},
            "observation.state": {"dtype": "float32", "shape": [2]},
            "observation.images.UP": {"dtype": "video", "shape": [480, 640, 3]},
        },
    }
    (d / "meta" / "info.json").write_text(json.dumps(info))
    episodes = [
        {
            "episode_index": 0,
            "tasks": ["grasp the ball"],
            "length": 4,
            "data/chunk_index": 0,
            "data/file_index": 0,
            "videos/observation.images.UP/chunk_index": 0,
            "videos/observation.images.UP/file_index": 0,
            "videos/observation.images.UP/from_timestamp": 0.0,
            "videos/observation.images.UP/to_timestamp": 4 / 30,
        },
        {
            "episode_index": 1,
            "tasks": ["grasp the ball"],
            "length": 2,
            "data/chunk_index": 0,
            "data/file_index": 0,
            "videos/observation.images.UP/chunk_index": 0,
            "videos/observation.images.UP/file_index": 0,
            "videos/observation.images.UP/from_timestamp": 4 / 30,
            "videos/observation.images.UP/to_timestamp": 6 / 30,
        },
    ]
    (d / "meta" / "episodes.jsonl").write_text("\n".join(json.dumps(e) for e in episodes))
    rows = []
    for ep, length in ((0, 4), (1, 2)):
        for fr in range(length):
            rows.append(
                {
                    "episode_index": ep,
                    "frame_index": fr,
                    "action": [float(ep + fr), float(fr)],
                    "observation.state": [float(fr), float(ep)],
                }
            )
    pd.DataFrame(rows).to_parquet(d / "data" / "chunk-000" / "file-000.parquet")
    (d / "videos" / "observation.images.UP" / "chunk-000" / "file-000.mp4").write_bytes(b"")
    return d


def test_dataset_episodes_plain_json(tmp_lerobot_home: Path) -> None:
    from leforge.datasets import dataset_episodes

    _make_v3_dataset(tmp_lerobot_home, "user/ds")
    out = dataset_episodes("user/ds")
    assert out["fps"] == 30.0
    assert out["cameras"] == ["observation.images.UP"]
    assert [e["episode_index"] for e in out["episodes"]] == [0, 1]
    assert out["episodes"][0]["tasks"] == ["grasp the ball"]
    json.dumps(out)


def test_dataset_video_window(tmp_lerobot_home: Path) -> None:
    from leforge.datasets import dataset_video_info

    _make_v3_dataset(tmp_lerobot_home, "user/ds")
    info = dataset_video_info("user/ds", 1, "observation.images.UP")
    assert info["path"].name == "file-000.mp4"
    assert info["from_timestamp"] == pytest.approx(4 / 30)
    assert info["to_timestamp"] == pytest.approx(6 / 30)
    with pytest.raises(FileNotFoundError):
        dataset_video_info("user/ds", 99, "observation.images.UP")
    with pytest.raises(FileNotFoundError):
        dataset_video_info("user/ds", 0, "observation.images.NOPE")


def test_dataset_series_json_serializable(tmp_lerobot_home: Path) -> None:
    from leforge.datasets import dataset_episode_series

    _make_v3_dataset(tmp_lerobot_home, "user/ds")
    out = dataset_episode_series("user/ds", 0, max_points=10)
    assert out["joint_names"] == ["j0", "j1"]
    assert out["frames"] == [0, 1, 2, 3]
    assert out["action"][3] == [3.0, 3.0]
    assert out["state"][0] == [0.0, 0.0]
    json.dumps(out)


def test_dataset_root_traversal_rejected(tmp_lerobot_home: Path) -> None:
    from leforge.datasets import dataset_episodes

    _make_v3_dataset(tmp_lerobot_home, "user/ds")
    with pytest.raises(FileNotFoundError):
        dataset_episodes("../ds")


def test_sim_eval_camera_aliases(tmp_path: Path) -> None:
    from leforge.sim_eval import _make_env_kwargs

    ckpt = tmp_path / "model"
    ckpt.mkdir()
    (ckpt / "config.json").write_text(
        json.dumps(
            {
                "input_features": {
                    "observation.state": {},
                    "observation.images.side": {},
                    "observation.images.up": {},
                    "observation.images.wrist": {},
                }
            }
        )
    )
    kwargs = _make_env_kwargs(str(ckpt), "lerobot/so101-tabletop-mujoco")
    assert kwargs == {"cameras": {"up": "top", "side": "front", "wrist": "wrist_cam"}}
    assert list(kwargs["cameras"]) == ["up", "side", "wrist"]
    # Other env repos get no tabletop-specific mapping.
    assert _make_env_kwargs(str(ckpt), "someone/other-env") == {}


def test_sim_eval_unknown_camera_rejected(tmp_path: Path) -> None:
    from leforge.sim_eval import _make_env_kwargs

    ckpt = tmp_path / "model"
    ckpt.mkdir()
    (ckpt / "config.json").write_text(
        json.dumps({"input_features": {"observation.images.ceiling": {}}})
    )
    with pytest.raises(ValueError, match="ceiling"):
        _make_env_kwargs(str(ckpt), "lerobot/so101-tabletop-mujoco")


def test_sim_eval_parse_progress(tmp_path: Path) -> None:
    from leforge.sim_eval import parse_progress

    log = tmp_path / "log.txt"
    log.write_text(
        "Running rollout with at most 600 steps:  40%|███| 240/600 [00:04<00:06, 59.9it/s]\r"
        "Running rollout with at most 600 steps:  65%|█████| 390/600 [00:06<00:03, 60.1it/s]"
    )
    assert parse_progress(log) == {"batches_done": 390, "batches_total": 600}
    assert parse_progress(tmp_path / "missing.txt") is None


def _checkpoint(tmp_path: Path, policy_type: str) -> str:
    checkpoint = tmp_path / policy_type
    checkpoint.mkdir()
    (checkpoint / "config.json").write_text(json.dumps({"type": policy_type}))
    return str(checkpoint)


def test_sim_eval_act_defaults_to_twenty_step_replan(tmp_path: Path) -> None:
    from leforge.sim_eval import _append_action_replay_flags

    cmd: list[str] = []
    steps, note = _append_action_replay_flags(cmd, _checkpoint(tmp_path, "act"), 20, None)
    assert steps == 20
    assert note == ""
    assert cmd == ["--policy.n_action_steps=20"]


def test_sim_eval_act_replan_never_lengthens_checkpoint_queue(tmp_path: Path) -> None:
    from leforge.sim_eval import _append_action_replay_flags

    checkpoint = Path(_checkpoint(tmp_path, "act"))
    (checkpoint / "config.json").write_text(json.dumps({"type": "act", "n_action_steps": 5}))
    cmd: list[str] = []
    steps, note = _append_action_replay_flags(cmd, str(checkpoint), 20, None)
    assert steps == 5
    assert note == ""
    assert cmd == ["--policy.n_action_steps=5"]


def test_sim_eval_act_temporal_ensemble_forces_single_step(tmp_path: Path, monkeypatch) -> None:
    from leforge import sim_eval

    monkeypatch.setattr(sim_eval, "policy_supports_temporal_ensemble", lambda _path: True)
    cmd: list[str] = []
    steps, note = sim_eval._append_action_replay_flags(cmd, _checkpoint(tmp_path, "act"), 20, 0.01)
    assert steps == 1
    assert note == ""
    assert cmd == ["--policy.temporal_ensemble_coeff=0.01", "--policy.n_action_steps=1"]


def test_sim_eval_non_act_keeps_native_replay(tmp_path: Path) -> None:
    from leforge.sim_eval import _append_action_replay_flags

    cmd: list[str] = []
    steps, note = _append_action_replay_flags(cmd, _checkpoint(tmp_path, "tdmpc"), 20, None)
    assert steps == 20
    assert note == ""
    assert cmd == []


def test_sim_eval_grasp_assist_is_labeled_and_not_rankable(tmp_path: Path, monkeypatch) -> None:
    from leforge import sim_eval

    checkpoint = _checkpoint(tmp_path, "act")
    run_dir = tmp_path / "job" / "sim_eval" / "run"
    captured: list[str] = []

    class FakeProc:
        pid = 123
        returncode = 0

        def poll(self):
            return 0

    def fake_popen(cmd, **kwargs):
        captured.extend(cmd)
        cwd = Path(kwargs["cwd"])
        (cwd / "eval_info.json").write_text(
            json.dumps(
                {
                    "overall": {"pc_success": 100.0, "n_episodes": 1, "n_success": 1},
                    "per_task": [
                        {
                            "metrics": {
                                "env_metrics": [
                                    {
                                        "collisions": 0.0,
                                        "limit_violations": 0.0,
                                        "cycle_steps": 2.0,
                                        "gripper_ball_min_distance_m": -0.001,
                                        "gripper_ball_contact_steps": 2.0,
                                        "gripper_closing_contact_steps": 1.0,
                                        "gripper_ball_first_contact_step": 1.0,
                                        "gripper_ball_max_force_n": 3.0,
                                        "gripper_action_min": 0.0,
                                        "max_lift_m": 0.06,
                                        "grasp_assist_used": 1.0,
                                        "grasp_assist_attached": 1.0,
                                        "grasp_assist_steps": 1.0,
                                        "grasp_assist_attach_step": 1.0,
                                    }
                                ]
                            }
                        }
                    ],
                }
            )
        )
        return FakeProc()

    monkeypatch.setattr(sim_eval.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(sim_eval, "diagnose_recordings", lambda *_args: {})
    result = sim_eval.run_sim_eval(
        checkpoint_path=checkpoint,
        run_dir=str(run_dir),
        env_hub_path=str(tmp_path / "so101-tabletop-mujoco"),
        n_episodes=1,
        max_episode_steps=2,
        grasp_assist=True,
    )
    assert "--policy.n_action_steps=20" in captured
    env_arg = next(arg for arg in captured if arg.startswith("--env.make_env_kwargs="))
    assert json.loads(env_arg.split("=", 1)[1])["grasp_assist"] is True
    assert result["grasp_assist"] is True
    assert result["ranking_eligible"] is False
    assert result["grasp_summary"]["lifted"] == 1
