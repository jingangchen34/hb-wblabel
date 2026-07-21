#!/usr/bin/env python3
"""Export embedded KITTI annotations from a kitti_infos_*.pkl to label TXT files."""

from __future__ import annotations

import argparse
import json
import pickle
import sys
from pathlib import Path
from typing import Any


def values_at(values: Any, index: int, default: Any) -> Any:
    if values is None or index >= len(values):
        return default
    return values[index]


def numbers(values: Any, count: int, default: float = 0.0) -> list[float]:
    result = [float(value) for value in values] if values is not None else []
    return (result + [default] * count)[:count]


def number(value: Any) -> str:
    return format(float(value), ".15g")


def frame_index(info: dict[str, Any]) -> str:
    velodyne_path = info.get("velodyne_path")
    if velodyne_path:
        return Path(str(velodyne_path)).stem
    image_idx = info.get("image_idx")
    if image_idx is None:
        image_idx = (info.get("point_cloud") or {}).get("lidar_idx")
    if image_idx is None:
        raise ValueError("info has neither velodyne_path nor image_idx")
    return f"{int(image_idx):06d}"


def annotation_lines(info: dict[str, Any]) -> list[str]:
    annos = info.get("annos") or {}
    names = annos.get("name")
    if names is None:
        return []
    lines = []
    for index, raw_name in enumerate(names):
        name = str(raw_name)
        truncated = values_at(annos.get("truncated"), index, 0.0)
        occluded = values_at(annos.get("occluded"), index, 0)
        alpha = values_at(annos.get("alpha"), index, 0.0)
        bbox = numbers(values_at(annos.get("bbox"), index, None), 4)
        dimensions = numbers(values_at(annos.get("dimensions"), index, None), 3)
        location = numbers(values_at(annos.get("location"), index, None), 3)
        rotation_y = values_at(annos.get("rotation_y"), index, 0.0)
        # SECOND stores dimensions as [length, height, width]. KITTI TXT uses
        # [height, width, length].
        kitti_dimensions = [dimensions[1], dimensions[2], dimensions[0]]
        fields = [
            name,
            number(truncated),
            str(int(occluded)),
            number(alpha),
            *(number(value) for value in bbox),
            *(number(value) for value in kitti_dimensions),
            *(number(value) for value in location),
            number(rotation_y),
        ]
        lines.append(" ".join(fields) + "\n")
    return lines


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--info-pkl", type=Path, required=True)
    parser.add_argument("--output-label-dir", type=Path, required=True)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        with args.info_pkl.open("rb") as handle:
            infos = pickle.load(handle)
        if not isinstance(infos, (list, tuple)):
            raise ValueError("KITTI info PKL must contain a list of frame dictionaries")
        if args.output_label_dir.exists() and any(args.output_label_dir.iterdir()):
            raise FileExistsError(f"output directory is not empty: {args.output_label_dir}")

        prepared: list[tuple[str, list[str]]] = []
        seen: set[str] = set()
        class_counts: dict[str, int] = {}
        object_count = 0
        for info in infos:
            index = frame_index(info)
            if index in seen:
                raise ValueError(f"duplicate frame index in PKL: {index}")
            seen.add(index)
            lines = annotation_lines(info)
            prepared.append((index, lines))
            object_count += len(lines)
            for line in lines:
                class_name = line.split(maxsplit=1)[0]
                class_counts[class_name] = class_counts.get(class_name, 0) + 1

        stats = {
            "frames": len(prepared),
            "objects": object_count,
            "emptyFrames": sum(not lines for _, lines in prepared),
            "classes": dict(sorted(class_counts.items())),
        }
        if not args.dry_run:
            args.output_label_dir.mkdir(parents=True, exist_ok=False)
            for index, lines in prepared:
                (args.output_label_dir / f"{index}.txt").write_text(
                    "".join(lines), encoding="utf-8"
                )
            (args.output_label_dir.parent / f"{args.output_label_dir.name}_manifest.json").write_text(
                json.dumps(
                    {
                        "sourcePkl": str(args.info_pkl.resolve()),
                        "outputLabelDir": str(args.output_label_dir.resolve()),
                        **stats,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        print("DRY RUN: no files written" if args.dry_run else f"Wrote {args.output_label_dir}")
        return 0
    except (OSError, ValueError, pickle.PickleError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
