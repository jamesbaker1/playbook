# SPDX-License-Identifier: AGPL-3.0-only

"""Evaluate the frozen Playbook-1 release gates against per-condition episode rows.

``docs/playbook-1-experiment.yaml`` fixes the decision rules before any condition is
measured, so this module only reads the contract: every gate, comparison, allowance
and confidence level comes from the file rather than from a flag. Feed it the bench
scorecards for each condition and it returns the verdict the preregistration implies.

The primary gate is a one-sided cluster bootstrap over matter families; the remaining
gates are guardrails that compare condition means and fail when a regression exceeds
its declared allowance.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .experiment import load_experiment_contract
from .metrics import cluster_bootstrap_difference

# Rate metrics are means of per-episode indicators, matching ``aggregate_metrics``.
EPISODE_INDICATORS = {
    "critical_failure_rate": "critical_failure",
    "completion_rate": "terminated",
    "protocol_failure_rate": "protocol_failures",
}
RELATIONS = ("lt", "gt", "vs")
# Condition means are rounded to four decimals before a gate compares them, so an
# allowance met exactly is not lost to binary floating-point representation.
PRECISION = 4
EPSILON = 1e-9


def _round(value: float) -> float:
    """Round to the reporting precision, normalizing a rounded -0.0 back to 0.0."""
    return round(value, PRECISION) + 0.0


def parse_comparison(comparison: str, condition_ids: list[str]) -> tuple[str, str, str]:
    """Split ``<treatment>_<relation>_<control>`` into declared condition ids."""
    for relation in RELATIONS:
        for treatment in condition_ids:
            for control in condition_ids:
                if comparison == f"{treatment}_{relation}_{control}":
                    return treatment, control, relation
    raise ValueError(
        f"unsupported comparison {comparison!r}: expected "
        f"<treatment>_({'|'.join(RELATIONS)})_<control> naming two declared conditions"
    )


def episode_values(rows: list[dict[str, Any]], metric: str) -> list[float]:
    """Per-episode values for one metric, deriving rate metrics from their indicator.

    A missing indicator raises rather than defaulting to zero: a release gate must not
    silently score an absent column as a perfect result.
    """
    key = EPISODE_INDICATORS.get(metric)
    if key is not None:
        if any(key not in row for row in rows):
            raise ValueError(f"episode rows do not carry {key!r}, required for {metric}")
        return [float(bool(row[key])) for row in rows]
    if any(metric not in row for row in rows):
        raise ValueError(f"episode rows do not carry {metric!r}")
    return [float(row[metric]) for row in rows]


def condition_mean(rows: list[dict[str, Any]], metric: str) -> float:
    """Episode-weighted mean of one metric across a condition's episodes."""
    values = episode_values(rows, metric)
    if not values:
        raise ValueError(f"no episodes to average for {metric!r}")
    return _round(sum(values) / len(values))


def _bootstrap_gate(
    gate: dict[str, Any],
    rows_by_condition: dict[str, list[dict[str, Any]]],
    *,
    treatment: str,
    control: str,
    relation: str,
    confidence_level: float,
    family_key: str,
    samples: int,
    seed: int,
) -> dict[str, Any]:
    """Apply ``one_sided_cluster_bootstrap_ci_excludes_zero`` to one gate."""
    metric = gate["metric"]
    if gate.get("direction") != "minimize" or relation != "lt":
        raise ValueError(
            f"{metric}: the one-sided bootstrap decision rule is defined for a minimized "
            f"metric with a '_lt_' comparison, got direction {gate.get('direction')!r} "
            f"and relation {relation!r}"
        )
    tolerance = float(gate.get("tolerance", 0.0))
    bootstrap = cluster_bootstrap_difference(
        rows_by_condition[treatment],
        rows_by_condition[control],
        metric,
        family_key=family_key,
        samples=samples,
        confidence_level=confidence_level,
        seed=seed,
        one_sided=True,
    )
    # tolerance is the margin on the difference; the frozen contract sets it to 0, so
    # the gate is the preregistered strict-superiority test.
    passed = bootstrap["upper"] < tolerance
    return {
        "metric": metric,
        "direction": gate["direction"],
        "comparison": gate["comparison"],
        "decision_rule": gate["decision_rule"],
        "treatment": treatment,
        "control": control,
        "treatment_mean": condition_mean(rows_by_condition[treatment], metric),
        "control_mean": condition_mean(rows_by_condition[control], metric),
        "difference": bootstrap["estimate"],
        "tolerance": tolerance,
        "confidence_level": confidence_level,
        "excludes_zero": bootstrap["excludes_zero"],
        "bootstrap": bootstrap,
        "passed": bool(passed),
        "detail": (
            f"{treatment} - {control} = {bootstrap['estimate']} "
            f"(one-sided {confidence_level:.0%} upper bound {bootstrap['upper']}, "
            f"must be below {tolerance})"
        ),
    }


