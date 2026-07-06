#!/usr/bin/env python3
"""
HTTP adapter that lets Xtreme1 call a local FusionDet SANet inference script.

Xtreme1 calls model URLs with:
    {"datas": [{"id": 1, "pointCloudUrl": "...", "imageUrls": [...]}]}

This adapter resolves the point cloud URL back to the external-data filesystem,
runs sanet_infer.py once per clip, then returns the per-frame OD boxes in the
shape expected by Xtreme1. The SANet script also writes OCC and merged PCD
visualization files under FUSIONDET_OUTPUT_ROOT.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import posixpath
import shutil
import subprocess
import sys
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


OK = "OK"
ERROR = "ERROR"


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)


FUSIONDET_ROOT = Path(env("FUSIONDET_ROOT", "/home/user/cjg/code/fusiondet"))
INFER_SCRIPT = Path(env("FUSIONDET_INFER_SCRIPT", str(FUSIONDET_ROOT / "tools/misc/sanet_infer.py")))
CONFIG = env(
    "FUSIONDET_CONFIG",
    str(FUSIONDET_ROOT / "configs/sanet_nus2per2/sanet-point-voxel01-transfusion-nus2per2.py"),
)
CHECKPOINT = env(
    "FUSIONDET_CHECKPOINT",
    str(FUSIONDET_ROOT / "work_dirs/sanet-point-voxel01-transfusion-nus2per2/epoch_20_ema.pth"),
)
PYTHON_BIN = env("FUSIONDET_PYTHON", sys.executable)
EXTERNAL_DATA_ROOT = Path(env("EXTERNAL_DATA_ROOT", "/home/user/cjg/conch_data"))
OUTPUT_ROOT = Path(env("FUSIONDET_OUTPUT_ROOT", str(EXTERNAL_DATA_ROOT / "_fusiondet_results")))
PUBLIC_OUTPUT_PREFIX = env("FUSIONDET_PUBLIC_OUTPUT_PREFIX", "/external-data/_fusiondet_results")
MODEL_TYPE = env("FUSIONDET_MODEL_TYPE", "fusion")
SCORE_THR = env("FUSIONDET_SCORE_THR", "")
USE_CONCH = env("FUSIONDET_USE_CONCH", "1") != "0"
MULTI_TASK = env("FUSIONDET_MULTI_TASK", "1") != "0"
SAVE_OCC = env("FUSIONDET_SAVE_OCC", "1") != "0"
SAVE_PCD = env("FUSIONDET_SAVE_PCD", "1") != "0"
SAVE_IMAGE = env("FUSIONDET_SAVE_IMAGE", "1") != "0"
RUN_TIMEOUT_SEC = int(env("FUSIONDET_RUN_TIMEOUT_SEC", "3600"))
LOCK_WAIT_SEC = int(env("FUSIONDET_LOCK_WAIT_SEC", "3600"))
DEFAULT_CONFIDENCE = float(env("FUSIONDET_DEFAULT_CONFIDENCE", "0.99"))


def json_response(handler: BaseHTTPRequestHandler, status: int, body: Any) -> None:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def strip_external_data_prefix(path: str) -> str:
    parsed = urlparse(path)
    raw_path = parsed.path if parsed.scheme else path
    raw_path = unquote(raw_path).replace("\\", "/")
    marker = "/external-data/"
    if marker in raw_path:
        return raw_path.split(marker, 1)[1]
    return raw_path.lstrip("/")


def resolve_external_path(url: str) -> Path:
    rel = strip_external_data_prefix(url)
    return (EXTERNAL_DATA_ROOT / rel).resolve()


def find_clip_root(point_path: Path) -> Path:
    parts = point_path.parts
    for index, part in enumerate(parts):
        if part == "lidars" and index > 0:
            return Path(*parts[:index])
    raise ValueError(f"Cannot infer clip root from point cloud path: {point_path}")


def token_from_point_path(point_path: Path) -> str:
    return point_path.stem


def output_dir_for_clip(clip_root: Path) -> Path:
    try:
        rel = clip_root.resolve().relative_to(EXTERNAL_DATA_ROOT.resolve())
        clean = "__".join(rel.parts)
    except ValueError:
        clean = clip_root.name
    digest = hashlib.sha1(str(clip_root.resolve()).encode("utf-8")).hexdigest()[:10]
    return OUTPUT_ROOT / f"{clean}__{digest}"


def public_url(path: Path) -> str:
    rel = path.resolve().relative_to(OUTPUT_ROOT.resolve()).as_posix()
    return posixpath.join(PUBLIC_OUTPUT_PREFIX.rstrip("/"), rel)


def expected_paths(frame_out_dir: Path, token: str) -> dict[str, Path]:
    return {
        "det": frame_out_dir / "det" / f"{token}.json",
        "pcd": frame_out_dir / "pcd" / f"{token}.pcd",
        "occ": frame_out_dir / "occ" / f"{token}.npz",
        "png": frame_out_dir / f"{token}.png",
    }


def frame_output_dir(clip_out_dir: Path, clip_root: Path, token: str) -> Path:
    split_dir = clip_out_dir / clip_root.name
    if (split_dir / "det" / f"{token}.json").exists():
        return split_dir
    return clip_out_dir


def build_command(clip_root: Path, clip_out_dir: Path) -> list[str]:
    cmd = [
        PYTHON_BIN,
        str(INFER_SCRIPT),
        "--config",
        CONFIG,
        "--checkpoint",
        CHECKPOINT,
        "--data_root",
        str(clip_root),
        "--out_dir",
        str(clip_out_dir),
        "--model_type",
        MODEL_TYPE,
        "--no_with_gt",
    ]
    if SCORE_THR:
        cmd.extend(["--score_thr", SCORE_THR])
    if USE_CONCH:
        cmd.append("--use_conch")
    if MULTI_TASK:
        cmd.append("--multi_task")
    if SAVE_OCC:
        cmd.append("--save_occ")
    if SAVE_PCD:
        cmd.append("--save_pcd")
    else:
        cmd.append("--no_save_pcd")
    if not SAVE_IMAGE:
        cmd.append("--donot_save_img")
    return cmd


def run_clip_if_needed(clip_root: Path, token: str) -> tuple[Path, dict[str, Path]]:
    clip_out_dir = output_dir_for_clip(clip_root)
    frame_dir = frame_output_dir(clip_out_dir, clip_root, token)
    paths = expected_paths(frame_dir, token)
    if paths["det"].exists():
        return frame_dir, paths

    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    lock_path = clip_out_dir.with_suffix(".lock")
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as lock:
            lock.write(f"{os.getpid()} {time.time()}\n")
        try:
            if clip_out_dir.exists():
                shutil.rmtree(clip_out_dir)
            clip_out_dir.mkdir(parents=True, exist_ok=True)
            cmd = build_command(clip_root, clip_out_dir)
            completed = subprocess.run(
                cmd,
                cwd=str(FUSIONDET_ROOT),
                text=True,
                capture_output=True,
                timeout=RUN_TIMEOUT_SEC,
            )
            log_path = clip_out_dir / "infer.log"
            log_path.write_text(
                "$ " + " ".join(cmd) + "\n\nSTDOUT:\n" + completed.stdout + "\n\nSTDERR:\n" + completed.stderr,
                encoding="utf-8",
            )
            if completed.returncode != 0:
                raise RuntimeError(f"FusionDet inference failed, see {log_path}")
        finally:
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass
    except FileExistsError:
        deadline = time.time() + LOCK_WAIT_SEC
        while time.time() < deadline:
            frame_dir = frame_output_dir(clip_out_dir, clip_root, token)
            paths = expected_paths(frame_dir, token)
            if paths["det"].exists():
                return frame_dir, paths
            time.sleep(2)
        raise TimeoutError(f"Timed out waiting for FusionDet lock: {lock_path}")

    frame_dir = frame_output_dir(clip_out_dir, clip_root, token)
    paths = expected_paths(frame_dir, token)
    if not paths["det"].exists():
        raise FileNotFoundError(f"FusionDet did not create detection JSON for {token}: {paths['det']}")
    return frame_dir, paths


def load_objects(det_json_path: Path) -> list[dict[str, Any]]:
    data = json.loads(det_json_path.read_text(encoding="utf-8"))
    result = []
    for obj in data.get("objects", []):
        size = obj.get("size") or [0, 0, 0]
        translation = obj.get("translation") or [0, 0, 0]
        result.append(
            {
                "label": obj.get("category") or "unknown",
                "confidence": float(obj.get("score", DEFAULT_CONFIDENCE)),
                "x": float(translation[0]),
                "y": float(translation[1]),
                "z": float(translation[2]),
                "dx": float(size[0]),
                "dy": float(size[1]),
                "dz": float(size[2]),
                "rotX": 0.0,
                "rotY": 0.0,
                "rotZ": float(obj.get("yaw", 0.0)),
            }
        )
    return result


def infer_one(data: dict[str, Any]) -> dict[str, Any]:
    data_id = data.get("id")
    point_url = data.get("pointCloudUrl")
    if not point_url:
        return {"id": data_id, "code": ERROR, "message": "pointCloudUrl is empty", "objects": []}

    point_path = resolve_external_path(point_url)
    if not point_path.exists():
        return {"id": data_id, "code": ERROR, "message": f"Point cloud not found: {point_path}", "objects": []}

    clip_root = find_clip_root(point_path)
    token = token_from_point_path(point_path)
    _, paths = run_clip_if_needed(clip_root, token)
    objects = load_objects(paths["det"])

    urls = {}
    for key, value in paths.items():
        if value.exists():
            urls[key] = public_url(value)
    message = json.dumps({"clipRoot": str(clip_root), "outputs": urls}, ensure_ascii=False)
    return {"id": data_id, "code": OK, "message": message, "objects": objects}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            json_response(self, HTTPStatus.OK, {"code": OK, "message": "ok"})
        else:
            json_response(self, HTTPStatus.NOT_FOUND, {"code": ERROR, "message": "not found"})

    def do_POST(self) -> None:
        if self.path.rstrip("/") not in ("", "/infer"):
            json_response(self, HTTPStatus.NOT_FOUND, {"code": ERROR, "message": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            results = [infer_one(item) for item in payload.get("datas", [])]
            json_response(self, HTTPStatus.OK, {"code": OK, "message": "", "data": results})
        except Exception as exc:
            json_response(self, HTTPStatus.OK, {"code": ERROR, "message": str(exc), "data": []})

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=env("FUSIONDET_SERVICE_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(env("FUSIONDET_SERVICE_PORT", "8508")))
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"FusionDet Xtreme1 adapter listening on {args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
