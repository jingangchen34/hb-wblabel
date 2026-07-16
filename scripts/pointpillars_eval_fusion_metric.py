# -*- coding: utf-8 -*-
"""Evaluate PointPillars outputs with FusionDet/SANet detection metrics.

This script is intentionally additive. It does not modify the original
second/pytorch/eval.py IoU evaluator. It converts PointPillars prediction
annotations into the same nuScenes-style center-distance metric used by
FusionDet/SANet, so one FusionDet-format test set can be the common release
standard for both models.
"""

import argparse
import json
import os
import pickle
import sys
import time
from pathlib import Path

import numpy as np


DEFAULT_EVAL_CONFIG = {
    "class_range": [-51.2, -51.2, -5.0, 102.4, 51.2, 3.0],
    "class_names": ["car", "truck", "cyclist", "pedestrian"],
    "dist_fcn": "center_distance",
    "dist_ths": [0.5, 1.0, 2.0, 4.0],
    "dist_th_tp": 2.0,
    "min_recall": 0.1,
    "min_precision": 0.1,
    "max_boxes_per_sample": 2000,
    "mean_ap_weight": 5,
}


def _load_fusiondet_metric_api(fusiondet_root):
    if fusiondet_root:
        fusiondet_root = str(Path(fusiondet_root).resolve())
        if fusiondet_root not in sys.path:
            sys.path.insert(0, fusiondet_root)

    from nuscenes.eval.common.data_classes import EvalBoxes
    from nuscenes.eval.detection.algo import accumulate, calc_ap, calc_tp
    from nuscenes.eval.detection.constants import TP_METRICS
    from nuscenes.eval.detection.data_classes import (
        DetectionMetricDataList,
        DetectionMetrics,
    )
    from mmdet3d.eval.detection.data_classes import (
        SANetDetectionBox,
        SANetDetectionConfig,
    )
    from mmdet3d.eval.sanet_eval import add_center_dist, filter_eval_boxes

    return {
        "EvalBoxes": EvalBoxes,
        "accumulate": accumulate,
        "calc_ap": calc_ap,
        "calc_tp": calc_tp,
        "TP_METRICS": TP_METRICS,
        "DetectionMetricDataList": DetectionMetricDataList,
        "DetectionMetrics": DetectionMetrics,
        "SANetDetectionBox": SANetDetectionBox,
        "SANetDetectionConfig": SANetDetectionConfig,
        "add_center_dist": add_center_dist,
        "filter_eval_boxes": filter_eval_boxes,
    }


def _load_eval_config(path, class_names=None, class_range=None):
    if path:
        with open(path, "r") as f:
            cfg = json.load(f)
    else:
        cfg = dict(DEFAULT_EVAL_CONFIG)

    if class_names:
        cfg["class_names"] = [item.strip() for item in class_names.split(",") if item.strip()]
    if class_range:
        values = [float(item) for item in class_range.split(",") if item.strip()]
        if len(values) != 6:
            raise ValueError("--class_range must contain 6 comma-separated numbers")
        cfg["class_range"] = values
    return cfg


def _load_fusion_infos(path):
    with open(path, "rb") as f:
        data = pickle.load(f)
    if isinstance(data, dict) and "infos" in data:
        return list(data["infos"])
    if isinstance(data, (list, tuple)):
        return list(data)
    raise TypeError("Unsupported fusion infos format: expected list or dict with key 'infos'")


def _load_pickle(path):
    with open(path, "rb") as f:
        return pickle.load(f)


def _sample_token(info, index):
    for key in ("token", "sample_token", "image_idx", "FrameID", "frame_id"):
        if key in info and info[key] is not None:
            return str(info[key])
    lidar_path = info.get("lidar_path") or info.get("velodyne_path")
    if lidar_path:
        return Path(lidar_path).stem
    return str(index)


def _rotation_elements(yaw):
    from pyquaternion import Quaternion

    return Quaternion(axis=[0, 0, 1], angle=float(yaw)).elements.tolist()


def _as_2d_velocity(value):
    if value is None:
        return [0.0, 0.0]
    arr = np.asarray(value, dtype=np.float32).reshape(-1)
    if arr.size >= 2 and np.all(np.isfinite(arr[:2])):
        return [float(arr[0]), float(arr[1])]
    return [0.0, 0.0]