def _regression_gate(
    gate: dict[str, Any],
    rows_by_condition: dict[str, list[dict[str, Any]]],
    *,
    treatment: str,
    control: str,
) -> dict[str, Any]:
    """Apply a ``maximum_regression`` guardrail to one gate."""
    metric = gate["metric"]
    direction = gate.get("direction")
    if direction not in {"minimize", "maximize"}:
        raise ValueError(f"{metric}: gate direction must be minimize or maximize")
    allowance = float(gate["maximum_regression"])
    treatment_mean = condition_mean(rows_by_condition[treatment], metric)
    control_mean = condition_mean(rows_by_condition[control], metric)
    difference = _round(treatment_mean - control_mean)
    # A positive regression always means "the treatment is worse than the control".
    regression = _round(-difference if direction == "maximize" else difference)
    passed = regression <= allowance + EPSILON
    return {
        "metric": metric,
        "direction": direction,
        "comparison": gate["comparison"],
        "decision_rule": "condition_mean_regression_within_allowance",
        "treatment": treatment,
        "control": control,
        "treatment_mean": treatment_mean,
        "control_mean": control_mean,
        "difference": difference,
        "regression": regression,
        "maximum_regression": allowance,
        "passed": bool(passed),
        "detail": (
            f"{treatment} {treatment_mean} vs {control} {control_mean}: "
            f"regression {regression} against an allowance of {allowance}"
        ),
    }


def _per_family_report(
    rows_by_condition: dict[str, list[dict[str, Any]]],
    metric: str,
    *,
    family_key: str,
    report_per_family: bool,
    treatment: str | None,
    control: str | None,
) -> dict[str, Any]:
    """Break the primary metric out by matter family, as the contract requires."""
    report: dict[str, Any] = {
        "metric": metric,
        "report_per_family": report_per_family,
        "resampling_unit": "matter_family",
        "treatment": treatment,
        "control": control,
        "families": [],
    }
    if not report_per_family:
        return report
    family_ids = sorted(
        {
            str(row[family_key])
            for rows in rows_by_condition.values()
            for row in rows
            if family_key in row
        }
    )
    for family_id in family_ids:
        entry: dict[str, Any] = {"matter_family_id": family_id, "conditions": {}}
        for condition, rows in rows_by_condition.items():
            family_rows = [row for row in rows if str(row.get(family_key)) == family_id]
            if not family_rows:
                continue
            entry["conditions"][condition] = {
                "episodes": len(family_rows),
                "value": condition_mean(family_rows, metric),
            }
        pair = entry["conditions"]
        entry["difference"] = (
            _round(pair[treatment]["value"] - pair[control]["value"])
            if treatment in pair and control in pair
            else None
        )
        report["families"].append(entry)
    return report


