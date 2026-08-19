# SPDX-License-Identifier: AGPL-3.0-only

"""Stage the Playbook public corpus for Hugging Face and optionally push it.

Copies an explicit manifest of matter packages, trajectories, dataset specs,
scorecards, the gate-probe regression suite, and key documentation into a
staging tree, writes a SHA-256 line for every staged file, and — with --push —
uploads that tree to a Hugging Face dataset repository. Staging is stdlib-only
and deterministic: the same repository tree always yields the same manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO_ID = "jamesbaker1/playbook"
DEFAULT_OUT = "build/hf"
DEFAULT_CARD = "docs/hf-dataset-card.md"
MANIFEST_NAME = "MANIFEST.sha256"


class Item(NamedTuple):
    """One manifest entry: a single file, or a directory tree filtered by suffix."""

    kind: str  # "file" or "tree"
    source: str  # path relative to the repository root
    dest: str  # path relative to the staging root
    suffixes: tuple[str, ...] = ()  # trees only; empty tuple means "every file"


# The upload set, listed explicitly rather than globbed, so a reviewer can read
# what leaves the repository. Code and the scoring engine stay on GitHub; this
# tree is the corpus, the evidence, and the documents needed to read them.
MANIFEST: tuple[Item, ...] = (
    # The twelve public matter packages: matter.yaml, rubric.yaml,
    # hidden_facts.yaml, documents/, and counterparty.yaml where one exists.
    Item("tree", "matters", "matters", (".yaml", ".md")),
    # Reference and adversarial trajectories per matter, plus the critic's
    # example client authority file.
    Item("tree", "examples", "examples", (".jsonl", ".yaml")),
    # Synthetic variant family specs and their seed trajectories.
    Item("tree", "datasets/families", "datasets/families", (".yaml", ".jsonl")),
    # The split registry and the variant build catalog.
    Item("file", "datasets/matter-families.yaml", "datasets/matter-families.yaml"),
    Item("file", "datasets/family-catalog.yaml", "datasets/family-catalog.yaml"),
    # Published scorecards: per-model, pooled, and the first rollout pilot.
    Item("tree", "results/v0.4.0", "results/v0.4.0", (".json", ".md")),
    # The two-teacher scaffolded rollout pilot (2026-08-08).
    Item("tree", "results/rollout-pilot-2", "results/rollout-pilot-2", (".json", ".md")),
    # The gate-probe regression suite frozen by the August 2026 instrument audit.
    Item("tree", "tests/gate_probes", "tests/gate_probes", (".yaml",)),
    # Documentation a reader needs to interpret the corpus without the code.
    Item("file", "docs/instrument-audit-2026-08.md", "docs/instrument-audit-2026-08.md"),
    Item("file", "docs/related-work.md", "docs/related-work.md"),
    Item("file", "docs/baseline-report.md", "docs/baseline-report.md"),
    Item("file", "docs/scoring.md", "docs/scoring.md"),
    Item("file", "docs/evaluation.md", "docs/evaluation.md"),
    Item("file", "docs/playbook-1-plan.md", "docs/playbook-1-plan.md"),
    Item("file", "docs/playbook-1-experiment.yaml", "docs/playbook-1-experiment.yaml"),
    Item("file", "docs/critic.md", "docs/critic.md"),
    # Licence and citation travel with the data.
    Item("file", "LICENSE", "LICENSE"),
    Item("file", "CITATION.cff", "CITATION.cff"),
)


def resolve(items: tuple[Item, ...], root: Path) -> list[tuple[Path, str]]:
    """Expand the manifest into sorted (absolute source, staging path) pairs."""
    pairs: list[tuple[Path, str]] = []
    missing: list[str] = []
    for item in items:
        source = root / item.source
        if not source.exists():
            missing.append(item.source)
            continue
        if item.kind == "file":
            if not source.is_file():
                missing.append(item.source)
                continue
            pairs.append((source, item.dest))
        elif item.kind == "tree":
            if not source.is_dir():
                missing.append(item.source)
                continue
            for path in source.rglob("*"):
                if not path.is_file():
                    continue
                if item.suffixes and path.suffix not in item.suffixes:
                    continue
                relative = path.relative_to(source).as_posix()
                pairs.append((path, f"{item.dest}/{relative}"))
        else:
            raise ValueError(f"unknown manifest kind {item.kind!r} for {item.source}")
    if missing:
        raise SystemExit(
            "manifest paths not found under "
            f"{root}:\n  " + "\n  ".join(sorted(missing))
        )
    pairs.sort(key=lambda pair: pair[1])
    return pairs


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def stage(root: Path, out: Path, card: Path) -> list[tuple[Path, str]]:
    """Rebuild the staging tree from scratch and return the staged pairs."""
    pairs = resolve(MANIFEST, root)
    pairs.append((card, "README.md"))  # the dataset card, checked by the caller
    pairs.sort(key=lambda pair: pair[1])

    if out.exists():
        shutil.rmtree(out)
    for source, dest in pairs:
        target = out / dest
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return pairs


def write_manifest(out: Path, pairs: list[tuple[Path, str]]) -> str:
    """Write MANIFEST.sha256 over every staged file and return its text."""
    lines = [f"{sha256(out / dest)}  {dest}" for _, dest in pairs]
    text = "\n".join(lines) + "\n"
    (out / MANIFEST_NAME).write_text(text, encoding="utf-8", newline="\n")
    return text


def hub_api():
    """Import huggingface_hub and resolve a token, or exit with instructions.

    Called before staging so a missing dependency or login fails immediately
    rather than after a full tree build.
    """
    try:
        from huggingface_hub import HfApi
    except ModuleNotFoundError:
        raise SystemExit(
            "--push needs the huggingface_hub package, which is not installed.\n"
            "  pip install huggingface_hub && hf auth login"
        ) from None

    try:
        from huggingface_hub import get_token
    except ImportError:  # older huggingface_hub
        get_token = None
    token = get_token() if get_token else None
    token = token or os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if not token:
        raise SystemExit(
            "no Hugging Face token found — refusing to push.\n"
            "  pip install huggingface_hub && hf auth login"
        )
    return HfApi(token=token)


def push(out: Path, repo_id: str, message: str, api) -> None:
    """Upload the staged tree to a Hugging Face dataset repository."""
    api.create_repo(repo_id=repo_id, repo_type="dataset", private=False, exist_ok=True)
    api.upload_folder(
        folder_path=str(out),
        repo_id=repo_id,
        repo_type="dataset",
        commit_message=message,
    )
    print(f"pushed {out} -> https://huggingface.co/datasets/{repo_id}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stage the Playbook public corpus for Hugging Face, and optionally push it.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--stage-only", action="store_true",
                      help="build the staging tree and print the SHA-256 manifest")
    mode.add_argument("--push", action="store_true",
                      help="build the staging tree, then upload it to the dataset repo")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT,
                        help=f"Playbook checkout to stage from (default: {REPO_ROOT})")
    parser.add_argument("--out", type=Path, default=None,
                        help=f"staging directory (default: <repo-root>/{DEFAULT_OUT})")
    parser.add_argument("--card", type=Path, default=None,
                        help=f"dataset card staged as README.md (default: <repo-root>/{DEFAULT_CARD})")
    parser.add_argument("--repo-id", default=DEFAULT_REPO_ID,
                        help=f"Hugging Face dataset repo id (default: {DEFAULT_REPO_ID})")
    parser.add_argument("--commit-message", default="Publish Playbook public corpus",
                        help="commit message for --push")
    args = parser.parse_args()

    root = args.repo_root.resolve()
    out = (args.out or root / DEFAULT_OUT).resolve()
    card = (args.card or root / DEFAULT_CARD).resolve()
    if not root.is_dir():
        raise SystemExit(f"repo root not found: {root}")
    if not card.is_file():
        raise SystemExit(
            f"dataset card not found: {card}\n"
            f"  land the Hugging Face card at <repo-root>/{DEFAULT_CARD}, or pass --card"
        )
    api = hub_api() if args.push else None

    pairs = stage(root, out, card)
    text = write_manifest(out, pairs)
    total = sum((out / dest).stat().st_size for _, dest in pairs)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()

    sys.stdout.write(text)
    print(f"\n{len(pairs)} files, {total} bytes staged in {out}")
    print(f"manifest sha256: {digest}")

    if args.push:
        push(out, args.repo_id, args.commit_message, api)


if __name__ == "__main__":
    main()