def _as_score_array(anno, count):
    for key in ("score", "scores", "scores_3d"):
        if key in anno:
            scores = np.asarray(anno[key], dtype=np.float32).reshape(-1)
            if scores.size == count:
                return scores
    return np.ones((count,), dtype=np.float32)


def _normalize_pp_class_name(name, class_map):
    name = str(name)
    return class_map.get(name, class_map.get(name.lower(), name))


def _extract_gt_arrays(info):
    if "gt_boxes" in info:
        boxes = np.asarray(info["gt_boxes"], dtype=np.float32)
        names = np.asarray(info.get("gt_names", info.get("gt_classes", [])))
        return boxes, names
    annos = info.get("annos", {})
    if annos:
        loc = np.asarray(annos.get("location", []), dtype=np.float32)
        dims = np.asarray(annos.get("dimensions", []), dtype=np.float32)
        rots = np.asarray(annos.get("rotation_y", []), dtype=np.float32).reshape(-1, 1)
        names = np.asarray(annos.get("name", []))
        if loc.size and dims.size and rots.size:
            boxes = np.concatenate([loc, dims, rots], axis=1)
            return boxes, names
    return np.zeros((0, 7), dtype=np.float32), np.asarray([])


def _build_gt_eval_boxes(fusion_infos, api, class_names, class_map):
    EvalBoxes = api["EvalBoxes"]
    Box = api["SANetDetectionBox"]
    eval_boxes = EvalBoxes()
    tokens = []

    for index, info in enumerate(fusion_infos):
        token = _sample_token(info, index)
        tokens.append(token)
        boxes, names = _extract_gt_arrays(info)
        boxes = np.asarray(boxes, dtype=np.float32)
        names = np.asarray(names)

        rotations = info.get("gt_rotation")
        velocities = info.get("gt_velocity")
        lidar_pts = info.get("num_lidar_pts")
        sample_boxes = []

        for box_idx, box in enumerate(boxes):
            if box.shape[0] < 7:
                continue
            name = _normalize_pp_class_name(names[box_idx], class_map) if box_idx < len(names) else ""
            if name not in class_names:
                continue

            x, y, z, dx, dy, dz, yaw = [float(v) for v in box[:7]]
            if rotations is not None and box_idx < len(rotations):
                rotation = np.asarray(rotations[box_idx], dtype=np.float32).reshape(-1).tolist()
            else:
                rotation = _rotation_elements(yaw)
            velocity = _as_2d_velocity(velocities[box_idx] if velocities is not None and box_idx < len(velocities) else None)
            num_pts = int(lidar_pts[box_idx]) if lidar_pts is not None and box_idx < len(lidar_pts) else 1
            sample_boxes.append(
                Box(
                    sample_token=token,
                    translation=[x, y, z],
                    size=[dy, dx, dz],
                    rotation=rotation,
                    velocity=velocity,
                    ego_translation=(0.0, 0.0, 0.0),
                    num_pts=num_pts,
                    detection_name=name,
                    detection_score=-1.0,
                    attribute_name=name,
                )
            )
        eval_boxes.add_boxes(token, sample_boxes)

    return eval_boxes, tokens


def _build_prediction_eval_boxes(pp_eval_annos, tokens, api, class_names, class_map):
    EvalBoxes = api["EvalBoxes"]
    Box = api["SANetDetectionBox"]
    eval_boxes = EvalBoxes()

    for index, token in enumerate(tokens):
        anno = pp_eval_annos[index] if index < len(pp_eval_annos) else {}
        boxes = np.asarray(
            anno.get("box3d_lidar", anno.get("boxes_lidar", [])),
            dtype=np.float32,
        )
        names = np.asarray(anno.get("name", []))
        if boxes.ndim == 1 and boxes.size:
            boxes = boxes.reshape(1, -1)
        scores = _as_score_array(anno, len(boxes))

        sample_boxes = []
        for box_idx, box in enumerate(boxes):
            if box.shape[0] < 7:
                continue
            name = _normalize_pp_class_name(names[box_idx], class_map) if box_idx < len(names) else ""
            if name not in class_names:
                continue

            x, y, z_bottom, dx, dy, dz, pp_yaw = [float(v) for v in box[:7]]
            center_z = z_bottom + dz * 0.5
            # SECOND/PointPillars uses the opposite positive yaw direction from
            # FusionDet LiDAR boxes, so convert back to FusionDet convention.
            fusion_yaw = -pp_yaw
            sample_boxes.append(
                Box(
                    sample_token=token,
                    translation=[x, y, center_z],
                    size=[dy, dx, dz],
                    rotation=_rotation_elements(fusion_yaw),
                    velocity=[0.0, 0.0],
                    ego_translation=(0.0, 0.0, 0.0),
                    num_pts=-1,
                    detection_name=name,
                    detection_score=float(scores[box_idx]),
                    attribute_name=name,
                )
            )
        eval_boxes.add_boxes(token, sample_boxes)

    return eval_boxes