def _secondary_reporting(
    contract: dict[str, Any],
    rows_by_condition: dict[str, list[dict[str, Any]]],
    condition_ids: list[str],
    *,
    confidence_level: float,
    family_key: str,
    samples: int,
    seed: int,
) -> list[dict[str, Any]]:
    """Compute the contract's secondary reporting; these entries never gate a release."""
    entries: list[dict[str, Any]] = []
    for item in contract.get("secondary_reporting", []) or []:
        metric = item.get("metric")
        report: dict[str, Any] = {
            "metric": metric,
            "purpose": item.get("purpose"),
            "reporting_only": True,
        }
        if item.get("comparison"):
            treatment, control, relation = parse_comparison(item["comparison"], condition_ids)
            bootstrap = cluster_bootstrap_difference(
                rows_by_condition[treatment],
                rows_by_condition[control],
                metric,
                family_key=family_key,
                samples=samples,
                confidence_level=confidence_level,
                seed=seed,
                one_sided=relation != "vs",
            )
            report |= {
                "comparison": item["comparison"],
                "treatment": treatment,
                "control": control,
                "treatment_mean": condition_mean(rows_by_condition[treatment], metric),
                "control_mean": condition_mean(rows_by_condition[control], metric),
                "excludes_zero": bootstrap["excludes_zero"],
                "bootstrap": bootstrap,
            }
            entries.append(report)
            continue

        by_condition: dict[str, Any] = {}
        available = True
        for condition, rows in rows_by_condition.items():
            try:
                value = condition_mean(rows, metric)
            except ValueError as exc:
                available = False
                by_condition[condition] = {"available": False, "reason": str(exc)}
                continue
            by_condition[condition] = {
                "available": True,
                "episodes": len(rows),
                "value": value,
            }
        report |= {
            "scope": item.get("scope", "per_condition"),
            "available": available,
            "by_condition": by_condition,
        }
        entries.append(report)
    return entries


def evaluate_release_gates(
    contract: dict[str, Any],
    rows_by_condition: dict[str, list[dict[str, Any]]],
    *,
    family_key: str = "matter_family_id",
    samples: int = 2000,
    seed: int = 0,
) -> dict[str, Any]:
    """Score the contract's release gates and secondary reporting against episode rows.

    ``rows_by_condition`` maps a contract condition id to that condition's per-episode
    metric rows. Only the conditions the contract's gates and secondary reporting refer
    to are required, so the evaluator runs long before every condition has been trained.
    """
    condition_ids = [item["id"] for item in contract.get("conditions", []) if isinstance(item, dict)]
    unknown = sorted(set(rows_by_condition) - set(condition_ids))
    if unknown:
        raise ValueError(
            f"condition(s) not declared in the contract: {', '.join(unknown)}; "
            f"declared conditions are {', '.join(condition_ids)}"
        )

    gates = contract.get("release_gates", []) or []
    comparisons = [gate.get("comparison") for gate in gates]
    comparisons += [
        item["comparison"]
        for item in contract.get("secondary_reporting", []) or []
        if item.get("comparison")
    ]
    required: list[str] = []
    for comparison in comparisons:
        if not comparison:
            raise ValueError("every release gate must declare a comparison")
        treatment, control, _ = parse_comparison(comparison, condition_ids)
        required += [treatment, control]
    required = [condition for condition in condition_ids if condition in set(required)]
    missing = [
        condition
        for condition in required
        if not rows_by_condition.get(condition)
    ]
    if missing:
        raise ValueError(
            f"no episode rows for condition(s): {', '.join(missing)}; "
            f"the contract's gates and secondary reporting need {', '.join(required)}"
        )

    ordered = {
        condition: rows_by_condition[condition]
        for condition in condition_ids
        if condition in rows_by_condition
    }
    uncertainty = contract.get("uncertainty", {}) or {}
    default_confidence = float(uncertainty.get("confidence_level", 0.95))
    primary_metric = contract.get("primary_metric", {}).get("name")

    results: list[dict[str, Any]] = []
    for gate in gates:
        treatment, control, relation = parse_comparison(gate["comparison"], condition_ids)
        confidence_level = float(gate.get("confidence_level", default_confidence))
        if gate.get("decision_rule") == "one_sided_cluster_bootstrap_ci_excludes_zero":
            results.append(
                _bootstrap_gate(
                    gate,
                    ordered,
                    treatment=treatment,
                    control=control,
                    relation=relation,
                    confidence_level=confidence_level,
                    family_key=family_key,
                    samples=samples,
                    seed=seed,
                )
            )
        elif "maximum_regression" in gate:
            results.append(
                _regression_gate(gate, ordered, treatment=treatment, control=control)
            )
        else:
            raise ValueError(
                f"gate for {gate.get('metric')!r} declares neither a supported "
                f"decision_rule nor a maximum_regression"
            )

    primary_gate = next(
        (gate for gate in results if gate["metric"] == primary_metric),
        None,
    )
    return {
        "schema_version": "playbook.analysis.v1",
        "contract_schema_version": contract.get("schema_version"),
        "contract_status": contract.get("status"),
        "primary_metric": primary_metric,
        "uncertainty": {
            "method": uncertainty.get("method"),
            "resampling_unit": uncertainty.get("resampling_unit"),
            "confidence_level": default_confidence,
            "samples": samples,
            "seed": seed,
        },
        "conditions": {
            condition: {
                "episodes": len(rows),
                "families": len({str(row[family_key]) for row in rows if family_key in row}),
            }
            for condition, rows in ordered.items()
        },
        "gates": results,
        "secondary_reporting": _secondary_reporting(
            contract,
            ordered,
            condition_ids,
            confidence_level=default_confidence,
            family_key=family_key,
            samples=samples,
            seed=seed,
        ),
        "per_family": _per_family_report(
            ordered,
            primary_metric,
            family_key=family_key,
            report_per_family=bool(uncertainty.get("report_per_family")),
            treatment=primary_gate["treatment"] if primary_gate else None,
            control=primary_gate["control"] if primary_gate else None,
        ),
        "all_gates_pass": all(gate["passed"] for gate in results) if results else False,
    }


