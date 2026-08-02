"""Copy or verify canonical local source and matter packs in the Worker bundle."""

from __future__ import annotations

import argparse
import filecmp
import shutil
from pathlib import Path

WORKER = Path(__file__).resolve().parent
REPO = WORKER.parent
DESTINATIONS = {
    REPO / "src" / "playbook_legal": WORKER / "src" / "playbook_legal",
    REPO / "matters": WORKER / "src" / "matters",
}

IGNORED_NAMES = {"__pycache__"}
IGNORED_SUFFIXES = {".pyc"}


def _files(root: Path) -> set[Path]:
    return {
        path.relative_to(root)
        for path in root.rglob("*")
        if path.is_file()
        and not any(part in IGNORED_NAMES for part in path.relative_to(root).parts)
        and path.suffix not in IGNORED_SUFFIXES
    }


def verify(source: Path, destination: Path) -> list[str]:
    """Return human-readable differences between a source and vendored tree."""
    if not destination.is_dir():
        return [f"missing vendor directory: {destination.relative_to(REPO)}"]
    source_files = _files(source)
    destination_files = _files(destination)
    differences = [f"missing vendor file: {path}" for path in sorted(source_files - destination_files)]
    differences.extend(f"unexpected vendor file: {path}" for path in sorted(destination_files - source_files))
    differences.extend(
        f"stale vendor file: {path}"
        for path in sorted(source_files & destination_files)
        if not filecmp.cmp(source / path, destination / path, shallow=False)
    )
    return differences


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="fail unless every vendored file matches its source"
    )
    args = parser.parse_args()
    if args.check:
        differences = [
            difference
            for source, destination in DESTINATIONS.items()
            for difference in verify(source, destination)
        ]
        if differences:
            for difference in differences:
                print(difference)
            return 1
        print("Engine Worker vendor bundle matches canonical source and matters.")
        return 0

    for source, destination in DESTINATIONS.items():
        if destination.exists():
            shutil.rmtree(destination)
        shutil.copytree(source, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        print(f"Vendored {source.relative_to(REPO)} -> {destination.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