def _format_summary(metrics_summary):
    lines = [
        "mAP: %.4f" % metrics_summary["mean_ap"],
        "mATE: %.4f" % metrics_summary["tp_errors"].get("trans_err", 1.0),
        "mASE: %.4f" % metrics_summary["tp_errors"].get("scale_err", 1.0),
        "mAOE: %.4f" % metrics_summary["tp_errors"].get("orient_err", 1.0),
        "mAVE: %.4f" % metrics_summary["tp_errors"].get("vel_err", 1.0),
        "mAAE: %.4f" % metrics_summary["tp_errors"].get("attr_err", 1.0),
        "NDS: %.4f" % metrics_summary["nd_score"],
        "Per-class results:",
        "Object Class\tAP\tATE\tASE\tAOE\tAVE\tAAE",
    ]
    for name, item in metrics_summary["label_tp_errors"].items():
        lines.append(
            "%s\t%.3f\t%.3f\t%.3f\t%.3f\t%.3f\t%.3f"
            % (
                name,
                metrics_summary["mean_dist_aps"].get(name, 0.0),
                item.get("trans_err", 1.0),
                item.get("scale_err", 1.0),
                item.get("orient_err", 1.0),
                item.get("vel_err", 1.0),
                item.get("attr_err", 1.0),
            )
        )
    return "\n".join(lines)


SAFETY_FALSE_DETECTION_BANDS = (
    (0.0, 0.0),
    (0.0, 0.03),
    (0.03, 0.05),
    (0.05, 0.08),
    (0.08, 0.10),
)


def analyze_safety_thresholds(gt_boxes, pred_boxes, class_names, dist_threshold):
    sample_tokens = list(dict.fromkeys(list(gt_boxes.sample_tokens) + list(pred_boxes.sample_tokens)))
    frame_indices = {token: index for index, token in enumerate(sample_tokens)}
    results = []
    for class_name in class_names:
        frame_gt = {
            token: [box for box in gt_boxes[token] if box.detection_name == class_name]
            for token in sample_tokens
        }
        unmatched_gt = {token: set(range(len(boxes))) for token, boxes in frame_gt.items()}
        frame_fp = {token: 0 for token in sample_tokens}
        predictions = sorted(
            [(int(max(0.0, min(1.0, float(box.detection_score))) * 10000) / 10000.0,
              float(box.detection_score), token, box)
             for token in sample_tokens for box in pred_boxes[token]
             if box.detection_name == class_name],
            key=lambda item: (item[0], item[1]),
            reverse=True,
        )
        total_gt = sum(len(boxes) for boxes in frame_gt.values())
        tp = fp = 0
        scans = []

        def snapshot(threshold):
            predicted_count = tp + fp
            scans.append({
                "threshold": float(threshold),
                "TP": tp,
                "FP": fp,
                "FN": total_gt - tp,
                "falseDetectionRate": float(fp / predicted_count) if predicted_count else 0.0,
                "missRate": float((total_gt - tp) / total_gt) if total_gt else 0.0,
                "falsePositiveFrameIndices": [frame_indices[token] for token in sample_tokens if frame_fp[token]],
                "missedFrameIndices": [frame_indices[token] for token in sample_tokens if unmatched_gt[token]],
            })

        index = 0
        while index < len(predictions):
            threshold = predictions[index][0]
            snapshot(round(threshold + 0.0001, 4))
            while index < len(predictions) and predictions[index][0] == threshold:
                _, _, token, prediction = predictions[index]
                nearest_index = None
                nearest_distance = None
                for gt_index in unmatched_gt[token]:
                    gt = frame_gt[token][gt_index]
                    distance = float(
                        ((prediction.translation[0] - gt.translation[0]) ** 2
                         + (prediction.translation[1] - gt.translation[1]) ** 2) ** 0.5
                    )
                    if distance <= dist_threshold and (nearest_distance is None or distance < nearest_distance):
                        nearest_index = gt_index
                        nearest_distance = distance
                if nearest_index is None:
                    fp += 1
                    frame_fp[token] += 1
                else:
                    tp += 1
                    unmatched_gt[token].remove(nearest_index)
                index += 1
            snapshot(threshold)
        if not scans:
            snapshot(1.0)

        unique_scans = {item["threshold"]: item for item in scans}
        curve = []
        for item in unique_scans.values():
            curve.append({
                "threshold": item["threshold"],
                "precision": 1.0 - item["falseDetectionRate"],
                "recall": 1.0 - item["missRate"],
                "falseDetectionRate": item["falseDetectionRate"],
                "missRate": item["missRate"],
            })
        if len(curve) > 400:
            indices = sorted({round(index * (len(curve) - 1) / 399) for index in range(400)})
            curve = [curve[index] for index in indices]

        recommendations = []
        for rate_min, rate_max in SAFETY_FALSE_DETECTION_BANDS:
            if rate_min == rate_max == 0.0:
                feasible = [item for item in unique_scans.values()
                            if item["falseDetectionRate"] <= 1e-12]
            else:
                feasible = [item for item in unique_scans.values()
                            if rate_min + 1e-12 < item["falseDetectionRate"] <= rate_max + 1e-12]
            if feasible:
                best = min(feasible, key=lambda item: (item["missRate"], item["threshold"], item["FP"]))
                recommendation = dict(best)
                recommendation["available"] = bool(predictions)
                if not predictions:
                    recommendation.pop("threshold", None)
            else:
                recommendation = {
                    "available": False,
                    "falsePositiveFrameIndices": [],
                    "missedFrameIndices": [],
                }
            recommendation["falseDetectionRateMin"] = rate_min
            recommendation["falseDetectionRateMax"] = rate_max
            recommendations.append(recommendation)
        results.append({"className": class_name, "curve": curve, "recommendations": recommendations})
    return results