def parse_condition(value: str) -> tuple[str, Path]:
    """Split a ``--condition ID=PATH`` argument."""
    condition, separator, path = value.partition("=")
    if not separator or not condition.strip() or not path.strip():
        raise ValueError(f"expected --condition ID=PATH, got {value!r}")
    return condition.strip(), Path(path.strip())


def load_condition_rows(path: Path) -> list[dict[str, Any]]:
    """Read episode rows from a bench scorecard, or from a bare list of rows."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("episodes") if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{path}: expected a non-empty list of episode rows")
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"{path}: episode rows must be objects")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract", type=Path, default=Path("docs/playbook-1-experiment.yaml")
    )
    parser.add_argument(
        "--condition",
        action="append",
        default=[],
        metavar="ID=PATH",
        help="condition id and its bench scorecard JSON; repeat once per condition",
    )
    parser.add_argument("--family-key", default="matter_family_id")
    parser.add_argument("--samples", type=int, default=2000, help="bootstrap resamples")
    parser.add_argument("--seed", type=int, default=0, help="bootstrap seed")
    parser.add_argument("--out", type=Path, help="write the verdict JSON here")
    parser.add_argument(
        "--require-pass",
        action="store_true",
        help="exit non-zero unless every release gate passes",
    )
    args = parser.parse_args()

    try:
        contract = load_experiment_contract(args.contract)
        rows_by_condition: dict[str, list[dict[str, Any]]] = {}
        for item in args.condition:
            condition, path = parse_condition(item)
            if condition in rows_by_condition:
                raise ValueError(f"condition {condition!r} was passed twice")
            rows_by_condition[condition] = load_condition_rows(path)
        if not rows_by_condition:
            raise ValueError("pass at least one --condition ID=PATH")
        verdict = evaluate_release_gates(
            contract,
            rows_by_condition,
            family_key=args.family_key,
            samples=args.samples,
            seed=args.seed,
        )
    except (ValueError, OSError) as exc:
        parser.error(str(exc))

    text = json.dumps(verdict, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    else:
        print(text)
    for gate in verdict["gates"]:
        status = "PASS" if gate["passed"] else "FAIL"
        print(f"{status} {gate['metric']}: {gate['detail']}")
    print(
        "Verdict: "
        + ("all release gates pass" if verdict["all_gates_pass"] else "release gates not met")
    )
    if args.out:
        print(f"Verdict written to {args.out}")
    if args.require_pass and not verdict["all_gates_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
