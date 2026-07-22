#!/usr/bin/env python3
"""Register an external KITTI LiDAR dataset in Xtreme1 without copying files.

The KITTI annotations are in camera coordinates.  This importer can read either
raw ``label_2`` + ``calib`` files or PointPillars/SANet ``kitti_infos_*.pkl``
files, applies the same ``box_camera_to_lidar`` convention as the training code,
and writes LiDAR-only Xtreme1 frames that reference files through the external
read-only mount.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import mimetypes
import pickle
from collections.abc import Iterable, Iterator
from pathlib import Path


CLASS_COLORS = (
    "#FF7A00", "#00D084", "#2F80ED", "#EB5757",
    "#9B51E0", "#00B8D9", "#F2C94C", "#27AE60",
)


def sql_str(value: object | None) -> str:
    if value is None:
        return "NULL"
    return "'" + str(value).replace("\\", "\\\\").replace("'", "''") + "'"


def json_sql(value: object) -> str:
    return sql_str(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def rel_posix(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def path_hash(path: str) -> int:
    return int.from_bytes(hashlib.md5(path.encode("utf-8")).digest()[:8], "big", signed=True)


def class_color(name: str) -> str:
    digest = int(hashlib.md5(name.lower().encode("utf-8")).hexdigest()[:8], 16)
    return CLASS_COLORS[digest % len(CLASS_COLORS)]


def file_sql(path: Path, root: Path, bucket_name: str, user_id: int, variable: str) -> list[str]:
    relative = rel_posix(path, root)
    file_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return [
        "INSERT INTO `file` "
        "(`name`,`original_name`,`path`,`path_hash`,`type`,`size`,`bucket_name`,`created_at`,`created_by`,`updated_at`,`updated_by`) "
        f"VALUES ({sql_str(path.name)},{sql_str(path.name)},{sql_str(relative)},{path_hash(relative)},"
        f"{sql_str(file_type)},{path.stat().st_size},{sql_str(bucket_name)},NOW(),{user_id},NOW(),{user_id}) "
        "ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id),`name`=VALUES(`name`),`original_name`=VALUES(`original_name`),"
        "`type`=VALUES(`type`),`size`=VALUES(`size`),`bucket_name`=VALUES(`bucket_name`),updated_at=NOW(),updated_by=VALUES(updated_by);",
        f"SET {variable}=LAST_INSERT_ID();",
    ]


def parse_calib(path: Path) -> tuple[list[list[float]], list[list[float]]]:
    values: dict[str, list[float]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, raw = line.partition(":")
        if not sep:
            continue
        try:
            values[key.strip()] = [float(value) for value in raw.split()]
        except ValueError:
            continue
    rect_values = values.get("R0_rect") or values.get("R_rect")
    velo_values = values.get("Tr_velo_to_cam") or values.get("Tr_velo_cam")
    if len(rect_values or []) != 9 or len(velo_values or []) != 12:
        raise ValueError(f"invalid KITTI calibration: {path}")
    rect = [[0.0] * 4 for _ in range(4)]
    velo = [[0.0] * 4 for _ in range(4)]
    rect[3][3] = velo[3][3] = 1.0
    for row in range(3):
        for col in range(3):
            rect[row][col] = rect_values[row * 3 + col]
        for col in range(4):
            velo[row][col] = velo_values[row * 4 + col]
    return rect, velo


def as_matrix(values: object, rows: int, cols: int) -> list[list[float]]:
    if hasattr(values, "tolist"):
        values = values.tolist()
    if isinstance(values, list) and values and isinstance(values[0], list):
        matrix = [[float(value) for value in row[:cols]] for row in values[:rows]]
    else:
        flat = [float(value) for value in values]  # type: ignore[arg-type]
        matrix = [[flat[row * cols + col] for col in range(cols)] for row in range(rows)]
    if rows == 3 and cols == 3:
        matrix = [row + [0.0] for row in matrix] + [[0.0, 0.0, 0.0, 1.0]]
    elif rows == 3 and cols == 4:
        matrix = matrix + [[0.0, 0.0, 0.0, 1.0]]
    return matrix


def matmul(left: list[list[float]], right: list[list[float]]) -> list[list[float]]:
    return [[sum(left[row][k] * right[k][col] for k in range(4)) for col in range(4)] for row in range(4)]


def invert_4x4(matrix: list[list[float]]) -> list[list[float]]:
    augmented = [row[:] + [1.0 if row_index == col else 0.0 for col in range(4)] for row_index, row in enumerate(matrix)]
    for column in range(4):
        pivot = max(range(column, 4), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            raise ValueError("singular KITTI calibration matrix")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        factor = augmented[column][column]
        augmented[column] = [value / factor for value in augmented[column]]
        for row in range(4):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [value - factor * pivot_value for value, pivot_value in zip(augmented[row], augmented[column])]
    return [row[4:] for row in augmented]


def lidar_inverse(rect: list[list[float]], velo: list[list[float]]) -> list[list[float]]:
    # Equivalent to box_np_ops.camera_to_lidar: point @ inv((R0_rect @ Tr_velo_to_cam).T).
    return invert_4x4(matmul(rect, velo))


def camera_to_lidar(location: tuple[float, float, float], inverse: list[list[float]]) -> tuple[float, float, float]:
    x, y, z = location
    return (
        inverse[0][0] * x + inverse[0][1] * y + inverse[0][2] * z + inverse[0][3],
        inverse[1][0] * x + inverse[1][1] * y + inverse[1][2] * z + inverse[1][3],
        inverse[2][0] * x + inverse[2][1] * y + inverse[2][2] * z + inverse[2][3],
    )


def normalize_yaw(yaw: float) -> float:
    while yaw > math.pi:
        yaw -= math.tau
    while yaw <= -math.pi:
        yaw += math.tau
    return yaw


def kitti_box_to_xtreme1_center(
    location: tuple[float, float, float],
    height: float,
    rotation_y: float,
    inverse: list[list[float]],
) -> tuple[tuple[float, float, float], float]:
    # KITTI labels store the 3D location at the object bottom center in camera
    # coordinates. Xtreme1 renders boxes around their geometric center.
    x, y, z = camera_to_lidar(location, inverse)
    return (x, y, z + height / 2.0), normalize_yaw(-rotation_y)


def parse_labels(path: Path, rect: list[list[float]], velo: list[list[float]]) -> list[dict[str, object]]:
    objects: list[dict[str, object]] = []
    inverse = lidar_inverse(rect, velo)
    for index, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        fields = line.split()
        if len(fields) < 15 or fields[0].lower() == "dontcare":
            continue
        try:
            height, width, length = (float(fields[8]), float(fields[9]), float(fields[10]))
            location = (float(fields[11]), float(fields[12]), float(fields[13]))
            rotation_y = float(fields[14])
        except ValueError:
            continue
        (x, y, z), yaw = kitti_box_to_xtreme1_center(location, height, rotation_y, inverse)
        if not all(math.isfinite(value) for value in (x, y, z, width, length, height, yaw)):
            continue
        objects.append({
            "className": fields[0],
            "trackID": f"{path.stem}-{index}",
            "center3D": {"x": x, "y": y, "z": z},
            "size3D": {"x": width, "y": length, "z": height},
            "rotation3D": {"x": 0.0, "y": 0.0, "z": yaw},
        })
    return objects


def scalar(value: object) -> object:
    return value.item() if hasattr(value, "item") else value


def rows(values: object) -> list[object]:
    if hasattr(values, "tolist"):
        return values.tolist()
    return list(values)  # type: ignore[arg-type]


def pkl_annotations(info: dict[str, object]) -> list[dict[str, object]]:
    annos = info.get("annos")
    if not isinstance(annos, dict):
        return []
    names = rows(annos.get("name", []))
    locations = rows(annos.get("location", []))
    dimensions = rows(annos.get("dimensions", []))
    rotations = rows(annos.get("rotation_y", []))
    rect = as_matrix(info["calib/R0_rect"], 3, 3)
    velo = as_matrix(info["calib/Tr_velo_to_cam"], 3, 4)
    inverse = lidar_inverse(rect, velo)

    objects: list[dict[str, object]] = []
    for index, name in enumerate(names, start=1):
        class_name = str(scalar(name))
        if class_name.lower() == "dontcare" or index > len(locations) or index > len(dimensions) or index > len(rotations):
            continue
        try:
            location_values = [float(value) for value in locations[index - 1]]
            dimension_values = [float(value) for value in dimensions[index - 1]]
            rotation_y = float(scalar(rotations[index - 1]))
        except (TypeError, ValueError):
            continue
        if len(location_values) < 3 or len(dimension_values) < 3:
            continue
        length, height, width = dimension_values[:3]
        (x, y, z), yaw = kitti_box_to_xtreme1_center(tuple(location_values[:3]), height, rotation_y, inverse)
        if not all(math.isfinite(value) for value in (x, y, z, width, length, height, yaw)):
            continue
        frame_name = str(scalar(info.get("image_idx", ""))) or Path(str(info.get("velodyne_path", ""))).stem
        objects.append({
            "className": class_name,
            "trackID": f"{frame_name}-{index}",
            "center3D": {"x": x, "y": y, "z": z},
            "size3D": {"x": width, "y": length, "z": height},
            "rotation3D": {"x": 0.0, "y": 0.0, "z": yaw},
        })
    return objects


def annotation_sql(annotation: dict[str, object], dataset_var: str, class_var: str, user_id: int) -> str:
    contour = json_sql({
        "center3D": annotation["center3D"],
        "size3D": annotation["size3D"],
        "rotation3D": annotation["rotation3D"],
    })
    attributes = (
        "JSON_OBJECT('id',REPLACE(UUID(),'-',''),'type','3D_BOX','version',0,"
        f"'trackID',{sql_str(annotation['trackID'])},'trackId',{sql_str(annotation['trackID'])},"
        f"'trackName',{sql_str(annotation['trackID'])},'classId',{class_var},"
        f"'className',{sql_str(annotation['className'])},'classValues',JSON_ARRAY(),'contour',CAST({contour} AS JSON))"
    )
    return (
        "INSERT INTO `data_annotation_object` "
        "(`dataset_id`,`data_id`,`class_id`,`class_attributes`,`source_type`,`source_id`,`created_at`,`created_by`,`updated_at`,`updated_by`) "
        f"VALUES ({dataset_var},@data_id,{class_var},{attributes},'IMPORTED',-1,NOW(),{user_id},NOW(),{user_id});"
    )


def frame_paths(dataset_dir: Path, limit: int | None) -> Iterator[Path]:
    files = sorted((dataset_dir / "training" / "velodyne").glob("*.bin"))
    yield from files if limit is None else files[:limit]


def pkl_paths(dataset_dir: Path, split: str) -> list[tuple[str, Path]]:
    splits = ["train", "val"] if split == "all" else [split]
    paths = [(name, dataset_dir / f"kitti_infos_{name}.pkl") for name in splits]
    missing = [path for _, path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError("missing KITTI info pkl: " + ", ".join(str(path) for path in missing))
    return paths


def iter_pkl_frames(dataset_dir: Path, split: str, limit: int | None) -> Iterator[tuple[Path, list[dict[str, object]], str]]:
    yielded = 0
    split_map = {"train": "TRAINING", "val": "VALIDATION", "test": "TEST"}
    for split_name, pkl_path in pkl_paths(dataset_dir, split):
        with pkl_path.open("rb") as handle:
            infos = pickle.load(handle)
        for info in infos:
            if limit is not None and yielded >= limit:
                return
            if not isinstance(info, dict) or "velodyne_path" not in info:
                continue
            lidar = dataset_dir / str(info["velodyne_path"])
            if not lidar.is_file():
                continue
            yielded += 1
            yield lidar, pkl_annotations(info), split_map.get(split_name, "NOT_SPLIT")


def iter_label_frames(dataset_dir: Path, limit: int | None) -> Iterator[tuple[Path, list[dict[str, object]], str]]:
    for lidar in frame_paths(dataset_dir, limit):
        label = dataset_dir / "training" / "label_2" / f"{lidar.stem}.txt"
        calib = dataset_dir / "training" / "calib" / f"{lidar.stem}.txt"
        if not label.is_file() or not calib.is_file():
            continue
        try:
            rect, velo = parse_calib(calib)
            yield lidar, parse_labels(label, rect, velo), "NOT_SPLIT"
        except (OSError, ValueError) as exc:
            print(f"Skip {lidar}: {exc}")


def scene_name(split_type: str, scene_index: int) -> str:
    prefixes = {"TRAINING": "train", "VALIDATION": "val", "TEST": "test"}
    return f"{prefixes.get(split_type, 'clip')}_{scene_index:06d}"


def selected_pkl_split_types(split: str) -> list[str]:
    mapping = {"train": ["TRAINING"], "val": ["VALIDATION"], "all": ["TRAINING", "VALIDATION"]}
    return mapping[split]


def write_scene(
    output,
    dataset_var: str,
    scene_var: str,
    scene: str,
    split_type: str,
    args: argparse.Namespace,
) -> None:
    output.write(
        "INSERT INTO `data` (`dataset_id`,`name`,`order_name`,`content`,`type`,`parent_id`,`status`,`annotation_status`,`split_type`,`is_deleted`,`del_unique_key`,`created_at`,`created_by`,`updated_at`,`updated_by`) "
        f"VALUES ({dataset_var},{sql_str(scene)},{sql_str(scene)},JSON_ARRAY(),'SCENE',0,'VALID','ANNOTATED',{sql_str(split_type)},b'0',0,NOW(),{args.user_id},NOW(),{args.user_id}) "
        "ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id),`order_name`=VALUES(`order_name`),`annotation_status`=VALUES(`annotation_status`),`split_type`=VALUES(`split_type`),updated_at=NOW(),updated_by=VALUES(updated_by);\n"
    )
    output.write(f"SET {scene_var}=LAST_INSERT_ID();\n\n")


def write_dataset(output, root: Path, dataset_dir: Path, args: argparse.Namespace, dataset_index: int) -> tuple[int, int]:
    dataset_name = f"pp_data/{dataset_dir.name}"
    dataset_var = f"@dataset_{dataset_index}"
    output.write(f"-- Dataset: {dataset_name}\n")
    output.write(
        "INSERT INTO `dataset` (`name`,`type`,`description`,`is_deleted`,`del_unique_key`,`created_at`,`created_by`,`updated_at`,`updated_by`) "
        f"VALUES ({sql_str(dataset_name)},'LIDAR_BASIC',{sql_str('Haibo collected KITTI LiDAR data; labels converted from camera to LiDAR coordinates')},b'0',0,NOW(),{args.user_id},NOW(),{args.user_id}) "
        "ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id),`type`=VALUES(`type`),`description`=VALUES(`description`),updated_at=NOW(),updated_by=VALUES(updated_by);\n"
    )
    output.write(f"SET {dataset_var}=LAST_INSERT_ID();\n")
    if args.replace:
        output.write(f"DELETE dao FROM `data_annotation_object` dao INNER JOIN `data` d ON dao.data_id=d.id WHERE d.dataset_id={dataset_var};\n")
        output.write(f"DELETE FROM `dataset_class` WHERE dataset_id={dataset_var};\n")
        output.write(f"DELETE FROM `data` WHERE dataset_id={dataset_var};\n\n")
    elif args.replace_split:
        split_types = selected_pkl_split_types(args.pkl_split)
        split_sql = ",".join(sql_str(value) for value in split_types)
        temp_table = f"tmp_replace_split_data_{dataset_index}"
        output.write(f"DROP TEMPORARY TABLE IF EXISTS `{temp_table}`;\n")
        output.write(f"CREATE TEMPORARY TABLE `{temp_table}` (`id` BIGINT NOT NULL PRIMARY KEY);\n")
        output.write(
            f"INSERT INTO `{temp_table}` (`id`) SELECT id FROM `data` "
            f"WHERE dataset_id={dataset_var} AND split_type IN ({split_sql});\n"
        )
        for table in (
            "data_annotation_object",
            "data_annotation_classification",
            "data_classification_option",
            "data_scene_attribute",
            "model_data_result",
            "model_dataset_result",
        ):
            output.write(
                f"DELETE target FROM `{table}` target "
                f"INNER JOIN `{temp_table}` old_data ON target.data_id=old_data.id;\n"
            )
        output.write(
            f"DELETE target FROM `data_edit` target "
            f"INNER JOIN `{temp_table}` old_data ON target.data_id=old_data.id;\n"
        )
        output.write(
            f"DELETE target FROM `data_edit` target "
            f"INNER JOIN `{temp_table}` old_scene ON target.scene_id=old_scene.id;\n"
        )
        output.write(
            f"DELETE target FROM `data` target "
            f"INNER JOIN `{temp_table}` old_data ON target.id=old_data.id;\n"
        )
        output.write(f"DROP TEMPORARY TABLE `{temp_table}`;\n\n")

    class_vars: dict[str, str] = {}
    file_index = 0
    frame_count = 0
    object_count = 0
    current_scene_key = None
    scene_counter = 0
    frames: Iterable[tuple[Path, list[dict[str, object]], str]]
    if args.source == "pkl":
        frames = iter_pkl_frames(dataset_dir, args.pkl_split, args.limit)
    else:
        frames = iter_label_frames(dataset_dir, args.limit)
    for lidar, annotations, split_type in frames:
        clip_index = frame_count // args.clip_size + 1
        scene_key = (split_type, clip_index)
        if scene_key != current_scene_key:
            current_scene_key = scene_key
            scene_counter += 1
            scene_var = f"@scene_{dataset_index}_{scene_counter}"
            write_scene(output, dataset_var, scene_var, scene_name(split_type, clip_index), split_type, args)
        frame_count += 1
        file_index += 1
        file_var = f"@file_{dataset_index}_{file_index}"
        for statement in file_sql(lidar, root, args.bucket_name, args.user_id, file_var):
            output.write(statement + "\n")
        content_sql = (
            "JSON_ARRAY(JSON_OBJECT('name','point_cloud','type','directory','files',"
            f"JSON_ARRAY(JSON_OBJECT('name',{sql_str(lidar.name)},'type','file','fileId',{file_var},'pointDim',4))))"
        )
        output.write(
            "INSERT INTO `data` (`dataset_id`,`name`,`order_name`,`content`,`type`,`parent_id`,`status`,`annotation_status`,`split_type`,`is_deleted`,`del_unique_key`,`created_at`,`created_by`,`updated_at`,`updated_by`) "
            f"VALUES ({dataset_var},{sql_str(lidar.stem)},{sql_str(lidar.stem)},{content_sql},'SINGLE_DATA',{scene_var},'VALID','ANNOTATED',{sql_str(split_type)},b'0',0,NOW(),{args.user_id},NOW(),{args.user_id}) "
            "ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id),`content`=VALUES(`content`),`annotation_status`=VALUES(`annotation_status`),`split_type`=VALUES(`split_type`),`parent_id`=VALUES(`parent_id`),`order_name`=VALUES(`order_name`),updated_at=NOW(),updated_by=VALUES(updated_by);\n"
        )
        output.write("SET @data_id=LAST_INSERT_ID();\n")
        for annotation in annotations:
            class_name = str(annotation["className"])
            class_var = class_vars.get(class_name.lower())
            if class_var is None:
                class_var = f"@class_{dataset_index}_{len(class_vars) + 1}"
                class_vars[class_name.lower()] = class_var
                output.write(
                    "INSERT INTO `dataset_class` (`dataset_id`,`name`,`color`,`tool_type`,`tool_type_options`,`attributes`,`created_at`,`created_by`,`updated_at`,`updated_by`) "
                    f"VALUES ({dataset_var},{sql_str(class_name)},{sql_str(class_color(class_name))},'CUBOID',JSON_OBJECT(),JSON_ARRAY(),NOW(),{args.user_id},NOW(),{args.user_id}) "
                    "ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id),updated_at=NOW(),updated_by=VALUES(updated_by);\n"
                )
                output.write(f"SET {class_var}=LAST_INSERT_ID();\n")
            output.write(annotation_sql(annotation, dataset_var, class_var, args.user_id) + "\n")
            object_count += 1
        output.write("\n")
    return frame_count, object_count

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate SQL for external KITTI LiDAR datasets.")
    parser.add_argument("--root", required=True, help="Mounted external root, normally /home/user/cjg/conch_data")
    parser.add_argument("--scan-root", default=None, help="Directory containing mydata_raw_point and mydata_remove")
    parser.add_argument("--dataset", action="append", dest="datasets", help="Dataset directory name; repeat to select multiple")
    parser.add_argument("--output", default="external_kitti_lidar_import.sql")
    parser.add_argument("--bucket-name", default="external-data")
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--limit", type=int, default=None, help="Optional per-dataset frame limit for validation")
    parser.add_argument("--clip-size", type=int, default=30, help="Frames per generated scene/clip")
    parser.add_argument("--replace", action="store_true", help="Delete existing data and classes in the target dataset before import")
    parser.add_argument(
        "--replace-split",
        action="store_true",
        help="Delete existing data and annotations for the selected PKL split before re-importing it",
    )
    parser.add_argument("--source", choices=("pkl", "labels"), default="pkl", help="Read KITTI infos pkl or raw label_2/calib files")
    parser.add_argument("--pkl-split", choices=("train", "val", "all"), default="train", help="KITTI infos split to import in pkl mode")
    args = parser.parse_args()
    if args.replace and args.replace_split:
        parser.error("--replace and --replace-split are mutually exclusive")
    if args.replace_split and args.source != "pkl":
        parser.error("--replace-split requires --source pkl")
    root = Path(args.root).resolve()
    scan_root = Path(args.scan_root).resolve() if args.scan_root else root / "pp_data"
    selected = args.datasets or [path.name for path in sorted(scan_root.iterdir()) if path.is_dir()]
    dataset_dirs = [scan_root / name for name in selected]
    invalid = [path for path in dataset_dirs if not (path / "training" / "velodyne").is_dir()]
    if invalid:
        parser.error("not a KITTI dataset: " + ", ".join(map(str, invalid)))
    with Path(args.output).open("w", encoding="utf-8") as output:
        output.write("-- Generated by scripts/import_external_kitti_lidar.py\nSET NAMES utf8mb4;\nSTART TRANSACTION;\n\n")
        totals = [write_dataset(output, root, dataset_dir, args, index + 1) for index, dataset_dir in enumerate(dataset_dirs)]
        output.write("COMMIT;\n")
    frames = sum(total[0] for total in totals)
    objects = sum(total[1] for total in totals)
    print(f"Wrote {args.output}")
    print(f"Datasets: {len(dataset_dirs)}, frames: {frames}, boxes: {objects}")


if __name__ == "__main__":
    main()