def evaluate_sanet_metric(gt_boxes, pred_boxes, api, eval_config, output_dir, verbose=True):
    SANetDetectionConfig = api["SANetDetectionConfig"]
    DetectionMetricDataList = api["DetectionMetricDataList"]
    DetectionMetrics = api["DetectionMetrics"]
    TP_METRICS = api["TP_METRICS"]

    cfg = SANetDetectionConfig.deserialize(eval_config)
    os.makedirs(output_dir, exist_ok=True)

    gt_boxes = api["add_center_dist"](gt_boxes)
    gt_boxes = api["filter_eval_boxes"](gt_boxes, cfg.class_range)
    pred_boxes = api["add_center_dist"](pred_boxes)
    pred_boxes = api["filter_eval_boxes"](pred_boxes, cfg.class_range)

    safety_thresholds = analyze_safety_thresholds(
        gt_boxes, pred_boxes, cfg.class_names, cfg.dist_th_tp
    )

    metric_data_list = DetectionMetricDataList()
    for class_name in cfg.class_names:
        for dist_th in cfg.dist_ths:
            metric_data = api["accumulate"](
                gt_boxes,
                pred_boxes,
                class_name,
                cfg.dist_fcn_callable,
                dist_th,
                verbose=verbose,
            )
            metric_data_list.set(class_name, dist_th, metric_data)

    metrics = DetectionMetrics(cfg)
    for class_name in cfg.class_names:
        for dist_th in cfg.dist_ths:
            metric_data = metric_data_list[(class_name, dist_th)]
            ap = api["calc_ap"](metric_data, cfg.min_recall, cfg.min_precision)
            metrics.add_label_ap(class_name, dist_th, ap)
        for metric_name in TP_METRICS:
            metric_data = metric_data_list[(class_name, cfg.dist_th_tp)]
            tp = api["calc_tp"](metric_data, cfg.min_recall, metric_name)
            metrics.add_label_tp(class_name, metric_name, tp)

    metrics_summary = metrics.serialize()
    metrics_summary["eval_time"] = time.time()
    metrics_summary["safety_thresholds"] = safety_thresholds

    with open(os.path.join(output_dir, "metrics_summary.json"), "w") as f:
        json.dump(metrics_summary, f, indent=2, sort_keys=True)
    with open(os.path.join(output_dir, "metrics_details.json"), "w") as f:
        json.dump(metric_data_list.serialize(), f, indent=2, sort_keys=True)

    summary_text = _format_summary(metrics_summary)
    with open(os.path.join(output_dir, "metrics_summary.txt"), "w") as f:
        f.write(summary_text + "\n")
    print(summary_text)
    return metrics_summary


