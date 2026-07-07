#!/usr/bin/env python3
"""Platform evaluation adapter for FusionDet/SANet.

This service is intentionally separate from FusionDet's original tools/test.py.
It builds a temporary SANet ann_file from Xtreme1 selected data ids, invokes the
existing evaluation script, and returns metrics plus predictions for platform UI.
"""

from __future__ import annotations

import argparse
import json
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
BASE_INFO_PKL = Path(env("FUSIONDET_BASE_INFO_PKL", str(FUSIONDET_ROOT / "dataset/xinchi_infos_val.pkl")))
WORK_ROOT = Path(env("FUSIONDET_PLATFORM_EVAL_ROOT", str(FUSIONDET_ROOT / "work_dirs/platform_eval")))
MYSQL_BIN = env("MYSQL_BIN", "mysql")
MYSQL_DOCKER_CONTAINER = env("MYSQL_DOCKER_CONTAINER", "hb-wblabel-mysql-1")
MYSQL_HOST = env("XTREME1_MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = env("XTREME1_MYSQL_PORT", "8191")
MYSQL_USER = env("XTREME1_MYSQL_USER", "xtreme1")
MYSQL_PASSWORD = env("XTREME1_MYSQL_PASSWORD", "Rc4K3L6f")
MYSQL_DATABASE = env("XTREME1_MYSQL_DATABASE", "xtreme1")
RUN_TIMEOUT_SEC = int(env("FUSIONDET_EVAL_TIMEOUT_SEC", "21600"))


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
        "SELECT id,name,parent_id FROM data "
        f"WHERE id IN ({sql_list(data_ids)}) AND type='SINGLE_DATA' AND is_deleted=0"
    )
    return {int(row[0]): {"id": int(row[0]), "name": row[1], "parentId": int(row[2])} for row in rows}


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


def token_candidates(platform_name: str) -> set[str]:
    name = platform_name
    if name.startswith("LIDAR_"):
        name = name[6:]
    return {platform_name, name, f"LIDAR_{name}"}


def load_base_infos() -> dict[str, Any]:
    with BASE_INFO_PKL.open("rb") as f:
        return pickle.load(f)


def index_infos(infos: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for info in infos:
        values = [str(info.get("token", "")), Path(str(info.get("lidar_path", ""))).stem]
        for value in values:
            if value:
                index[value] = info
                if value.startswith("LIDAR_"):
                    index[value[6:]] = info
                else:
                    index[f"LIDAR_{value}"] = info
    return index


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


def apply_platform_gt(info: dict[str, Any], objects: list[dict[str, Any]]) -> dict[str, Any]:
    import numpy as np

    copied = dict(info)
    boxes, names, num_pts = [], [], []
    for obj in objects:
        box, name, points = object_to_box(obj)
        boxes.append(box)
        names.append(name)
        num_pts.append(points)
    copied["gt_boxes"] = np.asarray(boxes, dtype=np.float32).reshape((-1, 7))
    copied["gt_names"] = np.asarray(names)
    copied["num_lidar_pts"] = np.asarray(num_pts, dtype=np.int32)
    copied["gt_velocity"] = np.zeros((len(boxes), 2), dtype=np.float32)
    copied["valid_flag"] = np.ones((len(boxes),), dtype=bool)
    return copied


def build_eval_pkl(evaluation_id: int, data_ids: list[int]) -> tuple[Path, list[int], int]:
    frames = fetch_platform_frames(data_ids)
    gt_map = fetch_gt_objects(data_ids)
    base = load_base_infos()
    base_infos = base.get("infos", [])
    info_index = index_infos(base_infos)
    selected_infos = []
    ordered_data_ids = []
    miou_count = 0
    for data_id in data_ids:
        frame = frames.get(int(data_id))
        if not frame:
            continue
        matched = None
        for candidate in token_candidates(frame["name"]):
            matched = info_index.get(candidate)
            if matched is not None:
                break
        if matched is None:
            raise RuntimeError(f"Cannot map platform dataId={data_id}, name={frame['name']} to base info pkl")
        info = apply_platform_gt(matched, gt_map.get(int(data_id), []))
        info["platform_data_id"] = int(data_id)
        selected_infos.append(info)
        ordered_data_ids.append(int(data_id))
        if info.get("lidarseg_path") or info.get("occ_gt_path"):
            miou_count += 1
    out_dir = WORK_ROOT / f"eval_{evaluation_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    pkl_path = out_dir / f"eval_{evaluation_id}_infos.pkl"
    payload = dict(base)
    payload["infos"] = selected_infos
    with pkl_path.open("wb") as f:
        pickle.dump(payload, f)
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
    ann_file, ordered_data_ids, miou_count = build_eval_pkl(evaluation_id, data_ids)
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
