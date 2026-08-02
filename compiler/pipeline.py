"""Matter-compiler pipeline: staged, checkpointed, human-reviewable.

Every stage takes a checkpoint from the previous stage and writes its own, so a
lawyer can inspect, correct, or reject the intermediate product before anything
downstream runs. Nothing here calls a model or a network by itself; connectors and
model calls are injected, which is what keeps the whole thing runnable inside a
firm's own boundary with egress disabled (``docs/matter-compiler.md`` §5).

Status: **typed stubs**. The two mined-evidence extractors are real
(:mod:`compiler.redline_miner`, :mod:`compiler.correspondence`); the stages below
raise :class:`NotImplementedError` with a pointer to the design section that has to
be settled — usually with a design-partner firm — before code is worth writing.

Stage order::

    0 intake      hash + manifest every artifact (chain of custody)
    1 cluster     artifacts -> matters                        cluster_artifacts()
    2 order       matter -> ordered version chain             order_versions()
    3 redlines    version chain -> candidate issues           mine_redlines()
    4 mail        threads -> instructions/playbook/hidden     mine_correspondence()
    5 rubric      evidence -> draft rubric (lawyer reviews)   derive_rubric()
    6 anonymize   draft -> de-identified, resynthesized       anonymize()
    7 emit        draft -> matter.yaml/rubric.yaml/...        emit_matter()
    8 validate    playbook-lint + replay the reference run    validate_package()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

DESIGN_DOC = "docs/matter-compiler.md"

STAGES: tuple[str, ...] = (
    "intake",
    "cluster",
    "order",
    "redlines",
    "correspondence",
    "rubric",
    "anonymize",
    "emit",
    "validate",
)


# ------------------------------------------------------------------ data carriers


@dataclass(frozen=True)
class SourceArtifact:
    """One ingested object plus the provenance needed to defend it later.

    ``origin`` is the system of record (``imanage``, ``netdocuments``, ``graph``,
    ``pst``, ``filesystem``); ``external_id`` is that system's stable identifier
    (iManage ``LIB!docnum.version``, NetDocuments ``ndmid``, Graph immutable message
    id). ``sha256`` is computed at intake and never recomputed downstream.
    """

    artifact_id: str
    origin: str
    external_id: str
    kind: str  # docx | pdf | email | comparison | metadata
    sha256: str
    captured_at: str
    metadata: dict[str, Any] = field(default_factory=dict)
    local_path: Path | None = None


@dataclass(frozen=True)
class MatterCluster:
    """Artifacts believed to belong to one matter, with the evidence for that."""

    cluster_id: str
    artifacts: tuple[SourceArtifact, ...] = ()
    client_matter_number: str = ""
    practice_area: str = ""
    confidence: float = 0.0
    rationale: str = ""


@dataclass(frozen=True)
class VersionChain:
    """One document's versions in negotiation order, plus detected gaps."""

    document_label: str
    ordered: tuple[SourceArtifact, ...] = ()
    gaps: tuple[str, ...] = ()
    executed: SourceArtifact | None = None


@dataclass(frozen=True)
class CandidateIssue:
    """A proposed rubric issue with a pointer back to the evidence that produced it."""

    candidate_id: str
    anchor_hint: str  # e.g. "msa §4.2"
    title: str
    severity: str
    required_concepts: tuple[str, ...] = ()
    redline_concepts: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    reviewer_state: str = "proposed"  # proposed | accepted | edited | rejected


@dataclass(frozen=True)
class EvidenceBundle:
    """Everything Stage 5 is allowed to reason over for one matter."""

    cluster: MatterCluster
    chains: tuple[VersionChain, ...] = ()
    candidate_issues: tuple[CandidateIssue, ...] = ()
    instructions: tuple[str, ...] = ()
    playbook_positions: tuple[str, ...] = ()
    client_answers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MatterDraft:
    """The in-memory shape of a matter package, before anonymization and emit."""

    matter: dict[str, Any] = field(default_factory=dict)
    rubric: dict[str, Any] = field(default_factory=dict)
    hidden_facts: dict[str, Any] = field(default_factory=dict)
    documents: dict[str, str] = field(default_factory=dict)  # filename -> markdown
    reference_actions: tuple[dict[str, Any], ...] = ()


# ------------------------------------------------------------------------- stages


def cluster_artifacts(
    artifacts: Sequence[SourceArtifact],
    *,
    trust_dms_workspace: bool = True,
) -> list[MatterCluster]:
    """Stage 1 — group raw artifacts into matters.

    The DMS workspace is the ground truth when it exists (a human already filed the
    work), so ``trust_dms_workspace`` short-circuits the expensive path. Everything
    else — loose mailbox threads, drafts saved to personal folders — needs the
    participant graph, the client/matter number in the subject line, and content
    similarity, in that order of reliability.
    """
    raise _todo("§3.1 Stage 1 — artifact clustering", "cluster_artifacts")


