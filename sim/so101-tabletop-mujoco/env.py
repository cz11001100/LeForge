# Copyright 2026 The HuggingFace Inc. team. All rights reserved.
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

"""EnvHub environment: an SO-101 arm grasping a red or blue ball on a MuJoCo tabletop.

The arm is MuJoCo Menagerie's ``robotstudio_so101`` (bundled in this repository, Apache-2.0),
attached at the scene's ``so101_mount`` site. Objects, lights, cameras and physics options live in
``so101_tabletop.xml``. Each reset restores the XML state and applies seeded offsets (``randomize``).

State and actions use the units of LeRobot's ``so101_follower`` with ``use_degrees=True``: degrees
for the arm joints and 0-100 for the gripper. Actions are absolute joint position targets at 30 fps.
The task is ``grasp the red ball`` or ``grasp the blue ball``: reward is 1.0 when the target ball's
center rises 5 cm above its reset height, the episode terminates on success and is truncated after
``episode_length`` steps. A static 10 cm plate sits on the table as a distractor.
"""

import copy
import json
import xml.etree.ElementTree as ET  # nosec B405
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

import gymnasium as gym
import mujoco
import numpy as np
from gymnasium import spaces

REPO_ID = "lerobot/so101-tabletop-mujoco"
# Not resolved: in the Hugging Face cache, repository files are symlinks into blobs/ named by hash.
HERE = Path(__file__).absolute().parent
# Bundled from MuJoCo Menagerie at commit 0059d4335f8156206f63a35662313385f7ad6d74.
MENAGERIE_MODEL = "robotstudio_so101"
SCENE_FILE = "so101_tabletop.xml"
MOUNT_SITE = "so101_mount"
INSTRUCTION_TEXT = "instruction"
# The real 1021_8 arm is white; the motors stay dark.
ARM_COLOR = (0.90, 0.90, 0.88)

JOINTS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
# Robot bodies that a collision metric should count (anything but the balls).
ROBOT_BODIES = (
    "base", "shoulder", "upper_arm", "lower_arm", "wrist", "gripper",
    "moving_jaw_so101_v1", "camera_mount",
)
# Median first-frame joint pose of CZ11001100/1021_8 (degrees, gripper 0-100).
HOME = (-1.98, -103.43, 91.21, 71.16, -0.97, 37.55)
JOINT_NAMES = [f"{joint}.pos" for joint in JOINTS]

# How LeRobot describes this environment, locally and when served.
LEROBOT_SIM = {
    "fps": 30,
    "control_mode": "position",
    "semantics": "so101-joint-degrees-v1",
    "state_names": JOINT_NAMES,
    "action_names": JOINT_NAMES,
    "robot_type": "so_follower",
}
BALL_BODIES = ("red_ball", "blue_ball")
TARGET_BALLS = {
    "grasp the red ball": "red_ball",
    "grasp the blue ball": "blue_ball",
}
# A ball counts as grasped once its center rises this far above its reset height.
LIFT_SUCCESS = 0.05
# Opt-in grasp-assist thresholds in real-robot gripper units (0=closed, 100=open).
GRASP_ASSIST_DISTANCE = 0.026
GRASP_ASSIST_RELEASE = 60.0
GRASP_ASSIST_LIFT_DEG = 10.0
# User frame: x=0 at the base right edge, y=0 at the base front edge, +x right,
# +y forward. MuJoCo: X = y + BASE_FRONT_X, Y = -x + BASE_RIGHT_Y.
BASE_FRONT_X = 0.083
BASE_RIGHT_Y = -0.0555
BALL_RADIUS = 0.02


def user_cm_to_mj(x_cm: float, y_cm: float) -> tuple[float, float]:
    """Convert the user's tabletop frame (cm) to MuJoCo world X/Y (m)."""
    return y_cm / 100.0 + BASE_FRONT_X, -x_cm / 100.0 + BASE_RIGHT_Y


def mj_to_user_cm(x_mj: float, y_mj: float) -> tuple[float, float]:
    """Convert MuJoCo world X/Y (m) back to the user's tabletop frame (cm)."""
    return -(y_mj - BASE_RIGHT_Y) * 100.0, (x_mj - BASE_FRONT_X) * 100.0


def repo_root() -> Path:
    """Directory holding the scene and the arm model.

    LeRobot's in-process loader downloads ``env.py`` alone, into ``snapshots/<commit>/`` of the Hub
    cache; fetch the rest of that same commit. A local checkout or a full snapshot needs nothing.
    """
    if (HERE / SCENE_FILE).is_file():
        return HERE
    from huggingface_hub import snapshot_download

    revision = HERE.name if HERE.parent.name == "snapshots" else None
    return Path(snapshot_download(REPO_ID, revision=revision))


def build_model(scene: Path, root: Path) -> mujoco.MjModel:
    """Compile the scene with the Menagerie arm attached at its mount site."""
    spec = mujoco.MjSpec.from_file(str(scene))
    arm = mujoco.MjSpec.from_file(str(root / MENAGERIE_MODEL / "so101.xml"))
    for material in arm.materials:
        if not material.name.startswith("sts3215"):
            material.rgba = [*ARM_COLOR, 1.0]
    # Attaching drops the arm's tuned physics options; keep them unless the scene sets its own.
    if ET.parse(scene).getroot().find("option") is None:  # nosec B314
        for name in dir(arm.option):
            if not name.startswith("_"):
                setattr(spec.option, name, getattr(arm.option, name))
    if spec.site(MOUNT_SITE) is not None:
        spec.attach(arm, site=MOUNT_SITE, prefix="")
    else:
        spec.attach(arm, frame=spec.worldbody.add_frame(), prefix="")
    return spec.compile()


