#!/usr/bin/env python3
"""Remap KITTI label_2 Vehicle2 labels by evaluation Miss position.

Miss positions are one-based, as displayed by the anomaly viewer. The source
directory is read-only: output must be a different, initially empty directory.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_RANGES = (
    "1-201,231-242,287-338,428-492,519-536,577-653,690-706,"
    "757-845,867-890,902-932,1089-1100,1194-1196,1315-1399"
)


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def mysql_rows(sql: str) -> list[list[str]]:
    mysql_bin = env("MYSQL_BIN", "mysql")
    container = env("MYSQL_DOCKER_CONTAINER", "hb-wblabel-mysql-1")
    args = [
        f"-u{env('XTREME1_MYSQL_USER', 'xtreme1')}",
        f"-p{env('XTREME1_MYSQL_PASSWORD', 'Rc4K3L6f')}",
        "--batch", "--raw", "--skip-column-names",
        env("XTREME1_MYSQL_DATABASE", "xtreme1"), "-e", sql,
    ]
    if shutil.which(mysql_bin):
        command = [mysql_bin, f"-h{env('XTREME1_MYSQL_HOST', '127.0.0.1')}",
                   f"-P{env('XTREME1_MYSQL_PORT', '8191')}", *args]
    elif container and shutil.which("docker"):
        command = ["docker", "exec", container, "mysql", *args]
    else:
        command = [mysql_bin, *args]
    result = subprocess.run(command, text=True, capture_output=True, timeout=120)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return [line.split("\t") for line in result.stdout.splitlines() if line.strip()]


def parse_ranges(raw: str) -> set[int]:
    positions: set[int] = set()
    for value in raw.split(","):
        token = value.strip()
        match = re.fullmatch(r"(\d+)(?:\s*-\s*(\d+))?", token)
        if not match:
            raise ValueError(f"invalid range: {token!r}")
        start, end = int(match.group(1)), int(match.group(2) or match.group(1))
        if start < 1 or end < start:
            raise ValueError(f"invalid one-based range: {token!r}")
        positions.update(range(start, end + 1))
    return positions


def load_metrics(args: argparse.Namespace) -> dict[str, Any]:
    if args.metrics_json:
        metrics = json.loads(args.metrics_json.read_text(encoding="utf-8"))
    else:
        rows = mysql_rows(
            "SELECT metrics FROM model_evaluation_record "
            f"WHERE id={args.evaluation_id} AND is_deleted=0 LIMIT 1"
        )
        if not rows:
            raise RuntimeError(f"evaluation {args.evaluation_id} not found")
        metrics = json.loads(rows[0][0])
    if not isinstance(metrics, dict):
        raise ValueError("metrics must be a JSON object")
    return metrics


def missed_data_ids(metrics: dict[str, Any], args: argparse.Namespace) -> list[int]:
    matches = []
    for class_row in metrics.get("safetyThresholds") or []:
        if class_row.get("className") != args.class_name:
            continue
        for row in class_row.get("recommendations") or []:
            rate_min = float(row.get("falseDetectionRateMin", -1))
            rate_max = float(row.get("falseDetectionRateMax", -1))
            if abs(rate_min - args.false_detection_min) < 1e-9 and abs(
                rate_max - args.false_detection_max
            ) < 1e-9:
                matches.append(row)
    if len(matches) != 1:
        raise ValueError(
            f"expected one {args.class_name} recommendation for band "
            f"({args.false_detection_min}, {args.false_detection_max}], found {len(matches)}"
        )
    ids = [int(value) for value in matches[0].get("missedDataIds") or []]
    if len(ids) != args.expected_miss_count:
        raise ValueError(
            f"Miss ordering changed: expected {args.expected_miss_count}, found {len(ids)}"
        )
    if len(ids) != len(set(ids)):
        raise ValueError("Miss list contains duplicate data IDs")
    return ids


def frame_names(data_ids: list[int]) -> dict[int, str]:
    result: dict[int, str] = {}
    for start in range(0, len(data_ids), 400):
        batch = data_ids[start:start + 400]
        rows = mysql_rows(
            "SELECT id,name FROM data WHERE is_deleted=0 AND id IN ("
            + ",".join(map(str, batch)) + ")"
        )
        result.update({int(row[0]): row[1] for row in rows})
    missing = [value for value in data_ids if value not in result]
    if missing:
        raise RuntimeError(f"unresolved data IDs: {missing[:10]}")
    ordered = [result[value] for value in data_ids]
    if len(ordered) != len(set(ordered)):
        raise ValueError("duplicate frame names make label filenames ambiguous")
    return result


def transform(args: argparse.Namespace, ids: list[int], names: dict[int, str], selected: set[int]):
    if max(selected) > len(ids):
        raise ValueError(f"range {max(selected)} exceeds Miss length {len(ids)}")
    rows = []
    for position, data_id in enumerate(ids, 1):
        is_selected = position in selected
        rows.append({
            "miss_position": position, "data_id": data_id,
            "frame_name": names[data_id], "selected": is_selected,
            "target_class": args.selected_class if is_selected else args.other_class,
            "label_file_exists": False, "source_class_lines": 0,
        })
    by_name = {row["frame_name"]: row for row in rows}
    selected_names = {row["frame_name"] for row in rows if row["selected"]}
    labels = sorted(args.label_dir.glob("*.txt"))
    if not labels:
        raise FileNotFoundError(f"no labels in {args.label_dir}")
    if args.label_dir.resolve() == args.output_label_dir.resolve():
        raise ValueError("output-label-dir must differ from label-dir")
    if args.output_label_dir.exists() and any(args.output_label_dir.iterdir()):
        raise FileExistsError(f"output directory is not empty: {args.output_label_dir}")
    if not args.dry_run:
        args.output_label_dir.mkdir(parents=True, exist_ok=False)

    pattern = re.compile(rf"^(\s*){re.escape(args.source_class)}(?=\s|$)")
    grader_count = excavator_count = selected_without_source = 0
    for source in labels:
        target = args.selected_class if source.stem in selected_names else args.other_class
        with source.open("r", encoding="utf-8", newline="") as handle:
            lines = handle.readlines()
        changed = 0
        output = []
        for line in lines:
            line, count = pattern.subn(lambda match: match.group(1) + target, line, count=1)
            output.append(line)
            changed += count
        if target == args.selected_class:
            grader_count += changed
        else:
            excavator_count += changed
        if source.stem in by_name:
            by_name[source.stem]["label_file_exists"] = True
            by_name[source.stem]["source_class_lines"] = changed
        if source.stem in selected_names and not changed:
            selected_without_source += 1
        if not args.dry_run:
            destination = args.output_label_dir / source.name
            with destination.open("w", encoding="utf-8", newline="") as handle:
                handle.writelines(output)
            shutil.copystat(source, destination)
    stats = {
        "labelFiles": len(labels), "missFrames": len(rows),
        "selectedMissPositions": len(selected),
        "vehicle2ToGrader": grader_count,
        "vehicle2ToExcavator": excavator_count,
        "selectedFilesWithoutVehicle2": selected_without_source,
        "selectedFramesWithoutLabelFile": sum(
            row["selected"] and not row["label_file_exists"] for row in rows
        ),
    }
    return stats, rows


def write_manifest(args: argparse.Namespace, stats: dict[str, int], rows: list[dict[str, Any]]):
    manifest = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "evaluationId": args.evaluation_id, "className": args.class_name,
        "falseDetectionBand": [args.false_detection_min, args.false_detection_max],
        "ranges": args.ranges, "sourceClass": args.source_class,
        "selectedClass": args.selected_class, "otherClass": args.other_class,
        "inputLabelDir": str(args.label_dir.resolve()),
        "outputLabelDir": str(args.output_label_dir.resolve()), "stats": stats,
    }
    (args.output_label_dir / "remap_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (args.output_label_dir / "remap_miss_frames.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation-id", type=int, default=29)
    parser.add_argument("--class-name", default="excavator_body")
    parser.add_argument("--false-detection-min", type=float, default=0.08)
    parser.add_argument("--false-detection-max", type=float, default=0.10)
    parser.add_argument("--expected-miss-count", type=int, default=1514)
    parser.add_argument("--ranges", default=DEFAULT_RANGES)
    parser.add_argument("--source-class", default="Vehicle2")
    parser.add_argument("--selected-class", default="Grader")
    parser.add_argument("--other-class", default="Excavator")
    parser.add_argument("--label-dir", type=Path, required=True)
    parser.add_argument("--output-label-dir", type=Path, required=True)
    parser.add_argument("--metrics-json", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        selected = parse_ranges(args.ranges)
        ids = missed_data_ids(load_metrics(args), args)
        stats, rows = transform(args, ids, frame_names(ids), selected)
        if not args.dry_run:
            write_manifest(args, stats, rows)
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        print("DRY RUN: no files written" if args.dry_run else f"Wrote {args.output_label_dir}")
        return 0
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
