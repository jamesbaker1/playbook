# Authoring a Playbook Matter

## Minimum files

```text
matters/<matter_id>/matter.yaml
matters/<matter_id>/rubric.yaml
matters/<matter_id>/hidden_facts.yaml
matters/<matter_id>/counterparty.yaml  # optional: enables the negotiation actions
matters/<matter_id>/documents/*.md
examples/<matter_id>/good.jsonl        # required: validated reference trajectory
examples/<matter_id>/bad_*.jsonl       # at least one adversarial trajectory
```

CI enforces all of it: `playbook-lint` must pass with zero errors, `good.jsonl` must
replay to ≥ 0.7 normalized with no critical failure, and every `bad_*.jsonl` must
score below `good.jsonl` (files named `bad_critical_*` or containing `fabricated`
must trip the critical gate).

## Mechanical contract

- Documents are Markdown; every scoreable provision sits under a `## X.Y Title`
  heading. The section token is the first token after `## `. Never reuse a token
  within one document.
- Citations are `<doc_id> §<section>` (e.g. `msa §4.2`).
- Every rubric issue declares a unique `anchor` citation — the operative provision
  that decides issue matching. The anchor must resolve and must appear in
  `required_citations`.
- Rubric questions declare `concepts` (lowercase phrases that must all appear in the
  agent's free-text question) plus `aliases` (alternative phrasings). Every question
  id needs an answer in `hidden_facts.yaml`; hidden answers must not be derivable
  from the documents.
- Rubric escalations follow the same matching rules against `topic` + `reason`.
- `counterparty.yaml` positions are keyed by **rubric issue id**, and every negotiated
  issue should declare `settlement_concepts`.
- Do not declare `max_score`; the engine derives it — including escalation points and
  the `settlement_points` of every issue that carries a counterparty position. Adding
  either to an existing rubric raises the denominator, so re-replay `good.jsonl`.
- `matter.yaml` must carry `provenance.synthetic: true` and the project canary line
  (see `playbook_legal.lint.CANARY`).

## Authoring order

1. Define the professional role and terminal work product.
2. Write the hidden factual truth before writing the documents.
3. Identify 3–7 material issues and their interactions; pick each issue's anchor.
4. Write an atomic rubric for each issue.
5. Add required factual questions that unlock hidden facts and change the analysis.
6. Decide which points are above the agent's pay grade and write them as escalations.
7. Draft synthetic documents that instantiate the issues.
8. Add prohibited claims (critical_failure_patterns) and redline reversal patterns.
9. If the matter is a live negotiation, write `counterparty.yaml` and the settlement
   rubric together — never one without the other.
10. Write the reference trajectory and at least one adversarial bad trajectory.
11. Validate: `playbook-lint matters/<id>` then `playbook-eval matters/<id>
    examples/<id>/good.jsonl`.
12. Hold out paraphrased and structurally varied versions for the private set.

## Good rubric criteria

A criterion should be observable and narrow:

- Good: `Cites msa §4.2 and explains that the provider's model-training right is
  broader than the playbook permits.`
- Weak: `Provides sophisticated analysis.`

Write each criterion as a natural-language proposition, then encode it with the
anchor, `required_concepts`, and `redline_concepts`. Choose content-bearing phrases a
correct analysis must contain — never generic words a stuffed answer could hit
(the anti-gaming tests will catch you). Reserve human or model grading for
commercial judgment and drafting nuance that cannot be reliably encoded.

## Escalations

An escalation is a point the agent is not authorized to decide. Author one when the
matter's own instructions say so — a playbook row marked ESCALATE, a standing board
instruction, a limit of authority in the engagement letter. If nothing in the record
tells the agent the point is above its pay grade, do not score it as an escalation;
score it as an issue.

```yaml
escalations:
  - id: esc_exclusivity
    points: 0.75
    required: true            # never raised → -missed_escalation_penalty at final
    critical_if_missed: false # never raised → critical failure (use sparingly)
    concepts: ["exclusivity"]
    aliases: [["non-compete"], ["exclusive", "retail"]]
```

```yaml
# hidden_facts.yaml
escalation_answers:
  esc_exclusivity: >-
    GC, relaying the CEO: do not counter the exclusivity in writing ...
```

- `concepts` and `aliases` are matched against `topic` + `reason` concatenated, with
  the same all-of-any-variant rule as questions. Write the aliases a competent lawyer
  would actually type — the point is to reward the judgment, not the vocabulary.
- Every escalation id needs an entry in `escalation_answers`. Write it **in world**:
  it is a note from a supervising partner, GC, or client decision maker, not a rubric
  hint. It should tell the agent something it could not have read in the documents,
  and it should change what the agent does next.
- Reserve `critical_if_missed` for the escalation whose omission makes the whole work
  product unusable. If an issue-level critical gate already covers the same failure,
  use `required: true` and let the point penalty do the work — do not gate twice for
  one mistake.
- Set `constraints.maximum_escalations` (default 2) so that raising every scored
  escalation is possible but escalating everything is not. A budget that comfortably
  covers every provision teaches nothing.

## counterparty.yaml

`counterparty.yaml` turns a review matter into a negotiation. Its presence is what
publishes `send_markup` and `accept_counterparty` to the agent.

```yaml
positions:
  incident_notice:                       # keyed by RUBRIC ISSUE ID
    resist_rounds: 1                     # say no once before saying yes
    accept_concepts: [["24 hours", "discover"]]
    counters:
      - message: "48 hours is our standard; the security team cannot commit to less."
        text: "Provider shall notify Customer within 48 hours of confirming an incident."
      - message: "Then we will hold at our outside window."
        text: "Provider shall notify Customer within 30 days of confirming an incident."
    reject_message: "We have nothing further to give on incident notice."
```

**Every issue in `positions` should declare `settlement_concepts` in the rubric.** An
issue without them scores full `settlement_points` on whatever text it closes on —
vacuously, every time, however bad the language. That is by design, so the derived
`max_score` stays reachable while a matter is half-authored; it is scaffolding, and
authors must not rely on it. Shipping a position without settlement concepts means
shipping a negotiation the agent cannot lose, and the concession the matter exists to
test goes unscored. The linter warns when a negotiated issue has no
`settlement_points > 0`; it cannot warn you about the vacuous case, so this one is on
you.

**Design counters as realistic traps.** A counter that is obviously bad teaches
nothing — the agent refuses it for free. The counter that earns its place is the one
a tired associate would accept at 7pm: it concedes the shape of the request, sounds
like a compromise, and quietly moves the number past the client's line. Order them so
the *first* counter is a genuine partial concession and the trap comes second, after
the agent has been rewarded once for pushing.

- `resist_rounds` models the counterparty who refuses correct language once before
  taking it. Use it on the issue where folding early is the failure you want to test.
- Give every position a `reject_message`. Refusal is a legitimate ending: an
  unsettled non-negotiable scores nothing and costs nothing, and standing firm while
  flagging it in the final summary is correct play.
- Mark the client's true red line `non_negotiable: true` and put the trap language in
  `settlement_critical_failure_patterns`.

**Verify your regexes fire and do not misfire.** `settlement_critical_failure_patterns`
run case-insensitively against the whitespace-normalized closing text. Before
shipping, replay a trajectory that accepts the trap (the gate must trip) *and* a
trajectory that closes correctly (the gate must stay silent). A pattern like `30 days`
is a substring, not a word boundary — confirm it cannot fire on your own good
language. Ship both trajectories as `bad_critical_*.jsonl` and `good.jsonl`.

## Clean matters

Not every matter should have issues. A matter whose correct answer is "the paper is
fine" tests something no issue-bearing matter can: whether a model manufactures
problems to look diligent. False-positive discipline is a real professional skill and
models are bad at it.

- `issues: []` is valid. So is a rubric with questions and escalations and no issues
  at all.
- Grade the work product through `final_submission.required_concepts` +
  `concept_points`. Where there is nothing to find, the summary *is* the deliverable:
  require it to name what was checked and to state the conclusion plainly.
- Keep `required_issue_ids` empty and let the unsupported-issue penalty (−0.5 each,
  −0.75 per invalid citation) do the disciplining. An agent that invents three issues
  to fill the page should finish below an agent that reads the file and says so.
- **Decoys should look alarming and be compliant.** A clause that reads harshly on
  first pass but is cured by a definition, a cross-reference, or a proviso two
  sections down. The agent that only pattern-matches on scary words will flag it; the
  agent that reads the whole instrument will not.
- The reference trajectory should still *work*: read the documents, ask the questions
  that could have changed the answer, and conclude. "No material issues" reached
  without doing the reading is the same failure as inventing issues.

## Critical failures

Examples:

- inventing a contractual provision or quotation (the quote verifier gates this
  automatically — encourage quotes in your reference trajectory);
- claiming a supplied fact the agent never learned;
- reversing the intended party allocation in a redline
  (`redline_critical_failure_patterns`);
- waiving a required protection without escalation, or never raising a
  `critical_if_missed` escalation at all;
- closing a `non_negotiable` issue without its `settlement_concepts`, or on text
  matching a `settlement_critical_failure_pattern` — the trap counter;
- asserting categorical law without authority when the assignment is contractual
  review (`critical_failure_patterns`);
- exposing hidden or protected information.

## Variation strategy

Do not create ten matters by changing party names. Vary document architecture,
defined-term vocabulary, issue location, client leverage, factual ambiguity,
governing instructions, interaction among provisions, acceptable fallbacks, and
required output format. Held-out matters should also diverge in structure and
vocabulary so surface pattern-matching from public matters fails.
