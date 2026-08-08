"""Regression probes for the guarded critical-failure gates shipped in the corpus.

``tests/gate_probes/<matter_id>.yaml`` records, for one shipped matter, the sentences
that decide whether its gates are correctly tempered: replay-confirmed false positives
(correct work the bare regexes used to cap at 0.25, ``expect_fire: false``) and each
gate's canonical sin plus every trivial dodge closed during the migration
(``expect_fire: true``). ``variant_specs.yaml`` does the same for the gates that a
training-family spec declares through ``set_authority_bundle``.

Each entry is checked with :func:`playbook_legal.rewards.gate_match` against the gates
the *live* rubric (or spec) carries for that criterion and surface, over engine-
normalized text — so loosening a guard, renaming a criterion, or deleting a gate list
fails here rather than silently at scoring time. A probe that names a criterion or a
surface the rubric no longer declares is an error, never a skip.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import MATTERS, ROOT

from playbook_legal.rewards import gate_match, gate_spec_errors
from playbook_legal.text import normalize_text

PROBE_DIR = ROOT / "tests" / "gate_probes"
FAMILY_DIR = ROOT / "datasets" / "families"

# Probe surface -> the rubric field the engine reads on that scoring surface.
SURFACE_FIELDS = {
    "issue": "critical_failure_patterns",
    "redline": "redline_critical_failure_patterns",
    "settlement": "settlement_critical_failure_patterns",
}

REQUIRED_KEYS = {"surface", "criterion", "text", "expect_fire"}
OPTIONAL_KEYS = {"spec"}

PROBE_FILES = sorted(PROBE_DIR.glob("*.yaml"))


def _load_probes(path: Path) -> list[dict[str, Any]]:
    """Return the probe entries in ``path``.

    A file is either a mapping with a ``probes`` list or a bare list of entries; both
    shapes ship in the corpus and both are read the same way.
    """
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    probes = document.get("probes") if isinstance(document, dict) else document
    if not isinstance(probes, list) or not probes:
        raise AssertionError(f"{path.name}: expected a non-empty list of probe entries")
    return probes


def _probe_cases() -> list[tuple[Path, int, dict[str, Any]]]:
    cases: list[tuple[Path, int, dict[str, Any]]] = []
    for path in PROBE_FILES:
        for index, entry in enumerate(_load_probes(path)):
            cases.append((path, index, entry))
    return cases


PROBE_CASES = _probe_cases()


def _case_id(case: tuple[Path, int, dict[str, Any]]) -> str:
    path, index, entry = case
    fire = "fire" if entry.get("expect_fire") else "silent"
    return f"{path.stem}[{index:02d}]-{entry.get('surface')}-{entry.get('criterion')}-{fire}"


@cache
def _rubric_issues(matter_id: str) -> tuple[dict[str, Any], ...]:
    path = MATTERS / matter_id / "rubric.yaml"
    if not path.exists():
        raise AssertionError(
            f"gate probe file names matter {matter_id!r}, but {path} does not exist"
        )
    rubric = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return tuple(rubric.get("issues", []))


@cache
def _spec_document(spec_name: str) -> dict[str, Any]:
    path = FAMILY_DIR / spec_name
    if not path.exists():
        raise AssertionError(f"gate probe names spec {spec_name!r}, but {path} does not exist")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _matter_gates(matter_id: str, criterion: str, field: str) -> list[Any]:
    issues = [issue for issue in _rubric_issues(matter_id) if str(issue.get("id")) == criterion]
    if len(issues) != 1:
        available = sorted(str(issue.get("id")) for issue in _rubric_issues(matter_id))
        raise AssertionError(
            f"criterion {criterion!r} resolved {len(issues)} times in "
            f"matters/{matter_id}/rubric.yaml; declared issues are {available}"
        )
    gates = issues[0].get(field)
    if not isinstance(gates, list) or not gates:
        raise AssertionError(
            f"matters/{matter_id}/rubric.yaml issue {criterion!r} declares no {field}; "
            "the probe references a gate list that no longer exists"
        )
    return gates


def _spec_gates(spec_name: str, criterion: str, field: str) -> list[Any]:
    """Return the gates the named family spec itself declares for ``criterion``.

    Only the variant whose ``set_authority_bundle`` writes the field owns these gates:
    sibling variants of the same family inherit the base matter's, so unioning across
    a family would probe patterns the spec never touched.
    """
    document = _spec_document(spec_name)
    declared = [
        transform["rubric_fields"][field]
        for variant in document.get("variants", [])
        for transform in variant.get("transforms", [])
        if transform.get("type") == "set_authority_bundle"
        and str(transform.get("issue_id")) == criterion
        and isinstance(transform.get("rubric_fields"), dict)
        and field in transform["rubric_fields"]
    ]
    if len(declared) != 1:
        raise AssertionError(
            f"datasets/families/{spec_name} declares {field} for issue {criterion!r} "
            f"{len(declared)} times; a probe needs exactly one declaring variant"
        )
    gates = declared[0]
    if not isinstance(gates, list) or not gates:
        raise AssertionError(
            f"datasets/families/{spec_name} declares an empty {field} for {criterion!r}"
        )
    return gates


def _gates_for(path: Path, entry: dict[str, Any]) -> list[Any]:
    surface = str(entry["surface"])
    if surface not in SURFACE_FIELDS:
        raise AssertionError(
            f"unknown probe surface {surface!r}; expected one of {sorted(SURFACE_FIELDS)}"
        )
    field = SURFACE_FIELDS[surface]
    criterion = str(entry["criterion"])
    if "spec" in entry:
        return _spec_gates(str(entry["spec"]), criterion, field)
    return _matter_gates(path.stem, criterion, field)


@pytest.mark.parametrize("path,index,entry", PROBE_CASES, ids=[_case_id(c) for c in PROBE_CASES])
def test_probe_files_are_well_formed(path: Path, index: int, entry: dict[str, Any]) -> None:
    assert isinstance(entry, dict), f"{path.name}[{index}] is not a mapping"
    keys = set(entry)
    missing = REQUIRED_KEYS - keys
    unknown = keys - REQUIRED_KEYS - OPTIONAL_KEYS
    assert not missing, f"{path.name}[{index}] is missing {sorted(missing)}"
    assert not unknown, f"{path.name}[{index}] has unknown key(s) {sorted(unknown)}"
    assert isinstance(entry["expect_fire"], bool), (
        f"{path.name}[{index}] expect_fire must be true or false"
    )
    assert isinstance(entry["text"], str) and entry["text"].strip(), (
        f"{path.name}[{index}] text must be a non-empty string"
    )
    assert ("spec" in entry) == (path.name == "variant_specs.yaml"), (
        f"{path.name}[{index}]: only variant_specs.yaml entries carry a 'spec' key, "
        "because only there do the gates live outside matters/"
    )


@pytest.mark.parametrize("path,index,entry", PROBE_CASES, ids=[_case_id(c) for c in PROBE_CASES])
def test_gate_probe_behaves_as_declared(path: Path, index: int, entry: dict[str, Any]) -> None:
    gates = _gates_for(path, entry)
    for position, gate in enumerate(gates):
        errors = gate_spec_errors(gate)
        assert not errors, f"{path.name}[{index}] gate #{position} is malformed: {errors}"

    text = normalize_text(entry["text"])
    fired = [gate_match(gate, text) for gate in gates]
    matched = [pattern for pattern in fired if pattern is not None]
    expect_fire = bool(entry["expect_fire"])

    source = entry.get("spec", f"matters/{path.stem}/rubric.yaml")
    if expect_fire:
        assert matched, (
            f"{path.name}[{index}] expected a gate on {entry['surface']}/"
            f"{entry['criterion']} to fire, but none of the {len(gates)} gates in "
            f"{source} matched: {entry['text']!r}"
        )
    else:
        assert not matched, (
            f"{path.name}[{index}] expected no gate on {entry['surface']}/"
            f"{entry['criterion']} to fire, but {matched} matched in {source}: "
            f"{entry['text']!r}"
        )


def _structured_gate_matters() -> list[str]:
    matters = []
    for matter_dir in sorted(MATTERS.iterdir()):
        rubric_path = matter_dir / "rubric.yaml"
        if not rubric_path.exists():
            continue
        rubric = yaml.safe_load(rubric_path.read_text(encoding="utf-8")) or {}
        structured = any(
            isinstance(gate, dict)
            for issue in rubric.get("issues", [])
            for field in SURFACE_FIELDS.values()
            for gate in issue.get(field) or []
        )
        if structured:
            matters.append(matter_dir.name)
    return matters


@pytest.mark.parametrize("matter_id", _structured_gate_matters())
def test_every_matter_with_guarded_gates_ships_probes(matter_id: str) -> None:
    """A guard is only as good as the sentences that prove it, so probes are required."""
    assert (PROBE_DIR / f"{matter_id}.yaml").exists(), (
        f"matters/{matter_id}/rubric.yaml carries guarded gates but "
        f"tests/gate_probes/{matter_id}.yaml is missing"
    )
