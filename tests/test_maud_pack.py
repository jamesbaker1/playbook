"""Structural and provenance gates for the synthetic MAUD-informed M&A pack."""

from pathlib import Path

import yaml
from conftest import MATTERS

PACK = ("public_merger_target_011", "private_acquisition_buyer_012")


def test_maud_pack_is_synthetic_and_has_real_negotiation_ladders() -> None:
    for matter_id in PACK:
        matter_dir = MATTERS / matter_id
        matter = yaml.safe_load((matter_dir / "matter.yaml").read_text(encoding="utf-8"))
        rubric = yaml.safe_load((matter_dir / "rubric.yaml").read_text(encoding="utf-8"))
        counterparty = yaml.safe_load(
            (matter_dir / "counterparty.yaml").read_text(encoding="utf-8")
        )

        assert matter["provenance"]["synthetic"] is True
        assert matter["provenance"]["confidential_source_material_used"] is False
        assert "MAUD" in matter["provenance"]["notice"]
        assert len(rubric["issues"]) == 4
        assert set(counterparty["positions"]) == {issue["id"] for issue in rubric["issues"]}
        assert all(issue.get("settlement_concepts") for issue in rubric["issues"])
        assert all(position.get("counters") for position in counterparty["positions"].values())


def test_maud_attribution_records_contamination_boundary_and_review_status() -> None:
    provenance = (Path(__file__).parents[1] / "docs" / "maud-matter-pack.md").read_text(
        encoding="utf-8"
    )
    assert "CC BY 4.0" in provenance
    assert "No agreement text" in provenance
    assert "not yet reviewed or accepted" in provenance
    assert "MAUD_train.csv" in provenance