LAYOUT_FILE = "layout.json"


def load_layout(scene: Path | None) -> dict[str, Any]:
    """Read the per-scene ``layout.json`` (cameras, ball size, HOME, joint offsets, workspace).

    Keeping the real-world numbers in JSON means a changed room only needs a re-calibration
    (see ``calibrate_layout.py``) instead of editing this module or the MJCF. Missing file
    falls back to the constants and XML in this directory.
    """
    if scene is None:
        return {}
    path = Path(scene).parent / LAYOUT_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


@dataclass
class _BodyNoise:
    """Seeded offsets around one body's XML pose: free bodies move through qpos, static ones directly."""

    body: int
    qadr: int | None
    pos_range: np.ndarray
    yaw_range: float
    footprint: float


def _vector(cfg: Mapping, key: str) -> np.ndarray:
    value = np.asarray(cfg.get(key, (0.0, 0.0, 0.0)), dtype=np.float64)
    if value.shape != (3,):
        raise ValueError(f"randomize {key!r} must be three half-ranges (x, y, z), got {value.tolist()}")
    return value


class _World:
    """Compiled model, physics state, renderer and reset randomization of one SO-101 world."""

    def __init__(
        self,
        scene: Path,
        root: Path,
        fps: int,
        height: int,
        width: int,
        randomize: Mapping,
        camera_fovy: Mapping[str, float],
    ):
        self.layout = load_layout(scene)
        self.camera_hflip: dict[str, bool] = {}
        self.model = build_model(scene, root)
        # Layout values default to the MJCF/constants until _apply_layout runs below.
        self.joint_offsets = np.zeros(len(JOINTS))
        self.ball_radius = BALL_RADIUS
        # The control period must be a whole number of physics steps.
        self.substeps = max(1, round(1 / (fps * self.model.opt.timestep)))
        self.model.opt.timestep = 1 / (fps * self.substeps)
        self.data = mujoco.MjData(self.model)
        self.renderer = mujoco.Renderer(self.model, height, width)
        self.qadr = np.array([self.model.joint(name).qposadr[0] for name in JOINTS])
        self.ball_bodies = {
            name: self._id(mujoco.mjtObj.mjOBJ_BODY, name, "the task") for name in BALL_BODIES
        }
        self.actuators = np.array([self.model.actuator(name).id for name in JOINTS])
        self._apply_layout()
        self.lo, self.hi = self.model.actuator_ctrlrange[self.actuators].T.copy()
        text = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_TEXT, INSTRUCTION_TEXT)
        self.instruction = ""
        if text >= 0:
            start, size = self.model.text_adr[text], self.model.text_size[text]
            self.instruction = self.model.text_data[start : start + size - 1].decode()

        unknown = set(randomize) - {
            "joints",
            "bodies",
            "cameras",
            "ball_workspace",
            "ball_keepouts",
            "ball_spacing",
            "lighting",
            "materials",
            "ball_physics",
            "camera_noise",
        }
        if unknown:
            raise ValueError(f"Unknown randomize keys {sorted(unknown)}; expected joints, bodies, cameras, ball_*")
        self.joint_noise = float(randomize.get("joints", 0.0))
        self.ball_workspace = randomize.get("ball_workspace")
        self.ball_keepouts = list(randomize.get("ball_keepouts") or [])
        self.ball_spacing = float(randomize.get("ball_spacing", 0.06))
        self.bodies = [self._body_noise(name, cfg) for name, cfg in (randomize.get("bodies") or {}).items()]
        self.cameras = {
            self._id(mujoco.mjtObj.mjOBJ_CAMERA, name, "randomize.cameras"): _vector(cfg, "pos")
            for name, cfg in (randomize.get("cameras") or {}).items()
        }
        for name, fovy in camera_fovy.items():
            self.model.cam_fovy[self._id(mujoco.mjtObj.mjOBJ_CAMERA, name, "camera_fovy")] = fovy
        # Opt-in domain randomization groups (all default to off).
        self.lighting = dict(randomize.get("lighting") or {})
        self.materials = dict(randomize.get("materials") or {})
        self.ball_physics = dict(randomize.get("ball_physics") or {})
        self.camera_noise = dict(randomize.get("camera_noise") or {})
        self.headlight_ambient0 = self.model.vis.headlight.ambient.copy()
        self.headlight_diffuse0 = self.model.vis.headlight.diffuse.copy()
        self.light_diffuse0 = self.model.light_diffuse.copy()
        self.material_ids = {
            name: mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_MATERIAL, name)
            for name in self.materials
        }
        for name, mid in self.material_ids.items():
            if mid < 0:
                raise ValueError(f"Unknown material {name!r} in randomize.materials")
        self.mat_rgba0 = self.model.mat_rgba.copy()
        self.mass0 = self.model.body_mass.copy()
        self.friction0 = self.model.geom_friction.copy()
        self.ball_geoms = [
            g for g in range(self.model.ngeom) if self.model.geom_bodyid[g] in set(self.ball_bodies.values())
        ]
        self._cam_gain = 1.0
        self._cam_sigma = 0.0
        self._noise_rng = np.random.default_rng(0)
        self.body_pos0 = self.model.body_pos.copy()
        self.body_quat0 = self.model.body_quat.copy()
        self.cam_pos0 = self.model.cam_pos.copy()
        randomized = {noise.body for noise in self.bodies}
        # Free bodies left at their XML pose are still obstacles for the randomized ones.
        self.fixed_free = [
            body
            for body in range(1, self.model.nbody)
            if self._free_qadr(body) is not None and body not in randomized
        ]

    def _apply_layout(self) -> None:
        """Apply layout.json on top of the compiled model (cameras, balls, limits, offsets)."""
        layout = self.layout or {}
        model = self.model
        offsets = (layout.get("arm") or {}).get("joint_offsets_deg") or (0.0,) * len(JOINTS)
        self.joint_offsets = np.asarray(offsets, dtype=np.float64)[: len(JOINTS)]
        if self.joint_offsets.shape != (len(JOINTS),):
            raise ValueError(f"layout arm.joint_offsets_deg needs {len(JOINTS)} values, got {offsets}")
        balls = layout.get("balls") or {}
        if "radius_cm" in balls:
            self.ball_radius = float(balls["radius_cm"]) / 100.0
        self.camera_hflip = {}
        for name, cfg in (layout.get("cameras") or {}).items():
            camera = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_CAMERA, name)
            if camera < 0:
                continue
            self.camera_hflip[name] = bool(cfg.get("hflip", False))
            if "pos" in cfg:
                model.cam_pos[camera] = cfg["pos"]
            if "quat" in cfg:
                model.cam_quat[camera] = cfg["quat"]
            if "fovy" in cfg:
                model.cam_fovy[camera] = float(cfg["fovy"])
        if balls:
            mass = float(balls.get("mass_kg") or 0.0)
            for body in self.ball_bodies.values():
                for geom in np.flatnonzero(model.geom_bodyid == body):
                    model.geom_size[geom, 0] = self.ball_radius
                if mass > 0:
                    model.body_mass[body] = mass
                qadr = self._free_qadr(body)
                if qadr is not None:
                    model.qpos0[qadr + 2] = self.ball_radius
        for joint, (low, high) in ((layout.get("arm") or {}).get("limits_deg") or {}).items():
            if joint not in JOINTS[:5]:
                continue  # the gripper is 0-100, not radians; its range stays in the MJCF
            jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, joint)
            aid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, joint)
            if jid >= 0:
                model.jnt_range[jid] = np.radians([low, high])
            if aid >= 0:
                model.actuator_ctrlrange[aid] = np.radians([low, high])

    def _id(self, kind: mujoco.mjtObj, name: str, section: str) -> int:
        index = mujoco.mj_name2id(self.model, kind, name)
        if index < 0:
            raise ValueError(f"{section} names {name!r}, which this scene does not define")
        return index

    def _free_qadr(self, body: int) -> int | None:
        model = self.model
        if (
            model.body_jntnum[body] == 1
            and model.jnt_type[model.body_jntadr[body]] == mujoco.mjtJoint.mjJNT_FREE
        ):
            return int(model.jnt_qposadr[model.body_jntadr[body]])
        return None

    def _body_noise(self, name: str, cfg: Mapping) -> _BodyNoise:
        unknown = set(cfg) - {"pos", "yaw"}
        if unknown:
            raise ValueError(f"Unknown randomize keys {sorted(unknown)} for body {name!r}; expected pos, yaw")
        body = self._id(mujoco.mjtObj.mjOBJ_BODY, name, "randomize.bodies")
        qadr = self._free_qadr(body)
        if qadr is None and (self.model.body_jntnum[body] or self.model.body_parentid[body] != 0):
            raise ValueError(
                f"Randomized body {name!r} must have a freejoint or be a static child of the world"
            )
        return _BodyNoise(body, qadr, _vector(cfg, "pos"), float(cfg.get("yaw", 0.0)), self._footprint(body))

    def _footprint(self, body: int) -> float:
        """Radius of the body's footprint on the table, from its geoms' bounding boxes."""
        radius = 0.0
        for geom in np.flatnonzero(self.model.geom_bodyid == body):
            center, half = self.model.geom_aabb[geom, :3], self.model.geom_aabb[geom, 3:]
            corner = np.abs(self.model.geom_pos[geom, :2] + center[:2]) + half[:2]
            radius = max(radius, float(np.linalg.norm(corner)))
        return radius

    def _xy(self, body: int) -> np.ndarray:
        qadr = self._free_qadr(body)
        return self.data.qpos[qadr : qadr + 2] if qadr is not None else self.model.body_pos[body, :2]

    def _randomize_balls(self, rng: np.random.Generator) -> None:
        """Place red/blue balls in the user-frame workspace with rejection sampling.

        Rejects poses inside configured keep-out rectangles (plate, stand bases)
        and poses closer than ``ball_spacing`` to an already placed ball.
        """
        if not self.ball_workspace:
            return

        x0, x1 = sorted(self.ball_workspace["x"])
        y0, y1 = sorted(self.ball_workspace["y"])
        placed: list[tuple[float, float]] = []
        for name in BALL_BODIES:
            body = self.ball_bodies[name]
            qadr = self._free_qadr(body)
            if qadr is None:
                raise ValueError(f"Ball {name!r} must have a freejoint")
            for _ in range(300):
                x_cm = rng.uniform(x0, x1)
                y_cm = rng.uniform(y0, y1)

                blocked = False
                for keep in self.ball_keepouts:
                    kx0, kx1 = sorted(keep["x"])
                    ky0, ky1 = sorted(keep["y"])
                    margin = float(keep.get("margin", 0.0))
                    if kx0 - margin <= x_cm <= kx1 + margin and ky0 - margin <= y_cm <= ky1 + margin:
                        blocked = True
                        break
                if blocked:
                    continue

                x_mj, y_mj = user_cm_to_mj(x_cm, y_cm)
                if any(
                    (x_mj - px) ** 2 + (y_mj - py) ** 2 < self.ball_spacing**2
                    for px, py in placed
                ):
                    continue

                self.data.qpos[qadr : qadr + 3] = [x_mj, y_mj, self.ball_radius]
                self.data.qpos[qadr + 3 : qadr + 7] = [1.0, 0.0, 0.0, 0.0]
                placed.append((x_mj, y_mj))
                break
            else:
                raise ValueError(
                    f"Could not place ball {name!r} in workspace {self.ball_workspace} "
                    f"without hitting a keep-out or another ball"
                )

    def reset(self, rng: np.random.Generator, initial_joints: np.ndarray) -> None:
        """Restore the XML state, then apply seeded joint, body, camera and ball offsets."""
        model, data = self.model, self.data
        model.body_pos[:], model.body_quat[:], model.cam_pos[:] = (
            self.body_pos0,
            self.body_quat0,
            self.cam_pos0,
        )
        mujoco.mj_resetData(model, data)
        joints = initial_joints + rng.uniform(-self.joint_noise, self.joint_noise, len(JOINTS))
        data.qpos[self.qadr] = self.to_ctrl(joints)
        data.ctrl[self.actuators] = data.qpos[self.qadr]

        placed = [(self._xy(body).copy(), self._footprint(body)) for body in self.fixed_free]
        for noise in self.bodies:
            for _ in range(100):
                self._place(noise, rng)
                xy = self._xy(noise.body).copy()
                if all(np.linalg.norm(xy - other) > noise.footprint + radius for other, radius in placed):
                    break
            else:
                raise ValueError(f"Could not place body {model.body(noise.body).name!r} without overlap")
            placed.append((xy, noise.footprint))
        for camera, pos_range in self.cameras.items():
            model.cam_pos[camera] = self.cam_pos0[camera] + rng.uniform(-pos_range, pos_range)
        self._randomize_balls(rng)
        self._randomize_appearance(rng)
        mujoco.mj_forward(model, data)

    def _place(self, noise: _BodyNoise, rng: np.random.Generator) -> None:
        offset = rng.uniform(-noise.pos_range, noise.pos_range)
        yaw = rng.uniform(-noise.yaw_range, noise.yaw_range)
        turn = np.array([np.cos(yaw / 2), 0.0, 0.0, np.sin(yaw / 2)])
        if noise.qadr is not None:
            a = noise.qadr
            self.data.qpos[a : a + 3] = self.model.qpos0[a : a + 3] + offset
            mujoco.mju_mulQuat(self.data.qpos[a + 3 : a + 7], turn, self.model.qpos0[a + 3 : a + 7])
        else:
            self.model.body_pos[noise.body] = self.body_pos0[noise.body] + offset
            mujoco.mju_mulQuat(self.model.body_quat[noise.body], turn, self.body_quat0[noise.body])

    def to_ctrl(self, values: np.ndarray) -> np.ndarray:
        """Convert real-robot degrees (plus layout joint offsets) and the 0-100 gripper to radians."""
        values = np.asarray(values, dtype=np.float64)
        shifted = values.copy()
        shifted[:5] = shifted[:5] + self.joint_offsets[:5]
        ctrl = np.deg2rad(shifted)
        ctrl[5] = self.lo[5] + values[5] / 100 * (self.hi[5] - self.lo[5])
        return np.clip(ctrl, self.lo, self.hi)

    def joint_state(self) -> np.ndarray:
        """Joint positions in the real-robot units of ``to_ctrl`` (offsets removed)."""
        q = self.data.qpos[self.qadr]
        state = np.rad2deg(q)
        state[:5] = state[:5] - self.joint_offsets[:5]
        state[5] = (q[5] - self.lo[5]) / (self.hi[5] - self.lo[5]) * 100
        return state.astype(np.float32)

    def ball_height(self, name: str) -> float:
        """World-space height of a ball's center, in meters."""
        return float(self.data.xpos[self.ball_bodies[name]][2])

    @staticmethod
    def _sample(rng: np.random.Generator, spec, default=None):
        if spec is None:
            return default
        if isinstance(spec, (int, float)):
            return float(spec)
        lo, hi = float(spec[0]), float(spec[1])
        return float(rng.uniform(lo, hi))

    def _randomize_appearance(self, rng: np.random.Generator) -> None:
        """Lighting, material tint, ball physics and camera noise (all opt-in)."""
        model = self.model
        # Restore baselines so consecutive resets do not compound.
        model.vis.headlight.ambient[:] = self.headlight_ambient0
        model.vis.headlight.diffuse[:] = self.headlight_diffuse0
        model.light_diffuse[:] = self.light_diffuse0
        model.mat_rgba[:] = self.mat_rgba0
        model.body_mass[:] = self.mass0
        model.geom_friction[:] = self.friction0
        self._cam_gain = 1.0
        self._cam_sigma = 0.0
        if self.lighting:
            amb = self._sample(rng, self.lighting.get("ambient"))
            if amb is not None:
                model.vis.headlight.ambient[:] = amb
            dif = self._sample(rng, self.lighting.get("diffuse"))
            if dif is not None:
                model.vis.headlight.diffuse[:] = dif
            key = self._sample(rng, self.lighting.get("light"))
            if key is not None and model.nlight > 1:
                model.light_diffuse[1] = key
        for name, spec in self.materials.items():
            mid = self.material_ids[name]
            if isinstance(spec, (list, tuple)) and isinstance(spec[0], (list, tuple)):
                rgb = [self._sample(rng, channel) for channel in spec]
            else:
                v = self._sample(rng, spec)
                rgb = [v, v, v]
            model.mat_rgba[mid, :3] = rgb
        if self.ball_physics:
            mass_mul = self._sample(rng, self.ball_physics.get("mass"), 1.0)
            if mass_mul and mass_mul > 0 and mass_mul != 1.0:
                for body in self.ball_bodies.values():
                    model.body_mass[body] *= mass_mul
            fric_mul = self._sample(rng, self.ball_physics.get("friction"), 1.0)
            if fric_mul and fric_mul > 0 and fric_mul != 1.0:
                for gid in self.ball_geoms:
                    model.geom_friction[gid] *= fric_mul
        if self.camera_noise:
            self._cam_gain = self._sample(rng, self.camera_noise.get("gain"), 1.0)
            self._cam_sigma = self._sample(rng, self.camera_noise.get("sigma"), 0.0)
            self._noise_rng = np.random.default_rng(int(rng.integers(0, 2**31 - 1)))

    def render(self, camera: str) -> np.ndarray:
        self.renderer.update_scene(self.data, camera=camera)
        img = self.renderer.render().copy()
        if self._cam_gain != 1.0 or self._cam_sigma > 0:
            arr = img.astype(np.float32) * self._cam_gain
            if self._cam_sigma > 0:
                arr += self._noise_rng.normal(0.0, self._cam_sigma * 255.0, arr.shape)
            img = np.clip(arr, 0.0, 255.0).astype(np.uint8)
        if self.camera_hflip.get(camera, False):
            img = img[:, ::-1]
        return img


