#!/usr/bin/env python3
"""Platform evaluation adapter for FusionDet/SANet.

This service is intentionally separate from FusionDet's original tools/test.py.
It builds a temporary SANet ann_file from Xtreme1 selected data ids, invokes the
existing evaluation script, and returns metrics plus predictions for platform UI.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pickle
import subprocess
import shutil
import re
import sys
import time
import numpy as np
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

OK = "OK"
ERROR = "ERROR"


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)


FUSIONDET_ROOT = Path(env("FUSIONDET_ROOT", "/home/user/cjg/code/fusiondet"))
PYTHON_BIN = env("FUSIONDET_EVAL_PYTHON", sys.executable)
TEST_SCRIPT = Path(env("FUSIONDET_TEST_SCRIPT", str(FUSIONDET_ROOT / "tools/test.py")))
WORK_ROOT = Path(env("FUSIONDET_PLATFORM_EVAL_ROOT", str(FUSIONDET_ROOT / "work_dirs/platform_eval")))
POINTPILLARS_ROOT = Path(env("POINTPILLARS_ROOT", "/home/user/cjg/code/pointpillars_hb"))
POINTPILLARS_PYTHON = env("POINTPILLARS_EVAL_PYTHON", "/home/user/anaconda3/envs/sanet_deploy/bin/python")
POINTPILLARS_RAW_EVAL_PYTHON = env("POINTPILLARS_RAW_EVAL_PYTHON", "/home/user/anaconda3/envs/pointpillars/bin/python")
POINTPILLARS_METRIC_PYTHON = env("POINTPILLARS_METRIC_PYTHON", POINTPILLARS_PYTHON)
POINTPILLARS_DEFAULT_CONFIG = Path(env("POINTPILLARS_EVAL_CONFIG", str(POINTPILLARS_ROOT / "model/pipeline.config")))
POINTPILLARS_DEFAULT_MODEL_DIR = Path(env("POINTPILLARS_MODEL_DIR", str(POINTPILLARS_ROOT / "model")))
POINTPILLARS_CLASS_MAP = env("POINTPILLARS_CLASS_MAP", "{}")
FUSIONDET_EVAL_CONFIG_JSON = env("FUSIONDET_EVAL_CONFIG_JSON", "")
EXTERNAL_DATA_ROOT = Path(env("EXTERNAL_DATA_ROOT", "/home/user/cjg/conch_data"))
MYSQL_BIN = env("MYSQL_BIN", "mysql")
MYSQL_DOCKER_CONTAINER = env("MYSQL_DOCKER_CONTAINER", "hb-wblabel-mysql-1")
MYSQL_HOST = env("XTREME1_MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = env("XTREME1_MYSQL_PORT", "8191")
MYSQL_USER = env("XTREME1_MYSQL_USER", "xtreme1")
MYSQL_PASSWORD = env("XTREME1_MYSQL_PASSWORD", "Rc4K3L6f")
MYSQL_DATABASE = env("XTREME1_MYSQL_DATABASE", "xtreme1")
RUN_TIMEOUT_SEC = int(env("FUSIONDET_EVAL_TIMEOUT_SEC", "21600"))
CAMERA_PREFIXES = ("image_", "camera_")


def json_response(handler: BaseHTTPRequestHandler, status: int, body: Any) -> None:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def mysql_command(sql: str) -> list[str]:
    mysql_args = [
        f"-u{MYSQL_USER}",
        f"-p{MYSQL_PASSWORD}",
        "--batch",
        "--raw",
        "--skip-column-names",
        MYSQL_DATABASE,
        "-e",
        sql,
    ]
    if shutil.which(MYSQL_BIN):
        return [MYSQL_BIN, f"-h{MYSQL_HOST}", f"-P{MYSQL_PORT}", *mysql_args]
    if MYSQL_DOCKER_CONTAINER and shutil.which("docker"):
        return ["docker", "exec", MYSQL_DOCKER_CONTAINER, "mysql", *mysql_args]
    return [MYSQL_BIN, f"-h{MYSQL_HOST}", f"-P{MYSQL_PORT}", *mysql_args]


def mysql_rows(sql: str) -> list[list[str]]:
    cmd = mysql_command(sql)
    completed = subprocess.run(cmd, text=True, capture_output=True, timeout=120)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip())
    rows = []
    for line in completed.stdout.splitlines():
        if line.strip():
            rows.append(line.split("\t"))
    return rows


def sql_list(ids: list[int]) -> str:
    if not ids:
        return "NULL"
    return ",".join(str(int(x)) for x in ids)


def fetch_platform_frames(data_ids: list[int]) -> dict[int, dict[str, Any]]:
    rows = mysql_rows(
        "SELECT id,name,parent_id,content FROM data "
        f"WHERE id IN ({sql_list(data_ids)}) AND type='SINGLE_DATA' AND is_deleted=0"
    )
    frames = {}
    for row in rows:
        frames[int(row[0])] = {
            "id": int(row[0]),
            "name": row[1],
            "parentId": int(row[2]),
            "content": json.loads(row[3] or "[]"),
        }
    return frames


def fetch_file_paths(file_ids: list[int]) -> dict[int, dict[str, str]]:
    if not file_ids:
        return {}
    rows = mysql_rows(
        "SELECT id,name,path FROM file "
        f"WHERE id IN ({sql_list(file_ids)})"
    )
    return {int(row[0]): {"name": row[1], "path": row[2]} for row in rows}


def fetch_gt_objects(data_ids: list[int]) -> dict[int, list[dict[str, Any]]]:
    rows = mysql_rows(
        "SELECT data_id,class_attributes FROM data_annotation_object "
        f"WHERE data_id IN ({sql_list(data_ids)}) AND source_id=-1"
    )
    result: dict[int, list[dict[str, Any]]] = {}
    for data_id, attrs in rows:
        try:
            result.setdefault(int(data_id), []).append(json.loads(attrs))
        except json.JSONDecodeError:
            continue
    return result


def object_to_box(obj: dict[str, Any]) -> tuple[list[float], str, int]:
    contour = obj.get("contour") or {}
    center = contour.get("center3D") or {}
    size = contour.get("size3D") or {}
    rot = contour.get("rotation3D") or {}
    box = [
        float(center.get("x", 0.0)),
        float(center.get("y", 0.0)),
        float(center.get("z", 0.0)),
        float(size.get("x", 0.0)),
        float(size.get("y", 0.0)),
        float(size.get("z", 0.0)),
        float(rot.get("z", 0.0)),
    ]
    meta = obj.get("meta") or {}
    return box, str(obj.get("modelClass") or obj.get("label") or meta.get("classType") or "unknown"), int(contour.get("pointN") or 1)


def yaw_to_quaternion(yaw: float) -> list[float]:
    return [math.cos(yaw / 2.0), 0.0, 0.0, math.sin(yaw / 2.0)]


def object_to_annotation(obj: dict[str, Any]) -> dict[str, Any]:
    box, name, points = object_to_box(obj)
    return {
        "translation": box[:3],
        "size": box[3:6],
        "rotation": yaw_to_quaternion(box[6]),
        "category": name,
        "sub_category": "",
        "velocity": [0.0, 0.0, 0.0],
        "num_lidar_pts": max(points, 1),
        "num_radar_pts": 0,
    }


def ensure_link_or_copy(source: Path, target: Path) -> None:
    if target.exists() or target.is_symlink():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.symlink_to(source, target_is_directory=source.is_dir())
    except OSError:
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            shutil.copy2(source, target)


def collect_content_file_ids(content: list[dict[str, Any]]) -> list[int]:
    ids: list[int] = []
    for item in content:
        if item.get("type") == "file" and item.get("fileId"):
            ids.append(int(item["fileId"]))
        for file_item in item.get("files") or []:
            if file_item.get("fileId"):
                ids.append(int(file_item["fileId"]))
    return ids


def first_content_file(item: dict[str, Any], files: dict[int, dict[str, str]]) -> dict[str, str] | None:
    if item.get("type") == "file" and item.get("fileId"):
        return files.get(int(item["fileId"]))
    for file_item in item.get("files") or []:
        if file_item.get("fileId"):
            found = files.get(int(file_item["fileId"]))
            if found:
                return found
    return None


def frame_source_files(frame: dict[str, Any], files: dict[int, dict[str, str]]) -> dict[str, Any]:
    source: dict[str, Any] = {"cameras": {}}
    for item in frame["content"]:
        name = str(item.get("name") or "")
        file_info = first_content_file(item, files)
        if not file_info:
            continue
        path = Path(file_info["path"])
        if name == "point_cloud" or path.suffix == ".bin":
            source["lidar"] = path
        elif name == "camera_config" or path.name in {"calib.json", "calib_cylindrical.json"}:
            source["calib"] = path
        elif path.name == "pose.json":
            source["pose"] = path
        elif name.startswith(CAMERA_PREFIXES):
            source["cameras"][name] = path
    if "lidar" not in source:
        raise RuntimeError(f"Cannot find point cloud file for platform dataId={frame['id']}")
    return source


def resolve_external_path(path: Path) -> Path:
    return path if path.is_absolute() else EXTERNAL_DATA_ROOT / path


def infer_clip_root(lidar_rel_path: Path) -> Path:
    parts = list(lidar_rel_path.parts)
    if "lidars" not in parts:
        raise RuntimeError(f"Cannot infer clip root from lidar path: {lidar_rel_path}")
    return Path(*parts[:parts.index("lidars")])


def camera_key(group_name: str, rel_path: Path) -> str:
    if group_name.startswith("image_"):
        return group_name.split("_", 2)[2]
    if group_name.startswith("camera_"):
        return group_name.split("_", 1)[1]
    parts = list(rel_path.parts)
    if "cameras" in parts:
        index = parts.index("cameras")
        if index + 1 < len(parts):
            return parts[index + 1]
    return rel_path.parent.name


def timestamp_from_lidar_name(name: str) -> str:
    stem = Path(name).stem
    return stem[6:] if stem.startswith("LIDAR_") else stem


def frame_obstacle_entry(
    frame: dict[str, Any],
    source: dict[str, Any],
    clip_root: Path,
    gt_objects: list[dict[str, Any]],
    valid_camera_names: set[str],
) -> tuple[str, dict[str, Any]]:
    lidar_rel = source["lidar"].relative_to(clip_root)
    timestamp = timestamp_from_lidar_name(source["lidar"].name)
    cam_files = {}
    for group_name, camera_path in sorted(source["cameras"].items()):
        rel = camera_path.relative_to(clip_root)
        cam_name = camera_key(group_name, rel)
        if cam_name not in valid_camera_names:
            continue
        cam_files[cam_name] = {
            "cam_file": rel.as_posix(),
            "cylindrical_cam_file": rel.as_posix(),
            "ego_time": Path(camera_path).stem,
        }
    return timestamp, {
        "FrameID": Path(source["lidar"]).stem,
        "filepath": lidar_rel.as_posix(),
        "timestamp": timestamp,
        "ego_file": timestamp,
        "cam_files": cam_files,
        "annotations": [object_to_annotation(obj) for obj in gt_objects],
        "prev_time_file": "",
        "next_time_file": "",
        "platform_data_id": frame["id"],
    }


def valid_calib_cameras(calib_path: Path) -> set[str]:
    try:
        calib = json.loads(calib_path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    valid = set()
    for name, value in calib.items():
        if name == "LIDAR_CAR" or not isinstance(value, dict):
            continue
        if value.get("rotation") is not None and value.get("translation") is not None and value.get("camera_intrinsic") is not None:
            valid.add(name)
    return valid


def write_converter_helper(helper_path: Path) -> None:
    helper = [
        "#!/usr/bin/env python3",
        "import argparse",
        "import sys",
        "",
        "parser = argparse.ArgumentParser()",
        'parser.add_argument("--fusiondet-root", required=True)',
        'parser.add_argument("--root", required=True)',
        'parser.add_argument("--prefix", required=True)',
        'parser.add_argument("--metrics", default="mAP")',
        "args = parser.parse_args()",
        "",
        "sys.path.insert(0, args.fusiondet_root)",
        "from tools.data_converter.sanet_per2_converter import create_per2_infos",
        "",
        'metrics = set(args.metrics.split(","))',
        'options = {"dataset": "conch", "keep_empty": True, "class_map": None}',
        'if "miou" in metrics:',
        "    options.update({",
        '        "task": "occ",',
        '        "keep_empty_seg": True,',
        '        "lidarseg_only": True,',
        '        "gen_occ": True,',
        "    })",
        "create_per2_infos(args.root, args.prefix, max_sweeps=0, **options)",
        "",
    ]
    helper_path.write_text("\n".join(helper), encoding="utf-8")


def build_eval_pkl(evaluation_id: int, data_ids: list[int], metrics: list[str]) -> tuple[Path, list[int], int]:
    frames = fetch_platform_frames(data_ids)
    gt_map = fetch_gt_objects(data_ids)
    ordered_data_ids: list[int] = []
    out_dir = WORK_ROOT / f"eval_{evaluation_id}"
    dataset_root = out_dir / "dataset"
    if dataset_root.exists():
        shutil.rmtree(dataset_root)
    dataset_root.mkdir(parents=True, exist_ok=True)

    all_file_ids: list[int] = []
    for data_id in data_ids:
        frame = frames.get(int(data_id))
        if frame:
            all_file_ids.extend(collect_content_file_ids(frame["content"]))
    files = fetch_file_paths(sorted(set(all_file_ids)))

    scenes: dict[Path, dict[str, Any]] = {}
    for data_id in data_ids:
        frame = frames.get(int(data_id))
        if not frame:
            continue
        source = frame_source_files(frame, files)
        clip_root = infer_clip_root(source["lidar"])
        scene = scenes.setdefault(clip_root, {"frames": [], "sources": []})
        scene["frames"].append(frame)
        scene["sources"].append(source)
        ordered_data_ids.append(int(data_id))

    scene_names: list[str] = []
    miou_count = 0
    for clip_root, scene in scenes.items():
        digest = hashlib.sha1(clip_root.as_posix().encode("utf-8")).hexdigest()[:10]
        scene_name = f"{clip_root.name}_{digest}"
        scene_names.append(scene_name)
        scene_dir = dataset_root / scene_name
        clip_abs = resolve_external_path(clip_root)
        ensure_link_or_copy(clip_abs / "lidars", scene_dir / "lidars")
        if (clip_abs / "cameras").exists():
            ensure_link_or_copy(clip_abs / "cameras", scene_dir / "cameras")
            ensure_link_or_copy(clip_abs / "cameras", scene_dir / "cameras_cylindrical")
        calib_source = clip_abs / "calib_cylindrical.json"
        if not calib_source.exists():
            calib_source = clip_abs / "calib.json"
        ensure_link_or_copy(calib_source, scene_dir / "calib_cylindrical.json")
        ensure_link_or_copy(calib_source, scene_dir / "calib.json")
        valid_camera_names = valid_calib_cameras(calib_source)
        if (clip_abs / "pose.json").exists():
            ensure_link_or_copy(clip_abs / "pose.json", scene_dir / "pose.json")
        else:
            raise RuntimeError(f"Missing pose.json for clip {clip_abs}")
        if (clip_abs / "meta.json").exists():
            ensure_link_or_copy(clip_abs / "meta.json", scene_dir / "meta.json")
        if (clip_abs / "log.json").exists():
            ensure_link_or_copy(clip_abs / "log.json", scene_dir / "log.json")
        else:
            (scene_dir / "log.json").write_text("{}", encoding="utf-8")
        anno_dir = scene_dir / "anno"
        anno_dir.mkdir(parents=True, exist_ok=True)
        if (clip_abs / "anno" / "occ_labels").exists():
            ensure_link_or_copy(clip_abs / "anno" / "occ_labels", anno_dir / "occ_labels")

        obstacle: dict[str, Any] = {}
        keys: list[str] = []
        for frame, source in zip(scene["frames"], scene["sources"]):
            key, entry = frame_obstacle_entry(frame, source, clip_root, gt_map.get(int(frame["id"]), []), valid_camera_names)
            keys.append(key)
            obstacle[key] = entry
            lidar_stem = Path(source["lidar"]).stem
            if (anno_dir / "occ_labels" / "LIDAR_CAR" / f"{lidar_stem}.label").exists():
                miou_count += 1
        for index, key in enumerate(keys):
            obstacle[key]["prev_time_file"] = keys[index - 1] if index > 0 else ""
            obstacle[key]["next_time_file"] = keys[index + 1] if index + 1 < len(keys) else ""
        obstacle["first_frame"] = keys[0] if keys else ""
        (anno_dir / "obstacle_3d.json").write_text(json.dumps(obstacle, ensure_ascii=False), encoding="utf-8")

    train_val = {"train_file": [], "val_file": scene_names}
    (dataset_root / "train_val.json").write_text(json.dumps(train_val, ensure_ascii=False), encoding="utf-8")
    (dataset_root / "occ_train_val.json").write_text(json.dumps(train_val, ensure_ascii=False), encoding="utf-8")

    helper_path = out_dir / "build_infos.py"
    write_converter_helper(helper_path)
    prefix = f"eval_{evaluation_id}"
    cmd = [
        PYTHON_BIN,
        str(helper_path),
        "--fusiondet-root", str(FUSIONDET_ROOT),
        "--root", str(dataset_root),
        "--prefix", prefix,
        "--metrics", ",".join(metrics),
    ]
    helper_env = os.environ.copy()
    helper_env.setdefault("NUMBA_DISABLE_CACHE", "1")
    helper_env["NUMBA_CACHE_DIR"] = str(out_dir / "numba_cache")
    completed = subprocess.run(
        cmd,
        cwd=str(FUSIONDET_ROOT),
        text=True,
        capture_output=True,
        timeout=RUN_TIMEOUT_SEC,
        env=helper_env,
    )
    (out_dir / "build_infos.log").write_text(
        "$ " + " ".join(cmd) + "\n\nSTDOUT:\n" + completed.stdout + "\n\nSTDERR:\n" + completed.stderr,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Build SANet info failed, see {out_dir / 'build_infos.log'}: {completed.stderr[-1000:]}")

    pkl_path = dataset_root / f"{prefix}_infos_val.pkl"
    if not pkl_path.exists():
        raise RuntimeError(f"Build SANet info did not create {pkl_path}")
    return pkl_path, ordered_data_ids, miou_count

def load_outputs(path: Path) -> Any:
    try:
        import mmcv
        return mmcv.load(str(path))
    except Exception:
        with path.open("rb") as f:
            return pickle.load(f)


def tensor_to_list(value: Any) -> list[Any]:
    if hasattr(value, "detach"):
        value = value.detach().cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    if hasattr(value, "tolist"):
        return value.tolist()
    return list(value)


def predictions_from_outputs(outputs_path: Path, data_ids: list[int], class_names: list[str] | None = None) -> dict[str, list[dict[str, Any]]]:
    outputs = load_outputs(outputs_path)
    predictions: dict[str, list[dict[str, Any]]] = {}
    for data_id, item in zip(data_ids, outputs):
        det = item.get("obstacle", item) if isinstance(item, dict) else item
        if isinstance(det, list) and det:
            det = det[0]
        boxes_obj = det.get("boxes_3d") if isinstance(det, dict) else None
        if boxes_obj is None:
            predictions[str(data_id)] = []
            continue
        tensor = boxes_obj.tensor if hasattr(boxes_obj, "tensor") else boxes_obj
        boxes = tensor_to_list(tensor)
        scores = tensor_to_list(det.get("scores_3d", []))
        labels = tensor_to_list(det.get("labels_3d", []))
        frame_preds = []
        for index, box in enumerate(boxes):
            label_idx = int(labels[index]) if index < len(labels) else -1
            label = class_names[label_idx] if class_names and 0 <= label_idx < len(class_names) else str(label_idx)
            score = float(scores[index]) if index < len(scores) else 0.0
            frame_preds.append({
                "source": "PRED",
                "color": "#ef4444",
                "label": label,
                "confidence": score,
                "displayText": f"{label} {score:.2f}",
                "box": {
                    "x": float(box[0]), "y": float(box[1]), "z": float(box[2]),
                    "dx": float(box[3]), "dy": float(box[4]), "dz": float(box[5]),
                    "yaw": float(box[6]),
                },
            })
        predictions[str(data_id)] = frame_preds
    return predictions


def compact_detection_metrics(summary: dict[str, Any]) -> dict[str, Any]:
    per_class = []
    labels = summary.get("mean_dist_aps") or {}
    label_errors = summary.get("label_tp_errors") or {}
    for name, ap in labels.items():
        errors = label_errors.get(name) or {}
        per_class.append({
            "className": name,
            "AP": ap,
            "ATE": errors.get("trans_err"),
            "ASE": errors.get("scale_err"),
            "AOE": errors.get("orient_err"),
            "AVE": errors.get("vel_err"),
            "AAE": errors.get("attr_err"),
        })
    tp_errors = summary.get("tp_errors") or {}
    return {
        "mAP": summary.get("mean_ap"),
        "mATE": tp_errors.get("trans_err"),
        "mASE": tp_errors.get("scale_err"),
        "mAOE": tp_errors.get("orient_err"),
        "mAVE": tp_errors.get("vel_err"),
        "mAAE": tp_errors.get("attr_err"),
        "NDS": summary.get("nd_score"),
        "perClass": per_class,
    }


def format_detection_metrics(metrics: dict[str, Any]) -> str:
    lines = []
    for key in ("mAP", "mATE", "mASE", "mAOE", "mAVE", "mAAE", "NDS"):
        value = metrics.get(key)
        if isinstance(value, (int, float)):
            lines.append(f"{key}: {value:.4f}")
    per_class = metrics.get("perClass") or []
    if per_class:
        lines.append("Per-class results:")
        lines.append("Object Class\tAP\tATE\tASE\tAOE\tAVE\tAAE")
        for row in per_class:
            values = [row.get(k) for k in ("AP", "ATE", "ASE", "AOE", "AVE", "AAE")]
            formatted = ["-" if v is None else f"{float(v):.3f}" for v in values]
            lines.append(f"{row.get('className')}\t" + "\t".join(formatted))
    return "\n".join(lines)


def parse_metrics(stdout: str, work_dir: Path) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    summary = work_dir / "results" / "metrics_summary.json"
    if summary.exists():
        data = json.loads(summary.read_text(encoding="utf-8"))
        detection = compact_detection_metrics(data)
        metrics.update(detection)
        metrics["detectionText"] = format_detection_metrics(detection)
    occ_file = work_dir / "results" / "occ_eval_results.txt"
    if occ_file.exists():
        text = occ_file.read_text(encoding="utf-8", errors="ignore")
        metrics["miouTable"] = text
        for line in text.splitlines():
            if "meanIoU" in line:
                parts = [p.strip() for p in line.strip("| ").split("|")]
                if len(parts) >= 2:
                    try:
                        metrics["meanIoU"] = float(parts[1])
                    except ValueError:
                        pass
    return metrics


def eval_cfg_options(load_dim: int | None, metrics: list[str]) -> list[str]:
    options = [
        "data.test.pipeline.0.conch=False",
    ]
    if load_dim:
        options.append(f"data.test.pipeline.0.load_dim={load_dim}")
    if "miou" in metrics:
        options.append("data.test.occ_pipeline.0.conch=False")
        if load_dim:
            options.append(f"data.test.occ_pipeline.0.load_dim={load_dim}")
    return options


def write_test_runner(runner_path: Path) -> None:
    runner = [
        "#!/usr/bin/env python3",
        "import argparse",
        "import runpy",
        "import sys",
        "",
        "parser = argparse.ArgumentParser(add_help=False)",
        'parser.add_argument("--fusiondet-root", required=True)',
        'parser.add_argument("--test-script", required=True)',
        "args, rest = parser.parse_known_args()",
        "sys.path = [p for p in sys.path if not p.endswith('/tools')]",
        "if args.fusiondet_root not in sys.path:",
        "    sys.path.insert(0, args.fusiondet_root)",
        "sys.argv = [args.test_script] + rest",
        "runpy.run_path(args.test_script, run_name='__main__')",
        "",
    ]
    runner_path.write_text("\n".join(runner), encoding="utf-8")



def infer_evaluation_engine(payload: dict[str, Any]) -> str:
    explicit = str(payload.get("evaluationEngine") or payload.get("engine") or "").strip().lower()
    if explicit:
        return "pointpillars" if explicit in {"pointpillar", "pointpillars", "pp"} else "fusiondet"
    text = " ".join(str(payload.get(key) or "") for key in ("modelName", "modelUrl", "configPath", "checkpointPath")).lower()
    if "pointpillar" in text or "point_pillar" in text or "pp_data" in text:
        return "pointpillars"
    return "fusiondet"


def fusion_info_lidar_path(info: dict[str, Any], dataset_root: Path) -> Path:
    for key in ("lidar_path", "lidar_path_0", "pts_filename", "velodyne_path"):
        value = info.get(key)
        if value:
            path = Path(str(value))
            return path if path.is_absolute() else dataset_root / path
    raise RuntimeError(f"Cannot find lidar path in fusion info keys={list(info.keys())}")


def fusion_info_gt_arrays(info: dict[str, Any]) -> tuple[np.ndarray, np.ndarray]:
    if "gt_boxes" in info:
        gt_boxes = info.get("gt_boxes")
        gt_names = info.get("gt_names")
        return np.asarray(gt_boxes if gt_boxes is not None else [], dtype=np.float32), np.asarray(gt_names if gt_names is not None else [])
    annos = info.get("annos") or []
    boxes = []
    names = []
    if isinstance(annos, list):
        for anno in annos:
            trans = anno.get("translation") or [0, 0, 0]
            size = anno.get("size") or [0, 0, 0]
            rot = anno.get("rotation") or [1, 0, 0, 0]
            yaw = 0.0
            try:
                yaw = math.atan2(2.0 * (rot[0] * rot[3] + rot[1] * rot[2]), 1.0 - 2.0 * (rot[2] * rot[2] + rot[3] * rot[3]))
            except Exception:
                yaw = 0.0
            boxes.append([*trans[:3], *size[:3], yaw])
            names.append(str(anno.get("category") or anno.get("detection_name") or "unknown"))
    return np.asarray(boxes, dtype=np.float32), np.asarray(names)


def build_pointpillars_eval_assets(evaluation_id: int, fusion_infos_path: Path, load_dim: int | None, config_path: str | None) -> tuple[Path, Path, Path]:
    import numpy as np
    with fusion_infos_path.open("rb") as f:
        data = pickle.load(f)
    fusion_infos = list(data.get("infos", data) if isinstance(data, dict) else data)
    work_dir = WORK_ROOT / f"eval_{evaluation_id}"
    pp_root = work_dir / "pointpillars_dataset"
    velodyne_dir = pp_root / "training" / "velodyne"
    velodyne_dir.mkdir(parents=True, exist_ok=True)
    pp_infos = []
    dataset_root = fusion_infos_path.parent
    identity4 = np.eye(4, dtype=np.float32)
    p2 = np.eye(4, dtype=np.float32)[:3]
    for idx, info in enumerate(fusion_infos):
        lidar_src = fusion_info_lidar_path(info, dataset_root)
        lidar_name = f"{idx:06d}.bin"
        ensure_link_or_copy(lidar_src, velodyne_dir / lidar_name)
        boxes, names = fusion_info_gt_arrays(info)
        locs = []
        dims = []
        rots = []
        for box in boxes:
            x, y, z, dx, dy, dz, yaw = [float(v) for v in box[:7]]
            locs.append([x, y, z - dz * 0.5])
            dims.append([dy, dz, dx])
            rots.append(-yaw)
        count = len(locs)
        annos = {
            "name": names.astype(str) if count else np.asarray([], dtype=str),
            "truncated": np.zeros((count,), dtype=np.float32),
            "occluded": np.zeros((count,), dtype=np.int32),
            "alpha": np.zeros((count,), dtype=np.float32),
            "bbox": np.zeros((count, 4), dtype=np.float32),
            "dimensions": np.asarray(dims, dtype=np.float32).reshape((-1, 3)),
            "location": np.asarray(locs, dtype=np.float32).reshape((-1, 3)),
            "rotation_y": np.asarray(rots, dtype=np.float32),
            "difficulty": np.zeros((count,), dtype=np.int32),
            "num_points_in_gt": np.ones((count,), dtype=np.int32),
        }
        pp_infos.append({
            "image_idx": idx,
            "pointcloud_num_features": int(load_dim or 4),
            "velodyne_path": f"training/velodyne/{lidar_name}",
            "img_shape": [1920, 1080],
            "calib/R0_rect": identity4,
            "calib/Tr_velo_to_cam": identity4,
            "calib/P2": p2,
            "annos": annos,
        })
    info_path = pp_root / "kitti_infos_eval.pkl"
    with info_path.open("wb") as f:
        pickle.dump(pp_infos, f)
    source_config = Path(config_path) if config_path and str(config_path).endswith(".config") else POINTPILLARS_DEFAULT_CONFIG
    if not source_config.is_absolute():
        source_config = POINTPILLARS_ROOT / source_config
    cfg_text = source_config.read_text(encoding="utf-8")
    # The generated infos record the selected load dimension. Keep the reader
    # config in sync so, for example, 6-D point clouds are not parsed as 4-D.
    if load_dim is not None:
        cfg_text, replaced = re.subn(
            r"(num_point_features:\s*)\d+",
            rf"\g<1>{load_dim}",
            cfg_text,
        )
        if replaced == 0:
            raise ValueError("PointPillars config has no num_point_features setting")
    cfg_text = re.sub(r'eval_input_reader:\s*\{(?P<body>.*?)\n\}', lambda m: _rewrite_pp_eval_reader(m, info_path, pp_root), cfg_text, flags=re.S)
    eval_config = work_dir / "pointpillars_eval.config"
    eval_config.write_text(cfg_text, encoding="utf-8")
    return eval_config, pp_root, info_path


def _rewrite_pp_eval_reader(match: re.Match, info_path: Path, root_path: Path) -> str:
    body = match.group("body")
    body = re.sub(r'kitti_info_path:\s*"[^"]*"', f'kitti_info_path: "{info_path}"', body)
    body = re.sub(r'kitti_root_path:\s*"[^"]*"', f'kitti_root_path: "{root_path}"', body)
    if "kitti_info_path" not in body:
        body += f'\n  kitti_info_path: "{info_path}"'
    if "kitti_root_path" not in body:
        body += f'\n  kitti_root_path: "{root_path}"'
    return "eval_input_reader: {" + body + "\n}"


def parse_pointpillars_metrics(output_dir: Path) -> dict[str, Any]:
    summary = output_dir / "metrics_summary.json"
    if summary.exists():
        data = json.loads(summary.read_text(encoding="utf-8"))
        detection = compact_detection_metrics(data)
        detection["detectionText"] = format_detection_metrics(detection)
        return detection
    return {}



def write_fusiondet_eval_config_json(work_dir: Path, config_path: str | None = None) -> Path | None:
    if FUSIONDET_EVAL_CONFIG_JSON:
        path = Path(FUSIONDET_EVAL_CONFIG_JSON)
        return path if path.is_absolute() else FUSIONDET_ROOT / path
    config_path = config_path or "configs/conch_and_xinchi_occ/sanet-point-pillar02-centerhead-conch-11cls-fp16_occ.py"
    config_file = Path(config_path)
    if not config_file.is_absolute():
        config_file = FUSIONDET_ROOT / config_file
    if not config_file.exists():
        return None
    import importlib.util
    spec = importlib.util.spec_from_file_location("fusion_eval_cfg", str(config_file))
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cfg = getattr(mod, "eval_detection_configs", None)
    if not cfg:
        return None
    out = work_dir / "eval_detection_config.json"
    out.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return out
def pointpillars_predictions_from_eval_annos(eval_annos_path: Path, data_ids: list[int], class_map: dict[str, str] | None = None) -> dict[str, list[dict[str, Any]]]:
    class_map = class_map or {}
    with eval_annos_path.open("rb") as f:
        data = pickle.load(f)
    annos = data.get("dt_annos", data) if isinstance(data, dict) else data
    predictions: dict[str, list[dict[str, Any]]] = {}
    for data_id, anno in zip(data_ids, annos):
        boxes = np.asarray(anno.get("box3d_lidar", []), dtype=np.float32)
        names = list(anno.get("name", []))
        scores = np.asarray(anno.get("score", []), dtype=np.float32)
        frame_preds = []
        for index, box in enumerate(boxes):
            label = class_map.get(str(names[index]), str(names[index])) if index < len(names) else "unknown"
            score = float(scores[index]) if index < len(scores) else 0.0
            frame_preds.append({
                "source": "PRED",
                "color": "#ef4444",
                "label": label,
                "confidence": score,
                "displayText": f"{label} {score:.2f}",
                "box": {"x": float(box[0]), "y": float(box[1]), "z": float(box[2] + box[5] * 0.5), "dx": float(box[3]), "dy": float(box[4]), "dz": float(box[5]), "yaw": float(-box[6])},
            })
        predictions[str(data_id)] = frame_preds
    return predictions


def run_pointpillars_eval(payload: dict[str, Any]) -> dict[str, Any]:
    evaluation_id = int(payload["evaluationId"])
    data_ids = [int(x) for x in payload.get("dataIds", [])]
    raw_load_dim = payload.get("loadDim")
    load_dim = int(raw_load_dim) if raw_load_dim not in (None, "") else None
    metrics = [str(metric) for metric in payload.get("metrics") or ["mAP"] if str(metric) == "mAP"] or ["mAP"]
    fusion_infos_path, ordered_data_ids, miou_count = build_eval_pkl(evaluation_id, data_ids, ["mAP"])
    work_dir = WORK_ROOT / f"eval_{evaluation_id}"
    eval_config, _, _ = build_pointpillars_eval_assets(evaluation_id, fusion_infos_path, load_dim, payload.get("configPath"))
    output_dir = work_dir / "pointpillars_fusion_metric"
    fusion_eval_config = write_fusiondet_eval_config_json(work_dir, payload.get("configPath"))
    log_path = work_dir / "pointpillars_eval.log"
    checkpoint_path = str(payload.get("checkpointPath") or "")
    model_dir = Path(payload.get("modelDir") or POINTPILLARS_DEFAULT_MODEL_DIR)
    if checkpoint_path and not checkpoint_path.endswith(".pth"):
        ckpt_path = Path(checkpoint_path)
        if not ckpt_path.is_absolute():
            ckpt_path = POINTPILLARS_ROOT / ckpt_path
        if not ckpt_path.exists():
            ckpt_path = None
    else:
        ckpt_path = None
    class_map = json.loads(POINTPILLARS_CLASS_MAP or "{}")
    raw_result_dir = work_dir / "pointpillars_raw_eval"
    raw_cmd = [
        POINTPILLARS_RAW_EVAL_PYTHON,
        str(POINTPILLARS_ROOT / "second/pytorch/eval.py"),
        "evaluate",
        f"--config_path={eval_config}",
        f"--model_dir={model_dir}",
        f"--result_path={raw_result_dir}",
        "--save_fp_bev=False",
    ]
    if ckpt_path:
        raw_cmd.append(f"--ckpt_path={ckpt_path}")
    # eval.py is launched from second/pytorch, so the repository root is not
    # automatically importable. torchplus lives at that root.
    pointpillars_env = os.environ.copy()
    existing_pythonpath = pointpillars_env.get("PYTHONPATH")
    pointpillars_env["PYTHONPATH"] = str(POINTPILLARS_ROOT)
    if existing_pythonpath:
        pointpillars_env["PYTHONPATH"] += os.pathsep + existing_pythonpath
    raw_completed = subprocess.run(
        raw_cmd, cwd=str(POINTPILLARS_ROOT), text=True, capture_output=True,
        timeout=RUN_TIMEOUT_SEC, env=pointpillars_env,
    )
    candidates = sorted(raw_result_dir.glob("**/eval_annos.pkl"), key=lambda p: p.stat().st_mtime, reverse=True)
    eval_annos = candidates[0] if candidates else None

    metric_cmd = []
    metric_completed = None
    if raw_completed.returncode == 0 and eval_annos:
        metric_cmd = [
            POINTPILLARS_METRIC_PYTHON,
            str(POINTPILLARS_ROOT / "second/pytorch/eval_fusion_metric.py"),
            "from_eval_annos",
            "--pp_eval_annos_path", str(eval_annos),
            "--fusion_infos_path", str(fusion_infos_path),
            "--fusiondet_root", str(FUSIONDET_ROOT),
            "--output_dir", str(output_dir),
            "--class_map", json.dumps(class_map, ensure_ascii=False),
        ]
        if fusion_eval_config:
            metric_cmd.extend(["--eval_config_json", str(fusion_eval_config)])
        metric_completed = subprocess.run(
            metric_cmd, cwd=str(POINTPILLARS_ROOT), text=True, capture_output=True,
            timeout=RUN_TIMEOUT_SEC, env=pointpillars_env,
        )

    log_parts = [
        "$ " + " ".join(raw_cmd),
        "\nSTDOUT:\n" + raw_completed.stdout,
        "\nSTDERR:\n" + raw_completed.stderr,
    ]
    if metric_cmd:
        log_parts.extend([
            "\n$ " + " ".join(metric_cmd),
            "\nSTDOUT:\n" + (metric_completed.stdout if metric_completed else ""),
            "\nSTDERR:\n" + (metric_completed.stderr if metric_completed else ""),
        ])
    log_path.write_text("\n".join(log_parts), encoding="utf-8")
    if raw_completed.returncode != 0:
        raise RuntimeError(f"PointPillars raw evaluation failed, see {log_path}: {raw_completed.stderr[-1000:]}")
    if not eval_annos:
        raise RuntimeError(f"PointPillars raw evaluation did not produce eval_annos.pkl, see {log_path}")
    if metric_completed is None or metric_completed.returncode != 0:
        stderr = metric_completed.stderr[-1000:] if metric_completed else "metric process was not started"
        raise RuntimeError(f"PointPillars fusion metric failed, see {log_path}: {stderr}")
    predictions = pointpillars_predictions_from_eval_annos(eval_annos, ordered_data_ids, class_map) if eval_annos else {}
    return {
        "metrics": {**parse_pointpillars_metrics(output_dir), "requested": metrics, "engine": "pointpillars", "loadDim": load_dim},
        "miouDataCount": miou_count,
        "outputPath": str(output_dir),
        "logPath": str(log_path),
        "predictions": predictions,
    }

def run_eval(payload: dict[str, Any]) -> dict[str, Any]:
    if infer_evaluation_engine(payload) == "pointpillars":
        return run_pointpillars_eval(payload)
    evaluation_id = int(payload["evaluationId"])
    data_ids = [int(x) for x in payload.get("dataIds", [])]
    config_path = str(payload.get("configPath") or "configs/conch_and_xinchi_occ/sanet-point-pillar02-centerhead-conch-11cls-fp16_occ.py")
    checkpoint_path = str(payload.get("checkpointPath") or "work_dirs/occ/epoch_20_ema.pth")
    raw_load_dim = payload.get("loadDim")
    load_dim = int(raw_load_dim) if raw_load_dim not in (None, "") else None
    metrics = [str(metric) for metric in payload.get("metrics") or ["mAP", "miou"] if str(metric) in {"mAP", "miou"}]
    if not metrics:
        metrics = ["mAP", "miou"]
    ann_file, ordered_data_ids, miou_count = build_eval_pkl(evaluation_id, data_ids, metrics)
    work_dir = WORK_ROOT / f"eval_{evaluation_id}"
    outputs_path = work_dir / f"eval_{evaluation_id}_outputs.pkl"
    log_path = work_dir / "eval.log"
    result_prefix = work_dir / "results"
    runner_path = work_dir / "run_test.py"
    write_test_runner(runner_path)
    cmd = [
        PYTHON_BIN,
        str(runner_path),
        "--fusiondet-root", str(FUSIONDET_ROOT),
        "--test-script", str(TEST_SCRIPT),
        config_path,
        "--checkpoint", checkpoint_path,
        "--eval", *metrics,
        "--out", str(outputs_path),
        "--cfg-options", f"data.test.ann_file={ann_file}", *eval_cfg_options(load_dim, metrics),
        "--eval-options", f"jsonfile_prefix={result_prefix}", f"save_dir={result_prefix}",
    ]
    helper_env = os.environ.copy()
    helper_env.setdefault("NUMBA_DISABLE_CACHE", "1")
    helper_env["NUMBA_CACHE_DIR"] = str(work_dir / "numba_cache")
    completed = subprocess.run(
        cmd,
        cwd=str(FUSIONDET_ROOT),
        text=True,
        capture_output=True,
        timeout=RUN_TIMEOUT_SEC,
        env=helper_env,
    )
    log_path.write_text("$ " + " ".join(cmd) + "\n\nSTDOUT:\n" + completed.stdout + "\n\nSTDERR:\n" + completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(f"Evaluation failed, see {log_path}: {completed.stderr[-1000:]}")
    class_names = None
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("eval_cfg", str(FUSIONDET_ROOT / config_path))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)
        class_names = list(getattr(mod, "class_names", []))
    except Exception:
        class_names = None
    predictions = predictions_from_outputs(outputs_path, ordered_data_ids, class_names)
    return {
        "metrics": {**parse_metrics(completed.stdout, work_dir), "requested": metrics, "loadDim": load_dim},
        "miouDataCount": miou_count,
        "outputPath": str(outputs_path),
        "logPath": str(log_path),
        "predictions": predictions,
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health":
            json_response(self, HTTPStatus.OK, {"code": OK, "message": "ok"})
        else:
            json_response(self, HTTPStatus.NOT_FOUND, {"code": ERROR, "message": "not found"})

    def do_POST(self) -> None:
        if self.path.rstrip("/") != "/evaluate":
            json_response(self, HTTPStatus.NOT_FOUND, {"code": ERROR, "message": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            data = run_eval(payload)
            json_response(self, HTTPStatus.OK, {"code": OK, "message": "", "data": data})
        except Exception as exc:
            json_response(self, HTTPStatus.OK, {"code": ERROR, "message": str(exc), "data": None})

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=env("FUSIONDET_EVAL_SERVICE_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(env("FUSIONDET_EVAL_SERVICE_PORT", "8510")))
    args = parser.parse_args()
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"FusionDet evaluation adapter listening on {args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
