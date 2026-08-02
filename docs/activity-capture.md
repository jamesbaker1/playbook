# Attorney activity capture — design note

*Status: design exploration. Nothing here is built, and the first section explains
why the naive version never should be.*

## The idea and the goal

"Record every screen at the firm and use it as training data." The goal underneath
is right and important: the scarcest training asset in legal AI is **expert
demonstrations at scale** — how a good lawyer actually moves through a matter, not
just the final artifacts. This note takes the goal seriously and specs the version
of it a firm could actually run.

## Why blanket screen recording is not buildable

Legal, in rough order of severity:

1. **Client confidentiality (Model Rule 1.6).** A screen shows every client's
   material simultaneously. Client A can consent to their matter being captured;
   they cannot consent for clients B–Z whose documents, names, and strategies
   cross the same screen. Blanket capture makes *informed, per-client* consent
   structurally impossible — one client's refusal poisons every recording that
   might show their material.
2. **Protective orders and inbound confidentiality.** Discovery material under a
   protective order, opposing counsel's drafts, third-party diligence rooms —
   recording them into a training corpus is a violation with a paper trail.
3. **Monitoring and wiretap law.** Jurisdiction-dependent employee-notice and
   consent requirements (e.g. New York's electronic-monitoring notice law,
   two-party-consent states, GDPR's proportionality bar for EU offices, biometric
   statutes if capture touches cameras). Blanket capture fails the
   least-intrusive-means test that regulators and works councils apply.
4. **The archive itself is a liability.** A store of everyone's screens is
   discoverable, subpoenable, and a catastrophic breach target: one compromise
   equals every client's everything. It can also waive privilege protections the
   firm is obligated to maintain.
5. **MNPI.** Deal teams' screens carry material nonpublic information; a
   recording pipeline that touches it creates insider-risk and information-wall
   problems the firm's compliance function cannot accept.

Technical, independently fatal to the naive version: pixels are the
lowest-fidelity, highest-volume representation of legal work. The signal
("changed the cap from 1x to 2x, citing the playbook") is already available as
structured data — tracked changes, DMS audit logs, email — at a thousandth of the
storage and none of the OCR/segmentation error. The one genuine use of raw screen
data is training *computer-use* agents (pixels-to-actions models), which is why a
narrow, sandboxed tier for it appears at the end — deferred, not default.

## The defensible spec: matter-scoped semantic capture

Capture **actions, not pixels**, and only where three consents align.

### Consent model (all three, or no capture)

- **Client**: per-matter consent, in the engagement letter or a specific waiver,
  naming training/evaluation use and the internal-only boundary.
- **Attorney**: per-session opt-in with a visible recording indicator and a
  one-keystroke pause. Never a condition of employment for existing matters.
- **Firm**: written policy satisfying monitoring-notice law in every office the
  capture runs in; works-council sign-off where applicable.

Capture is scoped by an **allowlist of consented matter IDs**. An event that
cannot be attributed to an allowlisted matter is dropped at the edge, unlogged.

### Capture layer (application instrumentation, not screen)

| Source | Mechanism | Yields |
| --- | --- | --- |
| Word | add-in logging tracked-change deltas, comment threads, section focus | redline sequences with author/time — the core demonstration data |
| DMS (iManage/NetDocuments) | native audit APIs | which documents were opened, in what order, for how long |
| Outlook | add-in on consented matters only | instruction/negotiation correspondence (see matter-compiler §correspondence) |
| Research tools | history export where licensable | authority actually consulted |

Events land in the **Playbook trace schema** — the same
`{action, observation delta, timestamp}` shape the gym already emits — so
captured human work exports through the existing pipeline (SFT tagging,
replay-verification where the matter has a rubric, DPO pairing). The gym's trace
format is the target; a screen recorder is just the worst possible sensor for it.

### Storage and governance

Identical to the matter-compiler deployment model (docs/matter-compiler.md):
inside the firm's tenancy, egress-denied, per-firm canary, privilege filter at
intake, deletion rights per matter, and an audit ledger of every read. Retention
capped and short; derived training data outlives raw events, raw events do not
outlive the retention window.

### Tier 2 (deferred): the sandboxed recording workspace

If computer-use training data is ever genuinely wanted: a dedicated VM per
consented matter — the attorney works *that matter only* inside it, nothing else
can appear on that virtual screen, recording is on by design and visibly so.
This solves cross-client contamination structurally rather than by policy. It is
the only shape in which screen pixels should ever be captured in a law firm, and
it should still be piloted with volunteer attorneys on synthetic or
consented-to-the-hilt matters first.

## Phasing

- **P0 (no new capture):** mine what already exists with consent — tracked
  changes and DMS audit logs. This is the matter compiler's Stage 3–4 and needs
  no new instrumentation.
- **P1:** Word/Outlook add-ins emitting semantic events on allowlisted matters;
  export through the trace pipeline.
- **P2 (only if computer-use training becomes a goal):** sandboxed recording
  workspace pilot.

## Bottom line

Do not build "record everyone's screens." Build "consented matters emit traces."
It captures the demonstrations that matter, in the format the training stack
already consumes, without making the firm's clients involuntary training data.