class SO101Env(gym.Env):
    """SO-101 joint position control in an MJCF scene, observed through the scene's named cameras."""

    metadata = {"render_modes": ["rgb_array"], "render_fps": 30}

    def __init__(
        self,
        scene: str | Path | None = None,
        fps: int = 30,
        episode_length: int = 400,
        observation_height: int = 480,
        observation_width: int = 640,
        cameras: Mapping[str, str] | None = None,
        instruction: str | None = None,
        initial_joints: Sequence[float] | None = None,
        randomize: Mapping[str, Any] | None = None,
        camera_fovy: Mapping[str, float] | None = None,
        action_smooth: float = 0.0,
        grasp_assist: bool = False,
    ):
        super().__init__()
        # None: the repository's tabletop scene, located on first use.
        self.scene = Path(scene) if scene is not None else None
        # Real-world numbers live next to the MJCF so a changed room only needs a new JSON.
        self.layout = load_layout(self.scene or (repo_root() / SCENE_FILE))
        self.task = "so101_tabletop"
        self.fps = fps
        self._max_episode_steps = episode_length
        self._steps = 0
        self.height = observation_height
        self.width = observation_width
        # Observation key -> MJCF camera name.
        self.cameras = dict(cameras or {"up": "top", "side": "front", "wrist": "wrist_cam"})
        self.instruction = instruction or (self.layout.get("task") or {}).get("instruction")
        if initial_joints is None:
            initial_joints = (self.layout.get("arm") or {}).get("home_deg", HOME)
        self.initial_joints = np.asarray(initial_joints, dtype=np.float32)
        if self.initial_joints.shape != (len(JOINTS),):
            raise ValueError(f"initial_joints needs one value per joint {JOINTS}")
        base_randomize = copy.deepcopy(DEFAULTS["randomize"])
        balls = self.layout.get("balls") or {}
        if balls.get("workspace_user_cm"):
            base_randomize["ball_workspace"] = balls["workspace_user_cm"]
        if balls.get("keepouts"):
            base_randomize["ball_keepouts"] = balls["keepouts"]
        if "spacing_m" in balls:
            base_randomize["ball_spacing"] = balls["spacing_m"]
        base_randomize.update(self.layout.get("randomize") or {})
        if randomize is None:
            randomize = base_randomize
        else:
            randomize = {**base_randomize, **randomize}
        self.randomize = dict(randomize)
        # MJCF camera name -> vertical field of view in degrees, e.g. to widen the arm's wrist_cam.
        self.camera_fovy = dict(camera_fovy or {})
        # Exponential low-pass on joint targets (0 = off). Trades a little lag
        # for visibly smoother arm motion; ACT temporal ensembling is the
        # preferred smoother and lives in the policy config.
        self.action_smooth = float(np.clip(action_smooth, 0.0, 0.95))
        # Opt-in kinematic grasp aid for demos and pipeline debugging. It is
        # reported separately and must never be treated as pure-policy success.
        self.grasp_assist = bool(grasp_assist)
        self._smoothed_action: np.ndarray | None = None
        self._world: _World | None = None
        self._target_ball: str | None = None
        self._ball_z0 = 0.0
        self._prev_gripper_action: float | None = None
        self._gripper_ball_min_distance = float("inf")
        self._gripper_ball_contact_steps = 0
        self._gripper_closing_contact_steps = 0
        self._gripper_ball_first_contact_step = 0
        self._gripper_ball_max_force = 0.0
        self._gripper_action_min = float("inf")
        self._gripper_ball_current_distance = float("inf")
        self._grasp_assist_current_distance = float("inf")
        self._max_lift = 0.0
        self._grasp_assist_attached = False
        self._grasp_assist_used = False
        self._grasp_assist_steps = 0
        self._grasp_assist_attach_step = 0
        self._grasp_assist_rel_pos = np.zeros(3, dtype=np.float64)
        self._grasp_assist_rel_quat = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)

        image = spaces.Box(0, 255, (self.height, self.width, 3), np.uint8)
        self.observation_space = spaces.Dict(
            {
                "agent_pos": spaces.Box(-360.0, 360.0, (len(JOINTS),), np.float32),
                "pixels": spaces.Dict(dict.fromkeys(self.cameras, image)),
            }
        )
        self.action_space = spaces.Box(-360.0, 360.0, (len(JOINTS),), np.float32)

    @property
    def task_description(self) -> str:
        """The configured instruction, else the scene's ``<custom><text name="instruction">``."""
        if self.instruction is not None:
            return self.instruction
        return self._ensure_world().instruction

    def _ensure_world(self) -> _World:
        """Build the world on first use, so async workers each own their GL context."""
        if self._world is None:
            root = repo_root()
            self._world = _World(
                self.scene or root / SCENE_FILE,
                root,
                self.fps,
                self.height,
                self.width,
                self.randomize,
                self.camera_fovy,
            )
        return self._world

    def render(self, camera: str | None = None) -> np.ndarray:
        """Render one observation camera, the first one by default."""
        key = camera or next(iter(self.cameras))
        return self._ensure_world().render(self.cameras.get(key, key))

    def _update_metrics(self, world: _World) -> None:
        """Accumulate collision, joint-limit and grasp diagnostics for the eval report."""
        model, data = world.model, world.data
        if getattr(self, "_metric_cache", None) is None:
            robot_bodies = {mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, n) for n in ROBOT_BODIES}
            ball_bodies = set(world.ball_bodies.values())
            self._robot_geoms = {g for g in range(model.ngeom) if model.geom_bodyid[g] in robot_bodies}
            self._ball_geoms = {g for g in range(model.ngeom) if model.geom_bodyid[g] in ball_bodies}
            self._ball_geoms_by_body = {
                name: {g for g in range(model.ngeom) if model.geom_bodyid[g] == body}
                for name, body in world.ball_bodies.items()
            }
            gripper_bodies = {
                mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, n)
                for n in ("gripper", "moving_jaw_so101_v1")
            }
            self._gripper_geoms = {
                g
                for g in range(model.ngeom)
                if model.geom_bodyid[g] in gripper_bodies
                and (model.geom_contype[g] != 0 or model.geom_conaffinity[g] != 0)
            }
            self._grasp_geoms = {
                g
                for g in self._gripper_geoms
                if not (mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_GEOM, g) or "").startswith("camera_")
            }
            self._grasp_site = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_SITE, "gripperframe")
            self._geom_distance_fromto = np.empty((2, 3), dtype=np.float64)
            self._joint_limits = []
            for jname in JOINTS[:5]:
                jid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, jname)
                if jid >= 0 and model.jnt_limited[jid]:
                    self._joint_limits.append(
                        (int(model.jnt_qposadr[jid]), float(model.jnt_range[jid][0]), float(model.jnt_range[jid][1]))
                    )
            self._metric_cache = True
        force = np.zeros(6, dtype=np.float64)
        for ci in range(data.ncon):
            con = data.contact[ci]
            g1, g2 = int(con.geom1), int(con.geom2)
            hit1, hit2 = g1 in self._robot_geoms, g2 in self._robot_geoms
            if not (hit1 or hit2):
                continue
            other = g2 if hit1 else g1
            if other in self._ball_geoms:
                continue  # contacting the balls is the task, not a collision
            mujoco.mj_contactForce(model, data, ci, force)
            if abs(float(force[0])) > 1.0:
                self._collisions += 1
        for adr, lo, hi in self._joint_limits:
            q = float(data.qpos[adr])
            if q - lo < np.radians(2.0) or hi - q < np.radians(2.0):
                self._limit_violations += 1

    def _update_grasp_metrics(self, world: _World, gripper_action: float) -> None:
        """Track target-ball proximity, contact while closing, force and lift."""
        model, data = world.model, world.data
        if getattr(self, "_metric_cache", None) is None:
            self._update_metrics(world)
        ball_geoms = self._ball_geoms_by_body[self._target_ball]
        min_distance = float("inf")
        grasp_distance = float("inf")
        for gripper_geom in self._gripper_geoms:
            for ball_geom in ball_geoms:
                if hasattr(mujoco, "mj_geomDistance"):
                    distance = mujoco.mj_geomDistance(
                        model, data, gripper_geom, ball_geom, 1.0, self._geom_distance_fromto
                    )
                else:
                    distance = float(
                        np.linalg.norm(data.geom_xpos[gripper_geom] - data.geom_xpos[ball_geom])
                        - model.geom_rbound[gripper_geom]
                        - model.geom_rbound[ball_geom]
                    )
                min_distance = min(min_distance, float(distance))
                if gripper_geom in self._grasp_geoms:
                    grasp_distance = min(grasp_distance, float(distance))
        self._gripper_ball_current_distance = min_distance
        self._grasp_assist_current_distance = grasp_distance
        self._gripper_ball_min_distance = min(self._gripper_ball_min_distance, min_distance)
        self._gripper_action_min = min(self._gripper_action_min, float(gripper_action))

        contact_count = 0
        max_force = 0.0
        force = np.zeros(6, dtype=np.float64)
        for ci in range(data.ncon):
            con = data.contact[ci]
            g1, g2 = int(con.geom1), int(con.geom2)
            touches_gripper = (g1 in self._gripper_geoms and g2 in ball_geoms) or (
                g2 in self._gripper_geoms and g1 in ball_geoms
            )
            if not touches_gripper:
                continue
            contact_count += 1
            mujoco.mj_contactForce(model, data, ci, force)
            max_force = max(max_force, abs(float(force[0])))
        closing = self._prev_gripper_action is not None and gripper_action < self._prev_gripper_action - 0.05
        self._prev_gripper_action = float(gripper_action)
        if contact_count:
            self._gripper_ball_contact_steps += 1
            if self._gripper_ball_first_contact_step == 0:
                self._gripper_ball_first_contact_step = self._steps
            if closing:
                self._gripper_closing_contact_steps += 1
        self._gripper_ball_max_force = max(self._gripper_ball_max_force, max_force)

    def _update_grasp_assist(self, world: _World, gripper_action: float) -> None:
        """Optionally keep the target ball fixed between the jaws for demos."""
        if not self.grasp_assist:
            return
        model, data = world.model, world.data
        if self._grasp_site < 0:
            raise RuntimeError("grasp_assist requires the scene's gripperframe site")
        body = world.ball_bodies[self._target_ball]
        qadr = world._free_qadr(body)
        if qadr is None:
            raise RuntimeError(f"Target ball {self._target_ball!r} must have a freejoint")

        if self._grasp_assist_attached:
            if gripper_action > GRASP_ASSIST_RELEASE:
                self._grasp_assist_attached = False
                return
            # Active assist: once the ball is in range, close the real gripper
            # actuator instead of waiting for the policy to notice the contact.
            data.ctrl[world.actuators[5]] = world.lo[5]
            site_pos = data.site_xpos[self._grasp_site]
            site_mat = data.site_xmat[self._grasp_site].reshape(3, 3)
            site_quat = np.empty(4, dtype=np.float64)
            mujoco.mju_mat2Quat(site_quat, site_mat.reshape(9))
            data.qpos[qadr : qadr + 3] = site_pos + site_mat @ self._grasp_assist_rel_pos
            ball_quat = np.empty(4, dtype=np.float64)
            mujoco.mju_mulQuat(ball_quat, site_quat, self._grasp_assist_rel_quat)
            data.qpos[qadr + 3 : qadr + 7] = ball_quat
            data.qvel[qadr : qadr + 6] = 0.0
            self._grasp_assist_steps += 1
            mujoco.mj_forward(model, data)
            return

        if self._grasp_assist_current_distance > GRASP_ASSIST_DISTANCE:
            return
        site_pos = data.site_xpos[self._grasp_site]
        site_mat = data.site_xmat[self._grasp_site].reshape(3, 3)
        site_quat = np.empty(4, dtype=np.float64)
        mujoco.mju_mat2Quat(site_quat, site_mat.reshape(9))
        inv_site_quat = site_quat.copy()
        inv_site_quat[1:] *= -1.0
        self._grasp_assist_rel_pos = site_mat.T @ (data.qpos[qadr : qadr + 3] - site_pos)
        mujoco.mju_mulQuat(
            self._grasp_assist_rel_quat,
            inv_site_quat,
            data.qpos[qadr + 3 : qadr + 7],
        )
        self._grasp_assist_attached = True
        self._grasp_assist_used = True
        self._grasp_assist_attach_step = self._steps
        data.ctrl[world.actuators[5]] = world.lo[5]

    def _obs(self, world: _World) -> dict[str, Any]:
        return {
            "agent_pos": world.joint_state(),
            "pixels": {key: world.render(camera) for key, camera in self.cameras.items()},
        }

    def reset(self, seed: int | None = None, **kwargs) -> tuple[dict[str, Any], dict[str, Any]]:
        """Restore the scene's XML state and apply the seeded randomization."""
        world = self._ensure_world()
        self._smoothed_action = None
        super().reset(seed=seed)
        world.reset(self.np_random, self.initial_joints)

        task = self.instruction if self.instruction is not None else world.instruction
        if task not in TARGET_BALLS:
            raise ValueError(f"Unknown task {task!r}; expected one of {sorted(TARGET_BALLS)}")
        self._target_ball = TARGET_BALLS[task]
        self._ball_z0 = world.ball_height(self._target_ball)
        self._steps = 0
        self._collisions = 0
        self._limit_violations = 0
        self._prev_gripper_action = None
        self._gripper_ball_min_distance = float("inf")
        self._gripper_ball_contact_steps = 0
        self._gripper_closing_contact_steps = 0
        self._gripper_ball_first_contact_step = 0
        self._gripper_ball_max_force = 0.0
        self._gripper_action_min = float("inf")
        self._gripper_ball_current_distance = float("inf")
        self._grasp_assist_current_distance = float("inf")
        self._max_lift = 0.0
        self._grasp_assist_attached = False
        self._grasp_assist_used = False
        self._grasp_assist_steps = 0
        self._grasp_assist_attach_step = 0
        self._grasp_assist_rel_pos = np.zeros(3, dtype=np.float64)
        self._grasp_assist_rel_quat = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float64)
        self._update_grasp_metrics(world, float(self.initial_joints[5]))
        ball_positions_cm = {}
        for name, body in world.ball_bodies.items():
            x_mj, y_mj = world.data.xpos[body][:2]
            x_cm, y_cm = mj_to_user_cm(x_mj, y_mj)
            ball_positions_cm[name] = [round(float(x_cm), 2), round(float(y_cm), 2)]
        return self._obs(world), {
            "is_success": False,
            "lift": 0.0,
            "target_ball": self._target_ball,
            "ball_positions_cm": ball_positions_cm,
        }

    def step(self, action: np.ndarray) -> tuple[dict[str, Any], float, bool, bool, dict[str, Any]]:
        """Hold the joint targets for one control period."""
        if self._target_ball is None:
            raise RuntimeError("Call reset() before step()")
        world = self._ensure_world()
        action = np.asarray(action)
        if action.shape != self.action_space.shape:
            raise ValueError(f"Expected action of shape {self.action_space.shape}, got {action.shape}")
        if self.action_smooth > 0:
            prev = self._smoothed_action if self._smoothed_action is not None else action
            action = self.action_smooth * prev + (1 - self.action_smooth) * action
            self._smoothed_action = action
        policy_gripper = float(action[5])
        if self.grasp_assist and self._grasp_assist_attached:
            # Active demo assist: keep the gripper closed and add a small
            # elbow-flex residual that raises the grasped ball.
            action = action.copy()
            action[2] -= GRASP_ASSIST_LIFT_DEG
            action[5] = 0.0
        world.data.ctrl[world.actuators] = world.to_ctrl(action)
        mujoco.mj_step(world.model, world.data, nstep=world.substeps)
        self._steps += 1
        self._update_metrics(world)
        self._update_grasp_metrics(world, policy_gripper)
        self._update_grasp_assist(world, policy_gripper)
        lift = world.ball_height(self._target_ball) - self._ball_z0
        self._max_lift = max(self._max_lift, float(lift))
        success = lift >= LIFT_SUCCESS
        truncated = self._steps >= self._max_episode_steps and not success
        info = {
            "is_success": success,
            "lift": lift,
            "target_ball": self._target_ball,
            "metrics": {
                "collisions": float(self._collisions),
                "limit_violations": float(self._limit_violations),
                "cycle_steps": float(self._steps if success else 0.0),
                "gripper_ball_min_distance_m": float(self._gripper_ball_min_distance),
                "gripper_ball_contact_steps": float(self._gripper_ball_contact_steps),
                "gripper_closing_contact_steps": float(self._gripper_closing_contact_steps),
                "gripper_ball_first_contact_step": float(self._gripper_ball_first_contact_step),
                "gripper_ball_max_force_n": float(self._gripper_ball_max_force),
                "gripper_action_min": float(self._gripper_action_min),
                "max_lift_m": float(self._max_lift),
                "grasp_assist_used": float(self._grasp_assist_used),
                "grasp_assist_attached": float(self._grasp_assist_attached),
                "grasp_assist_steps": float(self._grasp_assist_steps),
                "grasp_assist_attach_step": float(self._grasp_assist_attach_step),
            },
            "grasp_assist": self.grasp_assist,
            "grasp_assist_attached": self._grasp_assist_attached,
        }
        return self._obs(world), 1.0 if success else 0.0, success, truncated, info

    def close(self) -> None:
        if self._world is not None:
            self._world.renderer.close()
            self._world = None


