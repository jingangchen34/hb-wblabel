#!/usr/bin/env python3
"""Rename Vehicle2 in KITTI label_2 using a prepared original-index list.

Files whose stem is present in the Grader index list use ``Grader``. All other
``Vehicle2`` rows use ``Excavator``. Source files are never modified.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_GRADER_INDICES = Path(__file__).with_name("data") / "miss1514_grader_indices.txt"


def load_indices(path: Path) -> set[str]:
    values = {
        line.strip()
        for line in path.read_text(encoding="utf-8-sig").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    if not values:
        raise ValueError(f"index file is empty: {path}")
    invalid = sorted(value for value in values if not re.fullmatch(r"\d+", value))
    if invalid:
        raise ValueError(f"invalid original indices in {path}: {invalid[:10]}")
    return values


def read_lines(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return handle.readlines()


def write_lines(path: Path, lines: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.writelines(lines)


def write_index_file(path: Path, values: list[str]) -> None:
    path.write_text("\n".join(values) + ("\n" if values else ""), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label-dir", type=Path, required=True)
    parser.add_argument(
        "--output-label-dir",
        type=Path,
        help="default: a label_2_rename sibling of label-dir",
    )
    parser.add_argument(
        "--grader-index-file",
        type=Path,
        default=DEFAULT_GRADER_INDICES,
        help="one original frame index per line",
    )
    parser.add_argument("--source-class", default="Vehicle2")
    parser.add_argument("--grader-class", default="Grader")
    parser.add_argument("--excavator-class", default="Excavator")
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="continue if a requested Grader index has no Vehicle2 label",
    )
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        label_dir = args.label_dir.resolve()
        output_dir = (
            args.output_label_dir.resolve()
            if args.output_label_dir
            else label_dir.with_name("label_2_rename")
        )
        if output_dir == label_dir:
            raise ValueError("output-label-dir must differ from label-dir")
        if output_dir.exists() and any(output_dir.iterdir()):
            raise FileExistsError(f"output directory is not empty: {output_dir}")

        grader_requested = load_indices(args.grader_index_file)
        labels = sorted(label_dir.glob("*.txt"))
        if not labels:
            raise FileNotFoundError(f"no .txt files in {label_dir}")
        label_by_index = {path.stem: path for path in labels}
        pattern = re.compile(rf"^(\s*){re.escape(args.source_class)}(?=\s|$)")

        prepared: list[tuple[Path, list[str], str, int]] = []
        grader_converted: list[str] = []
        excavator_converted: list[str] = []
        grader_missing_file = sorted(grader_requested - set(label_by_index))
        grader_without_vehicle2: list[str] = []

        for source in labels:
            is_grader = source.stem in grader_requested
            target_class = args.grader_class if is_grader else args.excavator_class
            output_lines: list[str] = []
            changed = 0
            for line in read_lines(source):
                rewritten, count = pattern.subn(
                    lambda match: match.group(1) + target_class, line, count=1
                )
                output_lines.append(rewritten)
                changed += count
            if changed:
                (grader_converted if is_grader else excavator_converted).append(source.stem)
            elif is_grader:
                grader_without_vehicle2.append(source.stem)
            prepared.append((source, output_lines, target_class, changed))

        if (grader_missing_file or grader_without_vehicle2) and not args.allow_missing:
            raise ValueError(
                "Grader list does not match this label_2: "
                f"missing files={len(grader_missing_file)}, "
                f"files without {args.source_class}={len(grader_without_vehicle2)}. "
                "Use the correct original label directory; --allow-missing is only for intentional gaps."
            )

        stats = {
            "labelFiles": len(labels),
            "graderRequestedIndices": len(grader_requested),
            "graderConvertedIndices": len(grader_converted),
            "graderConvertedBoxes": sum(
                changed for _, _, target, changed in prepared if target == args.grader_class
            ),
            "excavatorConvertedIndices": len(excavator_converted),
            "excavatorConvertedBoxes": sum(
                changed for _, _, target, changed in prepared if target == args.excavator_class
            ),
            "graderMissingFiles": len(grader_missing_file),
            "graderFilesWithoutVehicle2": len(grader_without_vehicle2),
        }

        if not args.dry_run:
            output_dir.mkdir(parents=True, exist_ok=False)
            for source, lines, _, _ in prepared:
                destination = output_dir / source.name
                write_lines(destination, lines)
                shutil.copystat(source, destination)
            prefix = output_dir.parent / output_dir.name
            write_index_file(prefix.with_name(prefix.name + "_grader_indices.txt"), grader_converted)
            write_index_file(
                prefix.with_name(prefix.name + "_excavator_indices.txt"), excavator_converted
            )
            manifest = {
                "generatedAt": datetime.now(timezone.utc).isoformat(),
                "inputLabelDir": str(label_dir),
                "outputLabelDir": str(output_dir),
                "graderIndexFile": str(args.grader_index_file.resolve()),
                "sourceClass": args.source_class,
                "graderClass": args.grader_class,
                "excavatorClass": args.excavator_class,
                "graderMissingFileIndices": grader_missing_file,
                "graderIndicesWithoutVehicle2": grader_without_vehicle2,
                "stats": stats,
            }
            prefix.with_name(prefix.name + "_manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )

        print(json.dumps(stats, ensure_ascii=False, indent=2))
        print("DRY RUN: no files written" if args.dry_run else f"Wrote {output_dir}")
        return 0
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
