#!/usr/bin/env python3
"""
Copy labeled clip directories into target subdirectories named by label.

By default the script reads clip labels from the local Xtreme1 MySQL container:

    python scripts/copy_clips_by_label.py --source-root D:/clips --target-root D:/clips_by_label

Only clips with a non-empty label are copied. Unlabeled clips are not touched.
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


WINDOWS_INVALID_CHARS = '<>:"\\|?*'


@dataclass(frozen=True)
class ClipLabel:
    clip_name: str
    label: str


def clean_label(label: str) -> str:
    value = " ".join(label.strip().split())
    for char in WINDOWS_INVALID_CHARS:
        value = value.replace(char, "_")
    value = value.rstrip(". ")
    return value or "_blank"


def read_labels_tsv(path: Path) -> list[ClipLabel]:
    rows: list[ClipLabel] = []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.reader(file, delimiter="\t")
        for line_no, row in enumerate(reader, start=1):
            if not row or len(row) < 2:
                continue
            clip_name = row[0].strip()
            label = row[1].strip()
            if line_no == 1 and clip_name.lower() in {"clip", "clip_name", "name"}:
                continue
            if clip_name and label:
                rows.append(ClipLabel(clip_name=clip_name, label=label))
    return rows


def mysql_query(args: argparse.Namespace) -> list[ClipLabel]:
    where = ["d.type = 'SCENE'", "d.is_deleted = 0", "dsa.sub_type IS NOT NULL", "dsa.sub_type <> ''"]
    if args.dataset_id is not None:
        where.append(f"d.dataset_id = {int(args.dataset_id)}")
    if args.dataset_name:
        where.append("ds.name = " + sql_quote(args.dataset_name))

    sql = f"""
SELECT d.name, dsa.sub_type
FROM data_scene_attribute dsa
JOIN data d ON d.id = dsa.data_id
JOIN dataset ds ON ds.id = d.dataset_id
WHERE {' AND '.join(where)}
ORDER BY dsa.sub_type, d.name;
""".strip()

    command = [
        "docker",
        "compose",
        "-f",
        str(args.compose_file),
        "exec",
        "-T",
        "mysql",
        "mysql",
        "-u",
        args.db_user,
        f"-p{args.db_password}",
        args.db_name,
        "--batch",
        "--raw",
        "--skip-column-names",
        "-e",
        sql,
    ]
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "mysql query failed")

    rows: list[ClipLabel] = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        clip_name = parts[0].strip()
        label = parts[1].strip()
        if clip_name and label:
            rows.append(ClipLabel(clip_name=clip_name, label=label))
    return rows


def sql_quote(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def find_clip(source_root: Path, clip_name: str, cache: dict[str, list[Path]]) -> Path | None:
    normalized = clip_name.replace("\\", "/").strip("/")
    direct = source_root / normalized
    if direct.is_dir():
        return direct

    basename = Path(normalized).name
    if basename not in cache:
        cache[basename] = [path for path in source_root.rglob(basename) if path.is_dir()]
    matches = cache[basename]
    if len(matches) == 1:
        return matches[0]
    for path in matches:
        try:
            rel = path.relative_to(source_root).as_posix()
        except ValueError:
            continue
        if rel == normalized or rel.endswith("/" + normalized):
            return path
    return None


def unique_dest(dest: Path) -> Path:
    if not dest.exists():
        return dest
    index = 2
    while True:
        candidate = dest.with_name(f"{dest.name}_{index}")
        if not candidate.exists():
            return candidate
        index += 1


def copy_clip(src: Path, dest: Path, overwrite: bool, dry_run: bool) -> None:
    if dry_run:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and overwrite:
        shutil.rmtree(dest)
    shutil.copytree(src, dest)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Copy labeled clips into label-named directories.")
    parser.add_argument("--source-root", required=True, type=Path, help="Original clip root directory.")
    parser.add_argument("--target-root", required=True, type=Path, help="Output directory.")
    parser.add_argument("--labels-tsv", type=Path, help="Optional TSV: clip_name<TAB>label. If omitted, read MySQL from Docker.")
    parser.add_argument("--compose-file", type=Path, default=Path("docker-compose.yml"), help="docker-compose.yml path.")
    parser.add_argument("--db-user", default="xtreme1")
    parser.add_argument("--db-password", default="Rc4K3L6f")
    parser.add_argument("--db-name", default="xtreme1")
    parser.add_argument("--dataset-id", type=int, help="Only copy clips in this dataset id.")
    parser.add_argument("--dataset-name", help="Only copy clips in this dataset name.")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing copied clip directories.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned copies without copying.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_root = args.source_root.resolve()
    target_root = args.target_root.resolve()
    if not source_root.is_dir():
        print(f"Source root not found: {source_root}", file=sys.stderr)
        return 2

    labels = read_labels_tsv(args.labels_tsv.resolve()) if args.labels_tsv else mysql_query(args)
    if not labels:
        print("No labeled clips found.")
        return 0

    cache: dict[str, list[Path]] = {}
    copied = 0
    missing = 0
    skipped = 0
    for item in labels:
        src = find_clip(source_root, item.clip_name, cache)
        if src is None:
            missing += 1
            print(f"[missing] {item.clip_name} ({item.label})")
            continue

        label_dir = target_root / clean_label(item.label)
        dest = label_dir / src.name
        if dest.exists() and not args.overwrite:
            dest = unique_dest(dest)
        if dest.exists() and not args.overwrite:
            skipped += 1
            print(f"[skip] {src} -> {dest}")
            continue

        print(f"[copy] {src} -> {dest}")
        copy_clip(src, dest, args.overwrite, args.dry_run)
        copied += 1

    action = "Would copy" if args.dry_run else "Copied"
    print(f"{action}: {copied}; missing source: {missing}; skipped: {skipped}; target: {target_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
