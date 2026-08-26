#!/usr/bin/env python3
"""Archive every OCC clip below a directory without modifying source data.

A clip is identified by a ``meta.json`` file.  By default, a clip directory
``parent/clip-name`` is written to ``parent/clip-name.zip`` and the archive
contains one top-level directory named ``clip-name``.
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import zipfile
from pathlib import Path


def find_clips(root: Path) -> list[Path]:
    clips = {path.parent for path in root.rglob("meta.json") if path.is_file()}
    return sorted(clips, key=lambda path: path.as_posix())


def archive_path_for(clip: Path, output_dir: Path | None) -> Path:
    parent = output_dir if output_dir is not None else clip.parent
    return parent / f"{clip.name}.zip"


def iter_clip_files(clip: Path):
    for path in sorted(clip.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_file():
            yield path


def verify_archive(archive: Path, clip: Path, source_file_count: int) -> None:
    expected_meta = f"{clip.name}/meta.json"
    with zipfile.ZipFile(archive, "r") as handle:
        bad_file = handle.testzip()
        if bad_file:
            raise RuntimeError(f"CRC verification failed for {bad_file}")
        files = [info.filename for info in handle.infolist() if not info.is_dir()]
        if expected_meta not in files:
            raise RuntimeError(f"archive is missing {expected_meta}")
        if len(files) != source_file_count:
            raise RuntimeError(
                f"file-count mismatch: source={source_file_count}, archive={len(files)}"
            )


def create_archive(
    clip: Path,
    destination: Path,
    *,
    overwrite: bool,
    compresslevel: int,
) -> tuple[int, int]:
    if destination.exists() and not overwrite:
        raise FileExistsError(f"already exists: {destination}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    files = list(iter_clip_files(clip))
    if not files:
        raise RuntimeError(f"clip contains no files: {clip}")

    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(
            temporary,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=compresslevel,
            allowZip64=True,
        ) as handle:
            for source in files:
                archive_name = Path(clip.name) / source.relative_to(clip)
                handle.write(source, archive_name.as_posix())

        verify_archive(temporary, clip, len(files))
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)

    return len(files), destination.stat().st_size


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create one verified ZIP archive beside every OCC clip."
    )
    parser.add_argument("root", type=Path, help="Root directory containing OCC clips")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Write all archives here instead of beside each clip",
    )
    parser.add_argument("--overwrite", action="store_true", help="Replace existing ZIP files")
    parser.add_argument("--dry-run", action="store_true", help="Only list planned archives")
    parser.add_argument(
        "--compresslevel",
        type=int,
        default=6,
        choices=range(0, 10),
        metavar="0-9",
        help="ZIP deflate level (default: 6)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.root.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve() if args.output_dir else None
    if not root.is_dir():
        print(f"ERROR: root directory does not exist: {root}", file=sys.stderr)
        return 2

    clips = find_clips(root)
    if not clips:
        print(f"ERROR: no clips containing meta.json found below {root}", file=sys.stderr)
        return 2

    print(f"Found {len(clips)} clips below {root}")
    succeeded = skipped = failed = 0
    for index, clip in enumerate(clips, start=1):
        destination = archive_path_for(clip, output_dir)
        prefix = f"[{index}/{len(clips)}]"
        if args.dry_run:
            print(f"{prefix} {clip} -> {destination}")
            continue
        if destination.exists() and not args.overwrite:
            print(f"{prefix} SKIP existing {destination}")
            skipped += 1
            continue
        try:
            file_count, byte_count = create_archive(
                clip,
                destination,
                overwrite=args.overwrite,
                compresslevel=args.compresslevel,
            )
            print(f"{prefix} OK {destination} ({file_count} files, {byte_count / 1024**2:.1f} MiB)")
            succeeded += 1
        except Exception as exc:
            print(f"{prefix} ERROR {clip}: {exc}", file=sys.stderr)
            failed += 1

    print(f"Done: created={succeeded}, skipped={skipped}, failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