def run_from_eval_annos(args):
    api = _load_fusiondet_metric_api(args.fusiondet_root)
    eval_config = _load_eval_config(args.eval_config_json, args.class_names, args.class_range)
    class_names = set(eval_config["class_names"])
    class_map = json.loads(args.class_map) if args.class_map else {}

    fusion_infos = _load_fusion_infos(args.fusion_infos_path)
    raw_eval_annos = _load_pickle(args.pp_eval_annos_path)
    pp_eval_annos = raw_eval_annos.get("dt_annos", raw_eval_annos) if isinstance(raw_eval_annos, dict) else raw_eval_annos
    gt_boxes, tokens = _build_gt_eval_boxes(fusion_infos, api, class_names, class_map)
    pred_boxes = _build_prediction_eval_boxes(pp_eval_annos, tokens, api, class_names, class_map)
    return evaluate_sanet_metric(gt_boxes, pred_boxes, api, eval_config, args.output_dir, args.verbose)


def run_pointpillars_then_eval(args):
    import second.pytorch.eval as pp_eval

    eval_result = pp_eval.evaluate(
        args.config_path,
        args.model_dir,
        result_path=args.result_path,
        ckpt_path=args.ckpt_path,
        class_names=args.pp_class_names,
        eval_batch_size=args.eval_batch_size,
        debug_iou=args.debug_iou,
        debug_max_frames=args.debug_max_frames,
        max_false_detection_rate=args.max_false_detection_rate,
        fixed_thresholds=args.fixed_thresholds,
        save_fp_bev=False,
        fp_bev_max_frames_per_class=args.fp_bev_max_frames_per_class,
    )
    eval_annos_path = os.path.join(eval_result["output_dir"], "eval_annos.pkl")
    args.pp_eval_annos_path = eval_annos_path
    if args.output_dir is None:
        args.output_dir = os.path.join(eval_result["output_dir"], "fusion_metric")
    return run_from_eval_annos(args)


def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="PointPillars evaluation using FusionDet/SANet metrics."
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.required = True

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--fusion_infos_path", required=True, help="FusionDet-format info pkl for the same test set.")
    common.add_argument("--fusiondet_root", default="/home/user/cjg/code/fusiondet", help="Path to FusionDet repo.")
    common.add_argument("--eval_config_json", default=None, help="JSON dumped from FusionDet eval_detection_configs.")
    common.add_argument("--class_names", default=None, help="Override eval class names, comma-separated.")
    common.add_argument("--class_range", default=None, help="Override eval class range: x_min,y_min,z_min,x_max,y_max,z_max.")
    common.add_argument("--class_map", default=None, help="JSON class-name map from PointPillars/Fusion infos to FusionDet names.")
    common.add_argument("--output_dir", default=None, help="Directory for metrics_summary.json/txt.")
    common.add_argument("--verbose", action="store_true")

    from_annos = subparsers.add_parser("from_eval_annos", parents=[common])
    from_annos.add_argument("--pp_eval_annos_path", required=True, help="PointPillars eval_annos.pkl generated by second/pytorch/eval.py.")
    from_annos.set_defaults(func=run_from_eval_annos)

    evaluate = subparsers.add_parser("evaluate", parents=[common])
    evaluate.add_argument("config_path")
    evaluate.add_argument("model_dir")
    evaluate.add_argument("--result_path", default=None)
    evaluate.add_argument("--ckpt_path", default=None)
    evaluate.add_argument("--pp_class_names", nargs="+", default=None)
    evaluate.add_argument("--eval_batch_size", type=int, default=1)
    evaluate.add_argument("--debug_iou", action="store_true")
    evaluate.add_argument("--debug_max_frames", type=int, default=5)
    evaluate.add_argument("--max_false_detection_rate", type=float, default=0.03)
    evaluate.add_argument("--fixed_thresholds", default=None)
    evaluate.add_argument("--fp_bev_max_frames_per_class", type=int, default=None)
    evaluate.set_defaults(func=run_pointpillars_then_eval)

    return parser


def main():
    parser = build_arg_parser()
    args = parser.parse_args()
    if args.output_dir is None and args.command == "from_eval_annos":
        args.output_dir = str(Path(args.pp_eval_annos_path).resolve().parent / "fusion_metric")
    args.func(args)


if __name__ == "__main__":
    main()

