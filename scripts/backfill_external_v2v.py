#!/usr/bin/env python3
"""Generate idempotent SQL that links external V2V.csv files to existing scenes."""
from __future__ import annotations

import argparse
from pathlib import Path

from import_external_occ_clips import (
    file_type,
    find_clip_dirs,
    find_v2v_csv,
    path_hash,
    rel_posix,
    sql_json_str,
    sql_str,
)


def generate_sql(args: argparse.Namespace) -> tuple[str, int]:
    root = Path(args.root).resolve()
    scan_root = Path(args.scan_root).resolve()
    if root != scan_root and root not in scan_root.parents:
        raise ValueError("--scan-root must be inside --root")
    clips = find_clip_dirs(scan_root, require_obstacle=False, layout_root=root)
    lines = ["SET NAMES utf8mb4;", "START TRANSACTION;", ""]
    count = 0
    for clip in clips:
        v2v = find_v2v_csv(clip)
        if not v2v:
            continue
        count += 1
        scene_name = clip.name if args.scene_name_from == "basename" else rel_posix(clip, scan_root)
        relative = rel_posix(v2v, root)
        lines.extend([
            f"-- Scene: {scene_name}",
            "SET @v2v_scene_id = NULL;",
            "SET @v2v_file_id = NULL;",
            "SELECT `id` INTO @v2v_scene_id FROM `data` "
            f"WHERE `dataset_id`={args.dataset_id} AND `type`='SCENE' AND `name`={sql_str(scene_name)} "
            "AND `is_deleted`=b'0' ORDER BY `id` LIMIT 1;",
            "INSERT INTO `file` "
            "(`name`, `original_name`, `path`, `path_hash`, `type`, `size`, `bucket_name`, "
            "`created_at`, `created_by`, `updated_at`, `updated_by`) "
            f"SELECT {sql_str(v2v.name)}, {sql_str(v2v.name)}, {sql_str(relative)}, {path_hash(relative)}, "
            f"{sql_str(file_type(v2v))}, {v2v.stat().st_size}, {sql_str(args.bucket_name)}, "
            f"NOW(), {args.user_id}, NOW(), {args.user_id} FROM DUAL WHERE @v2v_scene_id IS NOT NULL "
            "ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id), `name`=VALUES(`name`), "
            "`original_name`=VALUES(`original_name`), `type`=VALUES(`type`), `size`=VALUES(`size`), "
            "`bucket_name`=VALUES(`bucket_name`), `updated_at`=NOW(), `updated_by`=VALUES(`updated_by`);",
            "SET @v2v_file_id = IF(@v2v_scene_id IS NULL, NULL, LAST_INSERT_ID());",
            "UPDATE `data` SET `content`=JSON_ARRAY_APPEND(COALESCE(`content`, JSON_ARRAY()), '$', "
            f"JSON_OBJECT('name', 'v2v', 'type', 'directory', 'files', JSON_ARRAY(JSON_OBJECT('name', {sql_json_str(v2v.name)}, "
            "'type', 'file', 'fileId', @v2v_file_id)))), `updated_at`=NOW(), "
            f"`updated_by`={args.user_id} WHERE `dataset_id`={args.dataset_id} AND `parent_id`=@v2v_scene_id "
            "AND `type`='SINGLE_DATA' AND `is_deleted`=b'0' "
            "AND JSON_SEARCH(`content`, 'one', 'V2V.csv') IS NULL;",
            "",
        ])
    lines.extend([
        "COMMIT;",
        "SELECT COUNT(*) AS linked_frames FROM `data` "
        f"WHERE `dataset_id`={args.dataset_id} AND `type`='SINGLE_DATA' AND `is_deleted`=b'0' "
        "AND JSON_SEARCH(`content`, 'one', 'V2V.csv') IS NOT NULL;",
        "",
    ])
    return "\n".join(lines), count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--scan-root", required=True)
    parser.add_argument("--dataset-id", required=True, type=int)
    parser.add_argument("--output", required=True)
    parser.add_argument("--bucket-name", default="external-data")
    parser.add_argument("--user-id", type=int, default=1)
    parser.add_argument("--scene-name-from", choices=("basename", "scan-relative"), default="basename")
    args = parser.parse_args()
    sql, count = generate_sql(args)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(sql, encoding="utf-8")
    print(f"Generated {output} for {count} V2V clip(s)")


if __name__ == "__main__":
    main()
