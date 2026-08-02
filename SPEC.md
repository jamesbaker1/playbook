# Playbook v0.2 Technical Specification

## 1. Purpose

Playbook is a framework for constructing partially observable, multi-step legal work
environments for evaluation, data generation, supervised fine-tuning, preference
optimization, and reinforcement learning.

v0.1 proved that one realistic legal matter can be represented as state, observations,
actions, transitions, verifiers, rewards, and an auditable episode trace. v0.2 fixes
the scoring contract so that credit is earned by content rather than by guessing
rubric-internal identifiers, adds a fabrication gate built on verbatim quote
verification, and hardens the reward against gaming ahead of any RL use.

## 2. Research question

Can post-training in a structured legal environment improve an open model's performance
on unseen legal matters while reducing critical errors such as fabricated citations,
unsupported assumptions, and unauthorized departures from a client playbook?

## 3. Episode model

An episode consists of:

1. `reset(seed)` initializes public state, hidden state, budgets, and the trace.
2. The agent receives a public observation.
3. The agent submits one structured action.
4. The environment validates and executes the action.
5. The environment returns a new observation and incremental reward.
6. The episode ends on `submit_final` or truncates at the step limit.
7. The environment returns a normalized score, raw score, critical-failure status,
   and criterion-level breakdown.

## 4. Observation contract

Observations are JSON-serializable dictionaries containing:

- matter metadata; role and assignment;
- the visible document index;
- the full action contract (`action_schemas`) and the scoring `protocol` rules, so
  the contract is discoverable by any agent without out-of-band knowledge;
- current budgets;
- facts learned through permitted actions;
- submissions already made (by the agent's own labels);
- and the result of the immediately preceding action.

Hidden facts, rubric contents, counterparty fallback positions, and undisclosed
document content must never appear in observations. **Scoring detail (matched
criteria, matched concepts, per-component points) is harness-side only**: it appears
in `info` and the trace for auditing, never in the agent-visible observation, so the
rubric cannot be probed mid-episode.

## 5. Action contract

v0.2 supports:

- `read_document(document_id, section?)`
- `search_matter(query)`
- `ask_client(question)` — free natural-language text; every question consumes budget
- `submit_issue(issue_id, title, severity, citations, analysis, recommendation, quotes?)`
- `propose_redline(issue_id, document_id, section, replacement_text, rationale)`
- `submit_final(summary)`

`issue_id` is the agent's own label, used only to link a redline to the agent's
earlier issue. The same contract is published as OpenAI-compatible tool definitions
(`playbook_legal.schemas.tool_definitions`), so function-calling models play the
environment natively.

## 6. Scoring contract

Rubric credit is earned by content:

- **Issue matching.** Each rubric issue declares a unique `anchor` citation — the
  operative provision. A submitted issue is credited to the criterion whose anchor
  appears among its (valid) citations; the protocol instructs agents to cite the
  operative provision first, and the first anchor found decides. No anchor match →
  unsupported-issue penalty.
- **Question matching.** Rubric questions declare `concepts` (all must appear in the
  agent's free-text question) and `aliases` (alternative concept lists). Matched
  questions reveal the corresponding hidden fact and score once; redundant and
  off-rubric questions are penalized and still consume budget.
- **Quote verification.** Optional `quotes` entries are checked verbatim
  (whitespace-normalized, case-insensitive) against the cited section. A verified
  quote earns points once per issue; a quotation that does not appear in the cited
  section is **fabrication: a critical failure plus a penalty**. Quotes below a
  minimum length are ignored.
- **Redline matching.** A redline is credited via the agent's issue label, or by
  targeting the criterion's anchor section directly.
- Severity, required-citation, concept, and redline-concept components score as
  additive points per criterion; invalid citations are penalized wherever they
  appear.

A critical failure (fabricated quote, or a rubric-defined critical pattern in
analysis or redline text) caps the normalized episode score at
`critical_failure_score_cap`.

`max_score` is derived from the rubric by the engine; declaring it is optional and
linted against the derived value.

## 7. Scoring philosophy

Playbook does not treat all errors as interchangeable. A polished answer containing a
fabricated quotation or a reversed liability allocation is unusable despite high
average issue recall. Rubrics therefore distinguish required criteria, secondary
criteria, prohibited claims, critical failures, and procedural constraints.

Rubric criteria are written as natural-language propositions with deterministic
keyword/anchor hints. The deterministic scorer is implementation #1 of each
criterion; a calibrated LLM judge can later become implementation #2 of the same
rubric for drafting-quality dimensions verifiers cannot reach. Judges never replace
the deterministic layer for citations, quotes, budgets, or gates.

## 8. Anti-gaming requirements

Before any reward is used for training:

- keyword-stuffed submissions without valid anchor citations must score at or below
  zero (enforced by `tests/test_adversarial.py`);
- fabricated quotes and reversed-allocation redlines must trip the critical gate;
- full-episode observation sweeps must show no hidden-state or rubric leakage;
- identical seed + actions must reproduce identical traces bit-for-bit.

Any newly discovered reward-hacking pattern gets a regression test before training
resumes.

## 9. Determinism

Given the same matter, seed, and action sequence, v0.2 produces the same
observations, rewards, terminal state, and trace. LLM-based simulators and graders
are excluded from the deterministic scoring layer.

## 10. Evaluation protocol

Every experiment reports (implemented in `playbook_legal.metrics`):

- normalized and raw reward;
- issue recall and required-issue recall;
- unsupported-issue count;
- citation validity;
- question recall and questions asked;
- redline completion;
- fabricated-quote count;
- critical-error-free completion rate;
- steps (and tokens, where available);
- and performance on the private held-out matter set.

## 11. Security, ethics, and provenance

Matter authors must not use confidential client materials, employer playbooks,
privileged work product, or recognizable reconstructed matters. Every matter includes
a provenance declaration (`synthetic: true`) and the project contamination canary
string, enforced by the linter. Synthetic documents must avoid reproducing
proprietary forms or distinctive confidential language. Matter content is fictional
and is not legal advice.
