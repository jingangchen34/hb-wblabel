#!/usr/bin/env python3
"""
Generate SQL that registers externally stored OCC/LiDAR-fusion clips.

The script does not copy point clouds, images, pose.json, or obstacle_3d.json.
It writes MySQL rows whose file paths are resolved by the backend as
/external-data/<relative-path>.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import mimetypes
import os
from pathlib import Path
from typing import Iterable


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
POINT_EXTS = {".bin", ".pcd"}
POINT_CACHE_EXTS = {".xyzl"}
LABEL_EXTS = {".label"}
THUMBNAIL_SUFFIXES = ("_large", "_medium", "_small")
SKIP_DIR_NAMES = {
    ".git",
    "__pycache__",
    "lidars",
    "lidar_point_cloud_cache",
    "occ_label",
    "anno",
}


class VarGen:
    def __init__(self) -> None:
        self.file_index = 0
        self.scene_index = 0
        self.class_index = 0
        self.dataset_index = 0

    def file(self) -> str:
        self.file_index += 1
        return f"@file_{self.file_index}"

    def scene(self) -> str:
        self.scene_index += 1
        return f"@scene_{self.scene_index}"

    def class_id(self) -> str:
        self.class_index += 1
        return f"@class_{self.class_index}"

    def dataset(self) -> str:
        self.dataset_index += 1
        return f"@dataset_{self.dataset_index}"


def sql_str(value: str | os.PathLike[str] | None) -> str:
    if value is None:
        return "NULL"
    text = str(value).replace("\\", "\\\\").replace("'", "''")
    return f"'{text}'"


def sql_json_str(value: str) -> str:
    return sql_str(value)


def json_sql(value: object) -> str:
    return sql_str(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def path_hash(path: str) -> int:
    digest = hashlib.md5(path.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def rel_posix(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def file_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"


def find_obstacle_file(clip_dir: Path) -> Path | None:
    default = clip_dir / "anno" / "obstacle_3d.json"
    if default.is_file():
        return default
    matches = [p for p in clip_dir.rglob("obstacle_3d.json") if p.is_file()]
    return sorted(matches)[0] if matches else None


def find_lidar_bins(clip_dir: Path) -> list[Path]:
    lidar_dir = clip_dir / "lidars"
    if not lidar_dir.is_dir():
        return []
    return sorted(
        p for p in lidar_dir.rglob("*")
        if p.is_file() and p.suffix.lower() in POINT_EXTS
    )


def frame_token(path: Path) -> str:
    stem = path.stem
    parts = stem.split("_")
    return parts[-1] if parts else stem


def extract_frame_token(data_name: str) -> str:
    parts = data_name.split("_")
    return parts[-1] if parts else data_name


def find_matching_file(files: Iterable[Path], lidar: Path, frame_idx: int, frame_count: int) -> Path | None:
    files = sorted(files)
    stem = lidar.stem
    token = frame_token(lidar)
    for item in files:
        item_stem = item.stem
        if item_stem == stem or stem in item_stem or token and token in item_stem:
            return item
    if len(files) == frame_count and 0 <= frame_idx < len(files):
        return files[frame_idx]
    return None


def is_generated_thumbnail(path: Path) -> bool:
    return any(path.stem.endswith(suffix) for suffix in THUMBNAIL_SUFFIXES)


def find_camera_dirs(clip_dir: Path) -> list[Path]:
    dirs: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(clip_dir):
        current = Path(dirpath)
        if current == clip_dir:
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES]
        if any(Path(name).suffix.lower() in IMAGE_EXTS for name in filenames):
            dirs.append(current)
    return sorted(dirs)


def find_occ_camera_dirs(clip_dir: Path) -> list[Path]:
    dirs: list[Path] = []
    camera_root = clip_dir / "cameras"
    if camera_root.is_dir():
        dirs.extend(sorted(p for p in camera_root.iterdir() if p.is_dir()))
    return dirs or find_camera_dirs(clip_dir)


def camera_image_by_index(camera_dir: Path, frame_idx: int) -> Path | None:
    images = sorted(
        p for p in camera_dir.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS and not is_generated_thumbnail(p)
    )
    if 0 <= frame_idx < len(images):
        return images[frame_idx]
    return None


def resolve_clip_relative_file(clip_dir: Path, relative_path: object) -> Path | None:
    if not isinstance(relative_path, str) or not relative_path.strip():
        return None
    normalized = relative_path.replace("\\", "/").lstrip("/")
    path = clip_dir / normalized
    return path if path.is_file() else None


def find_obstacle_frame_entry(root: object, data_name: str) -> dict | None:
    token = extract_frame_token(data_name)

    def walk(node: object) -> dict | None:
        if isinstance(node, list):
            for item in node:
                result = walk(item)
                if result is not None:
                    return result
            return None
        if not isinstance(node, dict):
            return None

        direct = get_frame_value(node, data_name, token)
        if isinstance(direct, dict) and ("cam_files" in direct or "filepath" in direct):
            return direct

        filepath = str(node.get("filepath", ""))
        if ("cam_files" in node and matches_frame(node, data_name, token)) or (token and token in filepath):
            return node

        for value in node.values():
            result = walk(value)
            if result is not None:
                return result
        return None

    return walk(root)


def obstacle_camera_images(clip_dir: Path, obstacle_root: object | None, data_name: str) -> list[tuple[str, Path]]:
    if isinstance(obstacle_root, dict) and isinstance(obstacle_root.get("cam_files"), dict):
        frame_entry = obstacle_root
    else:
        frame_entry = find_obstacle_frame_entry(obstacle_root, data_name) if obstacle_root is not None else None
    if not isinstance(frame_entry, dict):
        return []
    cam_files = frame_entry.get("cam_files")
    if not isinstance(cam_files, dict):
        return []

    images: list[tuple[str, Path]] = []
    seen: set[str] = set()
    for camera_name in sorted(cam_files):
        config = cam_files.get(camera_name)
        if not isinstance(config, dict):
            continue
        image = resolve_clip_relative_file(clip_dir, config.get("cam_file"))
        if image is None:
            continue
        image_key = image.resolve().as_posix()
        if image_key in seen:
            continue
        seen.add(image_key)
        images.append((camera_name, image))
    return images


def collect_obstacle_frame_entries(node: object, output: list[dict]) -> None:
    if isinstance(node, list):
        for item in node:
            collect_obstacle_frame_entries(item, output)
        return
    if not isinstance(node, dict):
        return
    if isinstance(node.get("filepath"), str):
        output.append(node)
        return
    for value in node.values():
        collect_obstacle_frame_entries(value, output)


def obstacle_frame_sources(clip_dir: Path, obstacle_root: object | None) -> list[tuple[Path, dict | None]]:
    entries: list[dict] = []
    if obstacle_root is not None:
        collect_obstacle_frame_entries(obstacle_root, entries)
    sources: list[tuple[Path, dict | None]] = []
    seen: set[str] = set()
    for entry in entries:
        lidar = resolve_clip_relative_file(clip_dir, entry.get("filepath"))
        if lidar is None or lidar.suffix.lower() not in POINT_EXTS:
            continue
        key = lidar.resolve().as_posix()
        if key in seen:
            continue
        seen.add(key)
        sources.append((lidar, entry))
    return sources


def is_new_clip_path(path: Path, root: Path) -> bool:
    try:
        parts = path.resolve().relative_to(root.resolve()).parts
    except ValueError:
        return False
    return bool(parts) and parts[0] == "new_clip"


def find_clip_dirs(root: Path, require_obstacle: bool | None = True, layout_root: Path | None = None) -> list[Path]:
    clips: list[Path] = []
    root_for_layout = layout_root or root
    for dirpath, dirnames, _ in os.walk(root):
        current = Path(dirpath)
        pose = current / "pose.json"
        has_obstacle = find_obstacle_file(current) is not None
        obstacle_required = require_obstacle
        if obstacle_required is None:
            obstacle_required = not is_new_clip_path(current, root_for_layout)
        if pose.is_file() and (has_obstacle or not obstacle_required) and find_lidar_bins(current):
            clips.append(current)
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in {".git", "__pycache__"}]
    return sorted(clips)

def insert_file_sql(path: Path, root: Path, bucket_name: str, user_id: int, var: str) -> list[str]:
    rel = rel_posix(path, root)
    return [
        "INSERT INTO `file` "
        "(`name`, `original_name`, `path`, `path_hash`, `type`, `size`, `bucket_name`, `created_at`, `created_by`, `updated_at`, `updated_by`) "
        f"VALUES ({sql_str(path.name)}, {sql_str(path.name)}, {sql_str(rel)}, {path_hash(rel)}, "
        f"{sql_str(file_type(path))}, {path.stat().st_size}, {sql_str(bucket_name)}, NOW(), {user_id}, NOW(), {user_id}) "
        "ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id), "
        "`name`=VALUES(`name`), `original_name`=VALUES(`original_name`), `type`=VALUES(`type`), "
        "`size`=VALUES(`size`), `bucket_name`=VALUES(`bucket_name`), `updated_at`=NOW(), `updated_by`=VALUES(`updated_by`);",
        f"SET {var}=LAST_INSERT_ID();",
    ]


def file_node(name: str, file_var: str) -> str:
    return f"JSON_OBJECT('name', {sql_json_str(name)}, 'type', 'file', 'fileId', {file_var})"


def dir_node(name: str, children: list[str]) -> str:
    return f"JSON_OBJECT('name', {sql_json_str(name)}, 'type', 'directory', 'files', JSON_ARRAY({', '.join(children)}))"


def clip_parent_dataset_name(clip_dir: Path, root: Path) -> str:
    try:
        parent = clip_dir.parent.resolve().relative_to(root.resolve())
        parent_name = parent.as_posix()
        return parent_name if parent_name and parent_name != "." else clip_dir.parent.name
    except ValueError:
        return clip_dir.parent.name


def make_clip_display_name(clip_dir: Path, root: Path, dataset_name: str | None = None) -> str:
    try:
        relative_parts = clip_dir.resolve().relative_to(root.resolve()).parts
    except ValueError:
        relative_parts = ()

    dataset_parts = tuple(part for part in Path(dataset_name or "").parts if part not in {"", "."})
    if dataset_parts and relative_parts[: len(dataset_parts)] == dataset_parts:
        scene_parts = list(relative_parts[len(dataset_parts) :])
        if len(scene_parts) >= 3:
            site_name = scene_parts[-3]
            result_dir = scene_parts[-2]
            if result_dir == f"{site_name}_qlc_result":
                scene_parts.pop(-2)
                scene_parts[-1] = f"{scene_parts[-1]}.clip"
                return Path(*scene_parts).as_posix()

    parent_names = {args_safe_name(clip_dir.parent.name), args_safe_name(clip_parent_dataset_name(clip_dir, root))}
    if dataset_name and args_safe_name(dataset_name) in parent_names:
        return clip_dir.name
    return rel_posix(clip_dir, root)


def args_safe_name(name: str | None) -> str:
    return (name or "").strip()


def dataset_name_for_clip(clip_dir: Path, root: Path, args: argparse.Namespace) -> str:
    if args.dataset_from == "clip-parent":
        return clip_parent_dataset_name(clip_dir, root)
    if args.dataset_from == "root-child":
        try:
            return clip_dir.resolve().relative_to(root.resolve()).parts[0]
        except IndexError:
            return args.dataset_name
    return args.dataset_name


def dataset_description_for_name(name: str, args: argparse.Namespace) -> str:
    if args.dataset_description:
        return args.dataset_description
    return f"Imported external OCC clips for {name}"


def insert_dataset_sql(name: str, args: argparse.Namespace, var: str) -> list[str]:
    description = dataset_description_for_name(name, args)
    return [
        f"-- Dataset: {name}",
        "INSERT INTO `dataset` (`name`, `type`, `description`, `is_deleted`, `del_unique_key`, `created_at`, `created_by`, `updated_at`, `updated_by`) "
        f"VALUES ({sql_str(name)}, 'LIDAR_FUSION', {sql_str(description)}, b'0', 0, NOW(), {args.user_id}, NOW(), {args.user_id}) "
        "ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id), `type`=VALUES(`type`), `updated_at`=NOW(), `updated_by`=VALUES(`updated_by`);",
        f"SET {var}=LAST_INSERT_ID();",
        "",
    ]


def generate_sql(args: argparse.Namespace) -> tuple[str, int, int]:
    root = Path(args.root).resolve()
    scan_root = Path(args.scan_root).resolve() if args.scan_root else root
    try:
        scan_root.relative_to(root)
    except ValueError as exc:
        raise SystemExit(f"--scan-root must be inside --root: scan-root={scan_root}, root={root}") from exc

    require_obstacle = None if args.conch_data_layout else not args.skip_obstacle_annotations
    clips = find_clip_dirs(scan_root, require_obstacle=require_obstacle, layout_root=root)
    vargen = VarGen()
    lines: list[str] = [
        "-- Generated by scripts/import_external_occ_clips.py",
        "-- This SQL registers external files only. It does not copy source data.",
        "SET NAMES utf8mb4;",
        "START TRANSACTION;",
        "",
    ]
    frame_total = 0
    dataset_vars: dict[str, str] = {}
    class_vars: dict[tuple[str, str], str] = {}

    for clip_dir in clips:
        dataset_name = dataset_name_for_clip(clip_dir, root, args)
        dataset_var = dataset_vars.get(dataset_name)
        if dataset_var is None:
            dataset_var = vargen.dataset()
            dataset_vars[dataset_name] = dataset_var
            lines.extend(insert_dataset_sql(dataset_name, args, dataset_var))

        clip_name = make_clip_display_name(clip_dir, root, dataset_name)
        scene_var = vargen.scene()
        calib = clip_dir / "calib.json"
        pose = clip_dir / "pose.json"
        coordinate_conversion = clip_dir / "coordinate_conversion.json"
        obstacle = find_obstacle_file(clip_dir)
        skip_obstacle_annotations = args.skip_obstacle_annotations or (
            args.conch_data_layout and is_new_clip_path(clip_dir, root)
        )
        obstacle_root = read_json_file(obstacle) if obstacle and not skip_obstacle_annotations else None
        lidar_bins = find_lidar_bins(clip_dir)
        frame_sources = obstacle_frame_sources(clip_dir, obstacle_root)
        if not frame_sources:
            frame_sources = [(lidar, None) for lidar in lidar_bins]
        camera_dirs = find_occ_camera_dirs(clip_dir)

        lines.extend([
            f"-- Scene: {clip_name}",
            "INSERT INTO `data` (`dataset_id`, `name`, `order_name`, `content`, `type`, `parent_id`, `status`, `annotation_status`, `split_type`, `is_deleted`, `del_unique_key`, `created_at`, `created_by`, `updated_at`, `updated_by`) "
            f"VALUES ({dataset_var}, {sql_str(clip_name)}, {sql_str(clip_name)}, JSON_ARRAY(), 'SCENE', 0, 'VALID', 'NOT_ANNOTATED', 'NOT_SPLIT', b'0', 0, NOW(), {args.user_id}, NOW(), {args.user_id}) "
            "ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id), `order_name`=VALUES(`order_name`), `updated_at`=NOW(), `updated_by`=VALUES(`updated_by`);",
            f"SET {scene_var}=LAST_INSERT_ID();",
            "",
        ])

        for frame_idx, (lidar, frame_entry) in enumerate(frame_sources):
            frame_total += 1
            frame_name = lidar.stem
            content_nodes: list[str] = []

            lidar_var = vargen.file()
            lines.extend(insert_file_sql(lidar, root, args.bucket_name, args.user_id, lidar_var))
            content_nodes.append(dir_node("point_cloud", [file_node(lidar.name, lidar_var)]))

            cache_dir = clip_dir / "lidar_point_cloud_cache"
            cache = find_matching_file(
                [p for p in cache_dir.rglob("*") if p.is_file() and p.suffix.lower() in POINT_CACHE_EXTS] if cache_dir.is_dir() else [],
                lidar,
                frame_idx,
                len(frame_sources),
            )
            if cache:
                cache_var = vargen.file()
                lines.extend(insert_file_sql(cache, root, args.bucket_name, args.user_id, cache_var))
                content_nodes.append(dir_node("point_cloud_cache", [file_node(cache.name, cache_var)]))

            label = find_matching_file(
                [p for p in clip_dir.rglob("*") if p.is_file() and p.suffix.lower() in LABEL_EXTS],
                lidar,
                frame_idx,
                len(frame_sources),
            )
            if label:
                label_var = vargen.file()
                lines.extend(insert_file_sql(label, root, args.bucket_name, args.user_id, label_var))
                content_nodes.append(dir_node("occ_label", [file_node(label.name, label_var)]))

            camera_images = obstacle_camera_images(clip_dir, frame_entry or obstacle_root, frame_name)
            if not camera_images:
                camera_images = [
                    (camera_dir.name, image) for camera_dir in camera_dirs
                    if camera_dir.parent.name == "cameras"
                    if (image := camera_image_by_index(camera_dir, frame_idx)) is not None
                ]
            for camera_idx, (camera_name, image) in enumerate(camera_images):
                image_var = vargen.file()
                lines.extend(insert_file_sql(image, root, args.bucket_name, args.user_id, image_var))
                content_nodes.append(dir_node(f"image_{camera_idx}_{camera_name}", [file_node(image.name, image_var)]))

            if calib.is_file():
                calib_var = vargen.file()
                lines.extend(insert_file_sql(calib, root, args.bucket_name, args.user_id, calib_var))
                content_nodes.append(dir_node("camera_config", [file_node("calib.json", calib_var)]))

            if pose:
                pose_var = vargen.file()
                lines.extend(insert_file_sql(pose, root, args.bucket_name, args.user_id, pose_var))
                content_nodes.append(file_node("pose.json", pose_var))

            if coordinate_conversion.is_file():
                coordinate_conversion_var = vargen.file()
                lines.extend(insert_file_sql(
                    coordinate_conversion,
                    root,
                    args.bucket_name,
                    args.user_id,
                    coordinate_conversion_var,
                ))
                content_nodes.append(file_node("coordinate_conversion.json", coordinate_conversion_var))

            if obstacle:
                obstacle_var = vargen.file()
                lines.extend(insert_file_sql(obstacle, root, args.bucket_name, args.user_id, obstacle_var))
                content_nodes.append(file_node("obstacle_3d.json", obstacle_var))

            content_expr = f"JSON_ARRAY({', '.join(content_nodes)})"
            lines.extend([
                "INSERT INTO `data` (`dataset_id`, `name`, `order_name`, `content`, `type`, `parent_id`, `status`, `annotation_status`, `split_type`, `is_deleted`, `del_unique_key`, `created_at`, `created_by`, `updated_at`, `updated_by`) "
                f"VALUES ({dataset_var}, {sql_str(frame_name)}, {sql_str(frame_name)}, {content_expr}, 'SINGLE_DATA', {scene_var}, 'VALID', 'NOT_ANNOTATED', 'NOT_SPLIT', b'0', 0, NOW(), {args.user_id}, NOW(), {args.user_id}) "
                "ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id), `content`=VALUES(`content`), `order_name`=VALUES(`order_name`), `updated_at`=NOW(), `updated_by`=VALUES(`updated_by`);",
                "SET @data_id=LAST_INSERT_ID();",
                "",
            ])
            if obstacle_root is not None and not skip_obstacle_annotations:
                objects = find_obstacle_objects(obstacle_root, frame_name)
                for object_index, obj in enumerate(objects, start=1):
                    annotation = build_annotation(obj, frame_name, object_index)
                    if annotation is None:
                        continue
                    class_name = annotation["className"]
                    class_key = normalize_class_name(class_name)
                    dataset_class_key = (dataset_name, class_key)
                    class_var = class_vars.get(dataset_class_key)
                    if class_var is None:
                        class_var = vargen.class_id()
                        class_vars[dataset_class_key] = class_var
                        lines.extend(insert_class_sql(class_name, dataset_var, args.user_id, class_var))
                    lines.extend(insert_annotation_sql(annotation, dataset_var, class_var, args.user_id))
                if objects:
                    lines.append("")

    lines.extend([
        "COMMIT;",
        "",
        "-- Imported scenes:",
        "SELECT d.id AS dataset_id, d.name AS dataset_name, s.id AS scene_id, s.name AS scene_name "
        "FROM `dataset` d JOIN `data` s ON s.dataset_id=d.id "
        "WHERE s.type='SCENE' AND s.is_deleted=b'0' ORDER BY d.name, s.name;",
    ])
    return "\n".join(lines), len(clips), frame_total


def read_json_file(path: Path | None) -> object | None:
    if path is None:
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except UnicodeDecodeError:
        return json.loads(path.read_text(encoding="gbk"))


def first_array(obj: dict, keys: tuple[str, ...]) -> list | None:
    for key in keys:
        value = obj.get(key)
        if isinstance(value, list):
            return value
    return None


def get_frame_value(obj: dict, data_name: str, token: str) -> object | None:
    for key, value in obj.items():
        if key == data_name or (token and token in key):
            return value
    return None


def matches_frame(obj: dict, data_name: str, token: str) -> bool:
    frame_keys = (
        "frame", "frameName", "frame_name", "dataName", "data_name", "lidar", "lidarName",
        "lidar_name", "pointCloud", "point_cloud", "timestamp", "timestampNs", "timestamp_ns", "time",
    )
    for key in frame_keys:
        value = obj.get(key)
        if value is None:
            continue
        text = str(value)
        if data_name == text or data_name in text or text in data_name:
            return True
        if token and token in text:
            return True
    return False


def looks_like_obstacle(obj: dict) -> bool:
    return any(key in obj for key in ("center", "center3D", "position", "translation", "location", "x", "cx"))


def collect_obstacle_objects(node: object, data_name: str, token: str, frame_matched: bool, output: list[dict]) -> None:
    if isinstance(node, list):
        for item in node:
            collect_obstacle_objects(item, data_name, token, frame_matched, output)
        return
    if not isinstance(node, dict):
        return

    current_matched = frame_matched or matches_frame(node, data_name, token)
    child_array = first_array(node, ("objects", "annotations", "obstacles", "labels", "items"))
    if child_array is not None:
        for item in child_array:
            collect_obstacle_objects(item, data_name, token, current_matched, output)
        return

    frames = first_array(node, ("frames", "data", "samples"))
    if frames is not None:
        for item in frames:
            collect_obstacle_objects(item, data_name, token, current_matched, output)
        return

    direct = get_frame_value(node, data_name, token)
    if direct is not None:
        collect_obstacle_objects(direct, data_name, token, True, output)
        return

    if current_matched and looks_like_obstacle(node):
        output.append(node)


def find_obstacle_objects(root: object, data_name: str) -> list[dict]:
    objects: list[dict] = []
    collect_obstacle_objects(root, data_name, extract_frame_token(data_name), False, objects)
    return objects


def first_present(obj: dict, keys: tuple[str, ...]) -> object | None:
    for key in keys:
        value = obj.get(key)
        if value is not None:
            return value
    return None


def to_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except ValueError:
        return None


def parse_point(value: object) -> list[float] | None:
    if isinstance(value, list) and len(value) >= 3:
        parsed = [to_float(value[0]), to_float(value[1]), to_float(value[2])]
        return parsed if all(v is not None for v in parsed) else None
    if isinstance(value, dict):
        x = first_number(value, ("x", "cx", "length", "l", "dx"))
        y = first_number(value, ("y", "cy", "width", "w", "dy"))
        z = first_number(value, ("z", "cz", "height", "h", "dz"))
        if x is not None and y is not None and z is not None:
            return [x, y, z]
    return None


def first_number(obj: dict, keys: tuple[str, ...]) -> float | None:
    for key in keys:
        parsed = to_float(obj.get(key))
        if parsed is not None:
            return parsed
    return None


def first_string(obj: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = obj.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return ""


def read_point(obj: dict, object_keys: tuple[str, ...], scalar_keys: tuple[str, ...]) -> list[float] | None:
    for key in object_keys:
        point = parse_point(obj.get(key))
        if point is not None:
            return point
    x = first_number(obj, (scalar_keys[0], scalar_keys[3]))
    y = first_number(obj, (scalar_keys[1], scalar_keys[4]))
    z = first_number(obj, (scalar_keys[2], scalar_keys[5]))
    if (x is None or y is None or z is None) and len(scalar_keys) >= 9:
        x = first_number(obj, (scalar_keys[6],))
        y = first_number(obj, (scalar_keys[7],))
        z = first_number(obj, (scalar_keys[8],))
    if x is None or y is None or z is None:
        return None
    return [x, y, z]


def parse_quaternion_wxyz(value: object) -> list[float] | None:
    if isinstance(value, list) and len(value) >= 4:
        w, x, y, z = (to_float(value[0]), to_float(value[1]), to_float(value[2]), to_float(value[3]))
    elif isinstance(value, dict):
        w = first_number(value, ("w", "qw"))
        x = first_number(value, ("x", "qx"))
        y = first_number(value, ("y", "qy"))
        z = first_number(value, ("z", "qz"))
    else:
        return None
    if None in (w, x, y, z):
        return None
    norm = math.sqrt(w * w + x * x + y * y + z * z)
    if norm == 0:
        return [0.0, 0.0, 0.0]
    w, x, y, z = w / norm, x / norm, y / norm, z / norm
    roll = math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
    sinp = 2 * (w * y - z * x)
    pitch = math.copysign(math.pi / 2, sinp) if abs(sinp) >= 1 else math.asin(sinp)
    yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    return [roll, pitch, yaw]


def read_rotation(obj: dict) -> list[float]:
    quat = first_present(obj, ("quaternion", "quat", "rotation", "rotation_quaternion", "orientation"))
    euler = parse_quaternion_wxyz(quat)
    if euler is not None:
        return euler
    point = parse_point(first_present(obj, ("rotation3D", "rotation_euler", "euler")))
    if point is not None:
        return point
    yaw = first_number(obj, ("yaw", "heading", "rotationZ", "rot_z", "rz"))
    if yaw is not None:
        return [0.0, 0.0, yaw]
    return [0.0, 0.0, 0.0]


def normalize_class_name(name: str) -> str:
    return (name or "object").strip().lower()


def build_annotation(obj: dict, data_name: str, index: int) -> dict | None:
    center = read_point(obj, ("center3D", "center", "position", "translation", "location"), ("x", "y", "z", "cx", "cy", "cz"))
    size = read_point(obj, ("size3D", "size", "dimension", "dimensions", "extent"), ("length", "width", "height", "l", "w", "h", "dx", "dy", "dz"))
    if center is None or size is None:
        return None
    rotation = read_rotation(obj)
    class_name = first_string(obj, ("className", "class_name", "class", "category", "categoryName", "type", "label", "name")) or "object"
    track_id = first_string(obj, ("TrackID", "trackID", "trackId", "trackingId", "track_id", "tracking_id", "id", "uuid", "objectId", "object_id"))
    if not track_id:
        track_id = f"{extract_frame_token(data_name)}-{index}"
    track_name = first_string(obj, ("trackName", "track_name")) or track_id
    return {
        "className": class_name,
        "trackID": track_id,
        "trackName": track_name,
        "center3D": {"x": center[0], "y": center[1], "z": center[2]},
        "size3D": {"x": size[0], "y": size[1], "z": size[2]},
        "rotation3D": {"x": rotation[0], "y": rotation[1], "z": rotation[2]},
    }


def class_color(name: str) -> str:
    colors = ("#FF7A00", "#00D084", "#2F80ED", "#EB5757", "#9B51E0", "#00B8D9", "#F2C94C", "#27AE60")
    digest = int(hashlib.md5(normalize_class_name(name).encode("utf-8")).hexdigest()[:8], 16)
    return colors[digest % len(colors)]


def insert_class_sql(class_name: str, dataset_var: str, user_id: int, var: str) -> list[str]:
    return [
        "INSERT INTO `dataset_class` (`dataset_id`, `name`, `color`, `tool_type`, `tool_type_options`, `attributes`, `created_at`, `created_by`, `updated_at`, `updated_by`) "
        f"VALUES ({dataset_var}, {sql_str(class_name)}, {sql_str(class_color(class_name))}, 'CUBOID', JSON_OBJECT(), JSON_ARRAY(), NOW(), {user_id}, NOW(), {user_id}) "
        "ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id), `updated_at`=NOW(), `updated_by`=VALUES(`updated_by`);",
        f"SET {var}=LAST_INSERT_ID();",
    ]


def insert_annotation_sql(annotation: dict, dataset_var: str, class_var: str, user_id: int) -> list[str]:
    contour = (
        "JSON_OBJECT("
        "'center3D', " + point_sql(annotation["center3D"]) + ", "
        "'size3D', " + point_sql(annotation["size3D"]) + ", "
        "'rotation3D', " + point_sql(annotation["rotation3D"]) +
        ")"
    )
    class_attrs = (
        "JSON_OBJECT("
        "'id', REPLACE(UUID(), '-', ''), "
        "'type', '3D_BOX', "
        "'version', 0, "
        f"'trackID', {sql_str(annotation['trackID'])}, "
        f"'trackId', {sql_str(annotation['trackID'])}, "
        f"'trackName', {sql_str(annotation['trackName'])}, "
        "'classId', " + class_var + ", "
        f"'className', {sql_str(annotation['className'])}, "
        "'classValues', JSON_ARRAY(), "
        f"'contour', {contour}"
        ")"
    )
    return [
        "INSERT INTO `data_annotation_object` (`dataset_id`, `data_id`, `class_id`, `class_attributes`, `source_type`, `source_id`, `created_at`, `created_by`, `updated_at`, `updated_by`) "
        f"VALUES ({dataset_var}, @data_id, {class_var}, {class_attrs}, 'IMPORTED', -1, NOW(), {user_id}, NOW(), {user_id});"
    ]


def point_sql(point: dict) -> str:
    return f"JSON_OBJECT('x', {float(point['x'])}, 'y', {float(point['y'])}, 'z', {float(point['z'])})"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate SQL for externally stored OCC clips.")
    parser.add_argument("--root", required=True, help="External data root, e.g. /home/user/cjg/conch_data/fusiondet_data/7cam_data")
    parser.add_argument(
        "--scan-root",
        default=None,
        help="Optional subdirectory to scan for new clips. File paths are still written relative to --root.",
    )
    parser.add_argument(
        "--conch-data-layout",
        action="store_true",
        help="Use conch_data rules: new_clip skips obstacle annotations; other roots require obstacle_3d.json.",
    )
    parser.add_argument("--dataset-name", default=None, help="Dataset name to create or update in Xtreme1 when --dataset-from fixed")
    parser.add_argument(
        "--dataset-from",
        choices=("fixed", "clip-parent", "root-child"),
        default="fixed",
        help="How to assign clips to datasets: fixed uses --dataset-name, clip-parent uses the clip parent path relative to --root, root-child uses the first path segment under --root",
    )
    parser.add_argument("--output", default="external_occ_import.sql", help="Output SQL path")
    parser.add_argument("--bucket-name", default="external-data", help="Logical bucket name recognized by backend")
    parser.add_argument("--dataset-description", default="Imported external OCC clips", help="Dataset description")
    parser.add_argument("--user-id", type=int, default=1, help="Creator/updater user id")
    parser.add_argument("--skip-obstacle-annotations", action="store_true", help="Only register files and frames; do not import initial 3D boxes from obstacle_3d.json")
    args = parser.parse_args()
    if args.conch_data_layout and args.dataset_from == "fixed" and not args.dataset_name:
        args.dataset_from = "clip-parent"
    if args.dataset_from == "fixed" and not args.dataset_name:
        parser.error("--dataset-name is required when --dataset-from=fixed")
    if args.dataset_from != "fixed" and not args.dataset_name:
        args.dataset_name = Path(args.root).resolve().name

    sql, clip_count, frame_count = generate_sql(args)
    output = Path(args.output)
    output.write_text(sql, encoding="utf-8")
    print(f"Wrote {output}")
    print(f"Detected clips: {clip_count}")
    print(f"Detected frames: {frame_count}")
    print("Import this SQL into the xtreme1 MySQL database, then open the dataset in the web UI.")


if __name__ == "__main__":
    main()
