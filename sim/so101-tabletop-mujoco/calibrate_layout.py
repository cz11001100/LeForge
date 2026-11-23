#!/usr/bin/env python
"""Fit ``layout.json`` from a LeRobot v3 episode of the real tabletop scene.

The physical room changes now and then. Instead of hand-editing the MJCF, re-run this script:
it reads one episode (states, up/side/wrist frames), fits the camera poses and the arm joint
zero offsets against the plate anchors stored in ``layout.json``, then writes the numbers back.
A new room therefore needs: new plate corner pixels + camera positions in ``layout.json`` and
one command:

    python calibrate_layout.py --dataset ~/.cache/.../common_1115_1 --episode 0

What is fitted
  * ``top``/``front``: rotation + fovy, camera position kept from the layout.
  * ``wrist_cam``: local pose + fovy.
  * ``arm.joint_offsets_deg``: sim joint zero minus LeRobot zero (5 arm joints).
  * the two ball centers (used only as anchors, not stored).

What must be updated by hand when the room changes
  * ``plate.center_user_cm``, ``plate.size_cm``
  * ``cameras.<name>.pos`` (real camera positions)
  * ``calibration.anchors.plate_corners_px`` / ``plate_corner_order``
  * ``balls.radius_cm`` if the balls change

Requires: mujoco, numpy, pyarrow, av (all present in the LeRobot env).
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

import av
import cv2
import mujoco
import numpy as np
import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from env import JOINTS, SO101Env  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", required=True, help="LeRobot v3 dataset root (contains meta/, data/, videos/)")
    parser.add_argument("--episode", type=int, default=0)
    parser.add_argument("--layout", type=Path, default=HERE / "layout.json")
    parser.add_argument("--scene", type=Path, default=HERE / "so101_tabletop.xml")
    parser.add_argument("--max-frame", type=int, default=200, help="calibrate on frames 0..N before the grasp")
    return parser.parse_args()


def load_episode_rows(root: Path, episode: int) -> np.ndarray:
    rows = []
    for path in sorted(glob.glob(str(root / "data" / "chunk-*" / "*.parquet"))):
        table = pq.read_table(path)
        mask = table["episode_index"].to_numpy() == episode
        if mask.any():
            rows.append(np.stack(table["observation.state"].to_numpy(zero_copy_only=False))[mask])
    if not rows:
        raise SystemExit(f"episode {episode} not found under {root / 'data'}")
    return np.concatenate(rows, axis=0)


def episode_video(root: Path, episode: int, view: str) -> tuple[Path, float]:
    meta_rows = []
    for path in sorted(glob.glob(str(root / "meta" / "episodes" / "chunk-*" / "*.parquet"))):
        meta_rows.extend(pq.read_table(path).to_pylist())
    row = next((r for r in meta_rows if r["episode_index"] == episode), None)
    if row is None:
        raise SystemExit(f"episode {episode} missing from meta/episodes")
    key = f"videos/observation.images.{view}"
    path = root / "videos" / f"observation.images.{view}" / f"chunk-{row[key + '/chunk_index']:03d}" / f"file-{row[key + '/file_index']:03d}.mp4"
    return path, float(row[key + "/from_timestamp"])


def decode_frame(path: Path, t0: float, step: int, fps: int = 30) -> np.ndarray:
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        container.seek(int((t0 + step / fps) / stream.time_base), stream=stream, backward=True)
        target = t0 + step / fps
        last = None
        for frame in container.decode(video=0):
            last = frame.to_ndarray(format="rgb24")
            if frame.time is not None and frame.time + 1.0 / fps > target:
                break
        if last is None:
            raise SystemExit(f"no frame decoded from {path}")
        return last


def detect_ball(image: np.ndarray, name: str) -> np.ndarray | None:
    hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
    lo, hi = (0, 12) if name == "red" else (95, 135)
    mask = ((hsv[:, :, 0] >= lo) & (hsv[:, :, 0] <= hi) & (hsv[:, :, 1] > 85) & (hsv[:, :, 2] > 35)).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    if count < 2:
        return None
    blob = 1 + int(np.argmax(stats[1:, 4]))
    if stats[blob, 4] < 80:
        return None
    ys, xs = np.nonzero(labels == blob)
    (x, y), radius = cv2.minEnclosingCircle(np.column_stack([xs, ys]).astype(np.float32))
    return np.array([x, y, radius])


def expmap(rv: np.ndarray) -> np.ndarray:
    angle = np.linalg.norm(rv)
    if angle < 1e-12:
        return np.eye(3)
    axis = rv / angle
    skew = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    return np.eye(3) + np.sin(angle) * skew + (1 - np.cos(angle)) * (skew @ skew)


def project(position: np.ndarray, rotation: np.ndarray, fovy: float, point: np.ndarray, width: int, height: int):
    pc = rotation.T @ (np.asarray(point, dtype=float) - position)
    if pc[2] >= -1e-4:
        return np.array([1e4, 1e4])
    f = (height / 2) / np.tan(np.radians(fovy) / 2)
    return np.array([width / 2 + f * pc[0] / (-pc[2]), height / 2 - f * pc[1] / (-pc[2])])


def fit_camera(position, base_rotation, base_fovy, world_points, pixels, width, height):
    """Rotation (3) + log fovy (1) with the position held from the layout."""
    def residual(x):
        rotation = expmap(x[:3]) @ base_rotation
        fovy = base_fovy * np.exp(np.clip(x[3], -0.6, 0.6))
        return np.concatenate([project(position, rotation, fovy, p, width, height) - uv for p, uv in zip(world_points, pixels)])

    def solve(x0):
        x = x0.copy()
        damping = 1e-2
        current = float(residual(x) @ residual(x))
        for _ in range(200):
            r = residual(x)
            jac = np.zeros((len(r), 4))
            for i in range(4):
                step = x.copy()
                step[i] += 1e-6
                jac[:, i] = (residual(step) - r) / 1e-6
            step = np.linalg.solve(jac.T @ jac + damping * np.diag(np.diag(jac.T @ jac) + 1e-12), -jac.T @ r)
            trial = x + step
            cost = float(residual(trial) @ residual(trial))
            if cost < current:
                x, current, damping = trial, cost, max(damping / 3, 1e-9)
            else:
                damping *= 10
            if damping > 1e8:
                break
        return x, current

    starts = [np.zeros(4), np.array([0.3, 0, 0, 0.0]), np.array([-0.3, 0, 0, 0.0]),
              np.array([0, 0.3, 0, 0.0]), np.array([0, -0.3, 0, 0.0])]
    best = None
    for x0 in starts:
        x, cost = solve(x0)
        if np.isfinite(cost) and (best is None or cost < best[0]):
            best = (cost, x)
    return expmap(best[1][:3]) @ base_rotation, base_fovy * np.exp(np.clip(best[1][3], -0.6, 0.6)), best[0]


def minimize(residual, x0, iterations=80):
    x = x0.copy()
    damping = 1e-2

    def cost(v):
        r = np.clip(residual(v), -900, 900)
        return float(r @ r)

    current = cost(x)
    for _ in range(iterations):
        r = np.clip(residual(x), -900, 900)
        jac = np.zeros((len(r), len(x)))
        for i in range(len(x)):
            step = x.copy()
            step[i] += 1e-6
            jac[:, i] = (np.clip(residual(step), -900, 900) - r) / 1e-6
        step = np.linalg.solve(jac.T @ jac + damping * np.diag(np.diag(jac.T @ jac) + 1e-12), -jac.T @ r)
        trial = x + step
        trial_cost = cost(trial)
        if np.isfinite(trial_cost) and trial_cost < current:
            x, current, damping = trial, trial_cost, max(damping / 3, 1e-9)
        else:
            damping *= 10
        if damping > 1e8:
            break
    return x, current


def main() -> None:
    args = parse_args()
    layout = json.loads(args.layout.read_text())
    root = Path(args.dataset).expanduser()
    states = load_episode_rows(root, args.episode)
    layout_view = layout.get("calibration") or {}
    anchors = layout_view.get("anchors") or {}
    if "plate_corners_px" not in anchors:
        raise SystemExit("layout.calibration.anchors.plate_corners_px is required")

    env = SO101Env(scene=args.scene, initial_joints=states[0], randomize={"joints": 0.0, "ball_workspace": None})
    env.reset(seed=0)
    world = env._ensure_world()
    model = world.model
    height, width = env.height, env.width

    def camera_state(name):
        cid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_CAMERA, name)
        return cid, world.data.cam_xpos[cid].copy(), world.data.cam_xmat[cid].reshape(3, 3).copy(), model.cam_fovy[cid]

    # plate world corners from the layout
    center = layout["plate"]["center_user_cm"]
    half = 0.5 * layout["plate"]["size_cm"]
    y_user, x_user = center[1] / 100 + 0.083, -center[0] / 100 - 0.0555
    plate = np.array([
        [y_user + half[1] / 100, x_user + half[0] / 100, layout["plate"].get("top_z_m", 0.0075)],
        [y_user + half[1] / 100, x_user - half[0] / 100, layout["plate"].get("top_z_m", 0.0075)],
        [y_user - half[1] / 100, x_user - half[0] / 100, layout["plate"].get("top_z_m", 0.0075)],
        [y_user - half[1] / 100, x_user + half[0] / 100, layout["plate"].get("top_z_m", 0.0075)],
    ])

    # 1. fixed cameras from the plate corners
    for view, cam_name in (("up", "top"), ("side", "front")):
        pixels = np.asarray(anchors["plate_corners_px"][view], dtype=float)
        order = anchors["plate_corner_order"][view]
        _, position, rotation, fovy = camera_state(cam_name)
        rotation, fovy, cost = fit_camera(position, rotation, fovy, [plate[i] for i in order], pixels, width, height)
        cid = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_CAMERA, cam_name)
        model.cam_pos[cid] = position
        quat = np.zeros(4)
        mujoco.mju_mat2Quat(quat, rotation.flatten())
        model.cam_quat[cid] = quat
        model.cam_fovy[cid] = fovy
        layout["cameras"][cam_name] = {"pos": position.tolist(), "quat": quat.tolist(), "fovy": float(fovy)}
        print(f"{cam_name}: fovy {fovy:.1f}  corner rms {np.sqrt(cost / 8):.2f}px")

    mujoco.mj_forward(model, world.data)
    _, top_position, top_rotation, top_fovy = camera_state("top")
    _, front_position, front_rotation, front_fovy = camera_state("front")

    # 2. ball centers from the up/side first frame
    up_path, up_t0 = episode_video(root, args.episode, "up")
    side_path, side_t0 = episode_video(root, args.episode, "side")
    up_frame = decode_frame(up_path, up_t0, 0)
    side_frame = decode_frame(side_path, side_t0, 0)
    ball_pixels = {"up": {}, "side": {}}
    for name in ("red", "blue"):
        for view, frame in (("up", up_frame), ("side", side_frame)):
            hit = detect_ball(frame, name)
            if hit is not None:
                ball_pixels[view][name] = hit
    if "red" not in ball_pixels["up"]:
        raise SystemExit("red ball not detected in the up frame; check the dataset/layout")

    # 3. wrist camera + ball centers + joint offsets
    wrist_path, wrist_t0 = episode_video(root, args.episode, "wrist")
    track = {}
    for step in range(0, min(args.max_frame, len(states) - 1) + 1, 20):
        hit = detect_ball(decode_frame(wrist_path, wrist_t0, step), "red")
        if hit is not None:
            track[step] = hit
    if len(track) < 5:
        raise SystemExit("not enough wrist frames with a visible red ball")
    ball_radius = float((layout.get("balls") or {}).get("radius_cm", 2.6)) / 100.0
    wrist_cid, wrist_pos, wrist_rot, wrist_fovy = camera_state("wrist_cam")

    def residual(x):
        wpos, wrv, wf, red_xy, blue_xy, offsets = x[:3], x[3:6], x[6], x[7:9], x[9:11], x[11:16]
        red = np.array([red_xy[0], red_xy[1], ball_radius])
        blue = np.array([blue_xy[0], blue_xy[1], ball_radius])
        fovy = wrist_fovy * np.exp(np.clip(wf, -0.4, 0.4))
        out = []
        for name, ball in (("red", red), ("blue", blue)):
            if name in ball_pixels["up"]:
                out += list(project(top_position, top_rotation, top_fovy, ball, width, height) - ball_pixels["up"][name][:2])
            if name in ball_pixels["side"]:
                out += list(project(front_position, front_rotation, front_fovy, ball, width, height) - ball_pixels["side"][name][:2])
        for step, (u, v, r) in track.items():
            world.joint_offsets = offsets  # degrees, same units as layout.arm.joint_offsets_deg
            qpos = world.to_ctrl(states[step])
            world.data.qpos[world.qadr] = qpos
            world.data.ctrl[world.actuators] = qpos
            mujoco.mj_forward(model, world.data)
            body_pos = world.data.xpos[world._id(mujoco.mjtObj.mjOBJ_BODY, "camera_mount", "calibration")]
            body_rot = world.data.xmat[world._id(mujoco.mjtObj.mjOBJ_BODY, "camera_mount", "calibration")].reshape(3, 3)
            cam = body_pos + body_rot @ wpos
            rot = body_rot @ (expmap(wrv) @ wrist_rot)
            pc = rot.T @ (red - cam)
            if pc[2] >= 0:
                out += [1e3, 1e3, 1e3]
            else:
                f = (height / 2) / np.tan(np.radians(fovy) / 2)
                uv = np.array([width / 2 + f * pc[0] / (-pc[2]), height / 2 - f * pc[1] / (-pc[2])])
                out += [uv[0] - u, uv[1] - v, 0.5 * (f * ball_radius / np.linalg.norm(red - cam) - r)]
        out += list(0.35 * offsets)
        return np.array(out)

    x0 = np.r_[wrist_pos, np.zeros(3), 0.0, np.array([0.35, 0.05]), np.array([0.30, -0.05]),
               (layout.get("arm") or {}).get("joint_offsets_deg", [0] * 6)[:5]]
    best = None
    rng = np.random.default_rng(0)
    for trial in range(8):
        start = x0.copy()
        if trial:
            start[:3] += rng.uniform(-0.04, 0.04, 3)
            start[3:6] += rng.uniform(-0.3, 0.3, 3)
            start[7:11] += rng.uniform(-0.05, 0.05, 4)
            start[11:16] += rng.uniform(-0.08, 0.08, 5)
        x, cost = minimize(residual, start)
        if np.isfinite(cost) and (best is None or cost < best[0]):
            best = (cost, x)
    x = best[1]
    wpos, wrv, wf, offsets = x[:3], x[3:6], x[6], x[11:16]
    fovy = wrist_fovy * np.exp(np.clip(wf, -0.4, 0.4))
    quat = np.zeros(4)
    mujoco.mju_mat2Quat(quat, (expmap(wrv) @ wrist_rot).flatten())
    layout["cameras"]["wrist_cam"] = {"pos": wpos.tolist(), "quat": quat.tolist(), "fovy": float(fovy)}
    layout["arm"]["joint_offsets_deg"] = offsets.tolist() + [0.0]
    layout["calibration"]["residual_px"] = float(np.sqrt(best[0] / len(residual(x))))
    layout["calibration"]["status"] = "auto-calibrated by calibrate_layout.py"
    args.layout.write_text(json.dumps(layout, indent=2, ensure_ascii=False) + "\n")
    print(f"wrist_cam: fovy {fovy:.1f}  pos {np.round(wpos, 4).tolist()}")
    print(f"joint offsets (deg): {np.round(offsets, 1).tolist()}")
    print(f"residual rms: {layout['calibration']['residual_px']:.2f}px  -> {args.layout}")
    print("red ball world (anchor only):", np.round([x[7], x[8], ball_radius], 3).tolist())


if __name__ == "__main__":
    main()