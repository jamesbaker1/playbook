# Authoring a Playbook Matter

## Minimum files

```text
matters/<matter_id>/matter.yaml
matters/<matter_id>/rubric.yaml
matters/<matter_id>/hidden_facts.yaml
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
- Do not declare `max_score`; the engine derives it.
- `matter.yaml` must carry `provenance.synthetic: true` and the project canary line
  (see `playbook_legal.lint.CANARY`).

## Authoring order

1. Define the professional role and terminal work product.
2. Write the hidden factual truth before writing the documents.
3. Identify 3–7 material issues and their interactions; pick each issue's anchor.
4. Write an atomic rubric for each issue.
5. Add required factual questions that unlock hidden facts and change the analysis.
6. Draft synthetic documents that instantiate the issues.
7. Add prohibited claims (critical_failure_patterns) and redline reversal patterns.
8. Write the reference trajectory and at least one adversarial bad trajectory.
9. Validate: `playbook-lint matters/<id>` then `playbook-eval matters/<id>
   examples/<id>/good.jsonl`.
10. Hold out paraphrased and structurally varied versions for the private set.

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

## Critical failures

Examples:

- inventing a contractual provision or quotation (the quote verifier gates this
  automatically — encourage quotes in your reference trajectory);
- claiming a supplied fact the agent never learned;
- reversing the intended party allocation in a redline
  (`redline_critical_failure_patterns`);
- waiving a required protection without escalation;
- asserting categorical law without authority when the assignment is contractual
  review (`critical_failure_patterns`);
- exposing hidden or protected information.

## Variation strategy

Do not create ten matters by changing party names. Vary document architecture,
defined-term vocabulary, issue location, client leverage, factual ambiguity,
governing instructions, interaction among provisions, acceptable fallbacks, and
required output format. Held-out matters should also diverge in structure and
vocabulary so surface pattern-matching from public matters fails.