def order_versions(cluster: MatterCluster) -> list[VersionChain]:
    """Stage 2 — reconstruct each document's version chain in negotiation order.

    DMS version numbers are necessary but not sufficient: real turns arrive as email
    attachments and get re-filed as new documents. Ordering must reconcile version
    metadata, send times, and content similarity, and must *report* gaps rather than
    interpolate over them (§3.2, and §6 "version-chain gaps").
    """
    raise _todo("§3.2 Stage 2 — version-chain ordering", "order_versions")


def mine_redlines(chain: VersionChain) -> list[CandidateIssue]:
    """Stage 3 — turn each substantive partner edit into a candidate rubric issue.

    Uses :func:`compiler.redline_miner.extract_edits` where tracked changes survived,
    and a version-to-version diff (:func:`compiler.redline_miner.paragraph_views`)
    where they did not. The open work is *classification*: separating substantive
    edits from conforming, numbering, and typographic ones, and choosing the anchor
    provision (§3.3).
    """
    raise _todo("§3.3 Stage 3 — redline mining", "mine_redlines")


def mine_correspondence(cluster: MatterCluster) -> EvidenceBundle:
    """Stage 4 — mine the mail for instructions, positions, facts, and leverage.

    Supervising-lawyer mail becomes ``instructions.md`` and playbook positions;
    client answers become ``hidden_facts.client_answers`` plus the rubric questions
    that unlock them; counterparty mail carries severity and leverage signal
    (what was conceded, what was refused, what was escalated) (§3.4).
    """
    raise _todo("§3.4 Stage 4 — correspondence mining", "mine_correspondence")


def derive_rubric(bundle: EvidenceBundle, *, propose) -> MatterDraft:
    """Stage 5 — model-assisted rubric proposal, always lawyer-reviewed.

    ``propose`` is an injected callable ``(prompt, evidence) -> draft``: in a firm
    deployment it is a model running inside the tenant. Its output is a *proposal*
    with an evidence citation on every element; a lawyer accepts, edits, or rejects
    each one, and the acceptance ledger is part of the package's provenance (§3.5).
    """
    raise _todo("§3.5 Stage 5 — rubric derivation", "derive_rubric")


def anonymize(draft: MatterDraft, *, k_threshold: int = 5) -> MatterDraft:
    """Stage 6 — de-identify and resynthesize until the deal is unrecognizable.

    Consistent entity aliasing, order-preserving numeric jitter, and rewriting of
    distinctive drafting. ``k_threshold`` is the k-anonymity floor over
    (practice area, deal shape, issue set): a package that is unique on those axes
    identifies its source and must not be emitted. Rubric concepts and reference
    quotes are rewritten too — they are text from the source document (§3.6).
    """
    raise _todo("§3.6 Stage 6 — anonymization and synthesis", "anonymize")


def emit_matter(draft: MatterDraft, out_dir: Path) -> Path:
    """Stage 7 — write the package in the exact format the loaders parse.

    ``matter.yaml`` / ``rubric.yaml`` / ``hidden_facts.yaml`` / ``documents/*.md``,
    with headings renumbered to ``## X.Y`` tokens, citations as
    ``<document_id> §<section>``, the project canary, and a compiled-provenance
    block. Quotes in the reference trajectory are regenerated from the *emitted*
    text, never the source, or the fabrication gate trips (§3.7).
    """
    raise _todo("§3.7 Stage 7 — emit", "emit_matter")


def validate_package(matter_dir: Path, reference_actions: Sequence[dict[str, Any]]) -> dict:
    """Stage 8 — lint, then replay the partner's own work as ``good.jsonl``.

    ``playbook-lint`` must pass with zero errors and the derived reference
    trajectory must replay to ≥ 0.7 normalized with no critical failure. A reference
    run that scores low means the rubric is wrong, not the partner — that is the
    calibration loop, and it is the only automatic check on Stage 5 (§3.8).
    """
    raise _todo("§3.8 Stage 8 — validation and replay", "validate_package")


def compile_matter(artifacts: Sequence[SourceArtifact], out_dir: Path) -> Path:
    """Run every stage end to end. Deliberately unimplemented: see ``STAGES``.

    The orchestrator is the last thing to build, not the first — each stage has to
    survive lawyer review on real matters before chaining them is honest.
    """
    raise _todo("§3 Reconstruction pipeline", "compile_matter")


def _todo(section: str, symbol: str) -> NotImplementedError:
    return NotImplementedError(
        f"{symbol}() is a designed stub — see {DESIGN_DOC} {section}"
    )