# Seeded reset randomization of the tabletop scene.
DEFAULTS: dict[str, Any] = {
    "cameras": {"up": "top", "side": "front", "wrist": "wrist_cam"},
    "randomize": {
        "joints": 2.0,
        "bodies": {},
        "cameras": {},
        # Ball centers are sampled in the user frame (cm): x right, y forward.
        # Keep the whole ball inside the up camera: it covers y <= 31 cm (v=480 is
        # the bottom edge), and the 2 cm radius needs ~2 cm of margin.
        "ball_workspace": {"x": [-10.0, 24.0], "y": [10.0, 28.0]},
        # Reject poses inside these rectangles (cm) plus margin (cm).
        "ball_keepouts": [
            {"x": [15.0, 25.0], "y": [20.0, 30.0], "margin": 2.0},  # plate
            {"x": [-6.0, 6.0], "y": [39.0, 51.0], "margin": 1.0},   # up stand base
        ],
        "ball_spacing": 0.06,
    },
}


def make_env(n_envs: int = 1, use_async_envs: bool = False, **kwargs: Any) -> dict[str, dict[int, Any]]:
    """EnvHub entry point: ``{"so101_tabletop": {0: vector_env}}``; ``kwargs`` override ``SO101Env``'s."""
    layout = load_layout(Path(kwargs["scene"]) if kwargs.get("scene") else HERE / SCENE_FILE)
    balls = layout.get("balls") or {}
    scene_randomize = dict(layout.get("randomize") or {})
    if balls.get("workspace_user_cm"):
        scene_randomize["ball_workspace"] = balls["workspace_user_cm"]
    if balls.get("keepouts"):
        scene_randomize["ball_keepouts"] = balls["keepouts"]
    if "spacing_m" in balls:
        scene_randomize["ball_spacing"] = balls["spacing_m"]
    merged = {**DEFAULTS, **kwargs}
    # Scene layout first, the per-job overrides last.
    merged["randomize"] = {**DEFAULTS["randomize"], **scene_randomize, **(kwargs.get("randomize") or {})}
    factory = partial(SO101Env, **merged)
    vector_cls = gym.vector.AsyncVectorEnv if use_async_envs else gym.vector.SyncVectorEnv
    return {"so101_tabletop": {0: vector_cls([factory] * n_envs)}}
