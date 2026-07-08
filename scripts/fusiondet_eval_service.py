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
import sys
import time
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
        f"WHERE id IN ({sql_list(file_ids)}) AND is_deleted=0"
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
    return box, str(obj.get("modelClass") or obj.get("label") or "unknown"), int(contour.get("pointN") or 1)


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
) -> tuple[str, dict[str, Any]]:
    lidar_rel = source["lidar"].relative_to(clip_root)
    timestamp = timestamp_from_lidar_name(source["lidar"].name)
    cam_files = {}
    for group_name, camera_path in sorted(source["cameras"].items()):
        rel = camera_path.relative_to(clip_root)
        cam_files[camera_key(group_name, rel)] = {
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
        '        "use_conch": True,',
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
            key, entry = frame_obstacle_entry(frame, source, clip_root, gt_map.get(int(frame["id"]), []))
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
    completed = subprocess.run(cmd, cwd=str(FUSIONDET_ROOT), text=True, capture_output=True, timeout=RUN_TIMEOUT_SEC)
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


def parse_metrics(stdout: str, work_dir: Path) -> dict[str, Any]:
    metrics: dict[str, Any] = {"raw": stdout[-20000:]}
    summary = work_dir / "results" / "metrics_summary.json"
    if summary.exists():
        data = json.loads(summary.read_text(encoding="utf-8"))
        metrics["mAP"] = data.get("mean_ap")
        metrics["NDS"] = data.get("nd_score")
        metrics["detection"] = data
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


def run_eval(payload: dict[str, Any]) -> dict[str, Any]:
    evaluation_id = int(payload["evaluationId"])
    data_ids = [int(x) for x in payload.get("dataIds", [])]
    config_path = str(payload.get("configPath") or "configs/conch_and_xinchi_occ/sanet-point-pillar02-centerhead-conch-11cls-fp16_occ.py")
    checkpoint_path = str(payload.get("checkpointPath") or "work_dirs/occ/epoch_20_ema.pth")
    metrics = [str(metric) for metric in payload.get("metrics") or ["mAP", "miou"] if str(metric) in {"mAP", "miou"}]
    if not metrics:
        metrics = ["mAP", "miou"]
    ann_file, ordered_data_ids, miou_count = build_eval_pkl(evaluation_id, data_ids, metrics)
    work_dir = WORK_ROOT / f"eval_{evaluation_id}"
    outputs_path = work_dir / f"eval_{evaluation_id}_outputs.pkl"
    log_path = work_dir / "eval.log"
    result_prefix = work_dir / "results"
    cmd = [
        PYTHON_BIN,
        str(TEST_SCRIPT),
        config_path,
        "--checkpoint", checkpoint_path,
        "--eval", *metrics,
        "--out", str(outputs_path),
        "--cfg-options", f"data.test.ann_file={ann_file}",
        "--eval-options", f"jsonfile_prefix={result_prefix}", f"save_dir={result_prefix}",
    ]
    completed = subprocess.run(cmd, cwd=str(FUSIONDET_ROOT), text=True, capture_output=True, timeout=RUN_TIMEOUT_SEC)
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
        "metrics": {**parse_metrics(completed.stdout, work_dir), "requested": metrics},
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
