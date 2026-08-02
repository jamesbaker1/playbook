# Playbook v0.3 Technical Specification

## 1. Purpose

Playbook is a framework for constructing partially observable, multi-step legal work
environments for evaluation, data generation, supervised fine-tuning, preference
optimization, and reinforcement learning.

v0.1 proved that one realistic legal matter can be represented as state, observations,
actions, transitions, verifiers, rewards, and an auditable episode trace. v0.2 fixed
the scoring contract so that credit is earned by content rather than by guessing
rubric-internal identifiers, added a fabrication gate built on verbatim quote
verification, and hardened the reward against gaming ahead of any RL use.

v0.3 adds the two judgment mechanics that separate a competent reviewer from a
competent *lawyer*: knowing when a point is above your pay grade (§7, escalation) and
knowing what to trade and what to hold when someone is pushing back across the table
(§8, negotiation). Both are deterministic. The counterparty is a script, not a model.

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

v0.3 supports:

- `read_document(document_id, section?)`
- `search_matter(query)`
- `ask_client(question)` — free natural-language text; every question consumes budget
- `escalate(topic, reason)` — free natural-language text; budgeted (§7)
- `submit_issue(issue_id, title, severity, citations, analysis, recommendation, quotes?)`
- `propose_redline(issue_id, document_id, section, replacement_text, rationale)`
- `send_markup(issue_id, document_id, section, proposed_text)` — negotiation only (§8)
- `accept_counterparty(issue_id)` — negotiation only (§8)
- `submit_final(summary)`

`issue_id` is the agent's own label, used only to link a redline or a markup to the
agent's earlier issue. The two negotiation actions are **published only on matters
that ship a `counterparty.yaml` with positions**: on every other matter they are
absent from `observation["action_schemas"]`, from the `protocol` block, and from the
tool definitions, so an agent is never offered a table that does not exist. The same
contract is published as OpenAI-compatible tool definitions
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
- **Escalation matching** (§7) and **settlement scoring** (§8) follow the same
  principle: an escalation is credited by the concepts in its free text, and a
  settlement is credited by the concepts in the text the issue actually closed on.

A critical failure (fabricated quote, or a rubric-defined critical pattern in
analysis or redline text) caps the normalized episode score at
`critical_failure_score_cap`.

`max_score` is derived from the rubric by the engine; declaring it is optional and
linted against the derived value.

## 7. Escalation contract

Some points are not yours to decide. A matter may declare a rubric `escalations:`
block; the agent raises one with `escalate(topic, reason)`.

**Budget.** Escalations are capped by `constraints.maximum_escalations` (default 2)
and reported to the agent as `budgets.escalations_remaining`. Every *scored*
escalation consumes budget whether or not it matches — over-escalation is a real
professional cost, not a free lottery ticket. An `escalate` missing `topic` or
`reason` is rejected before scoring and consumes no budget; escalating past the
budget costs −0.5 and returns an error.

**Matching.** `topic` and `reason` are concatenated and matched by concept phrase,
with exactly the semantics of client questions: every concept in `concepts` must
appear, or every concept in any one `aliases` variant. First match in rubric order
wins. Matching is whitespace-normalized and case-insensitive substring containment.

**Answers.** A matched escalation returns the supervising lawyer's or client
decision maker's guidance from `hidden_facts.escalation_answers[<id>]`, which enters
`learned_facts` — escalation is a fact-acquisition channel as well as a compliance
act. An unmatched escalation returns a neutral acknowledgement that reveals nothing.

**Scoring.**

| Outcome | Points |
| --- | --- |
| Matched, first time | `points` (default 0.5) |
| Matched, already raised | −0.15 (redundant) |
| No rubric match | −0.25 (off-rubric) |

**Settle-up at final submission.** `submit_final` reconciles what was never raised:

- an escalation marked `required: true` that never happened costs
  `final_submission.missed_escalation_penalty` (default 0.5) each;
- an escalation marked `critical_if_missed: true` that never happened is a
  **critical failure**, capping the episode at `critical_failure_score_cap`.

`critical_if_missed` implies required for settle-up purposes; a critical miss is
gated rather than double-charged with the point penalty. Missing an escalation is
therefore scored the way a missed escalation actually plays out: quietly, at the end,
when the work product lands on the supervisor's desk without it.

Escalation `points` enter the derived `max_score`, so a rubric that adds escalations
raises the denominator: reference trajectories must earn them.

## 8. Negotiation contract

A matter may ship `counterparty.yaml`. Its `positions:` map is keyed by **rubric issue
id** and is hidden state: acceptance thresholds, resistance, undelivered counters, and
the settlement rubric never reach the agent. Only what the counterparty has actually
said does.

**Round logic.** `send_markup` is answered deterministically, per issue:

1. If the point is already closed → duplicate settlement (−0.2).
2. Otherwise the round counter for that issue increments, and the proposal is tested
   against `accept_concepts` — a list of variants; a variant is satisfied when every
   concept in it appears in the proposed text.
3. **Accept** if the proposal is acceptable *and* `rounds_used` now exceeds
   `resist_rounds` (default 0). The point closes on the agent's text, `closed_by:
   "ours"`. `resist_rounds` models the counterparty who says no once to correct
   language before saying yes — an agent that folds after one push never sees the
   deal it could have had.
4. Else **counter** with the next entry of `counters` (each a `{message, text}`),
   consumed in order. The counter text becomes the outstanding proposal. Countering
   scores nothing on its own.
5. Else, counters exhausted, **refuse** with `reject_message`. The issue stays open
   and unscored. Refusal is a legitimate terminal state: not every point closes, and
   holding a non-negotiable and flagging it in the final summary is correct play.

`accept_counterparty(issue_id)` closes the point on the outstanding counter text,
`closed_by: "theirs"`. It resolves through the agent's own labels only, and is
rejected (−0.25, no round consumed) when there is no outstanding counter.

**Settlement scoring — the text the issue closed on.** What is scored is neither the
opening ask nor the negotiating conduct but the language the point actually landed
on: the agent's text when the counterparty took it, the counterparty's text when the
agent accepted theirs. Points are `settlement_points` (default 1.0) times the
fraction of the issue's `settlement_concepts` present in that closing text, scored
once per issue.

**Gates.**

- `settlement_critical_failure_patterns` (regex, case-insensitive) on the closing
  text: a **critical failure**. This is how a trap counter — the counterparty's
  reasonable-sounding "30 days" where the client needs 24 hours — is caught.
- `non_negotiable: true` plus any missing `settlement_concept` in the closing text:
  a **critical failure**. Conceding a point the client told you not to concede is a
  gate, not a deduction.

**Budgets and penalties.** Rounds are capped by
`constraints.maximum_negotiation_rounds` (default 8) and reported as
`budgets.negotiation_rounds_remaining`. Every well-formed `send_markup` consumes one,
including a markup on an already-closed point; the per-issue counter that
`resist_rounds` is measured against advances only on live rounds. A markup that
matches no submitted issue label and no anchor, or that targets a provision on which
the counterparty holds no position, costs −0.5 as `unsupported_markup` **and still
burns a round**: sending the wrong paper across the table costs the same negotiating
capital as sending the right paper. A markup missing required fields is rejected
before any round is consumed.

**Authoring requirement.** Every issue carrying a counterparty position **should**
declare `settlement_concepts`. An issue without them scores full `settlement_points`
on whatever text it closes on — vacuously. That is deliberate: it keeps the derived
`max_score` reachable when an author adds a position before writing the settlement
rubric. It is a scaffold, not a feature. An author who relies on it has shipped a
negotiation the agent cannot lose, and the concession the matter exists to test goes
unscored.

`settlement_points` enter the derived `max_score` only for issues that actually carry
a counterparty position.

## 9. Scoring philosophy

Playbook does not treat all errors as interchangeable. A polished answer containing a
fabricated quotation or a reversed liability allocation is unusable despite high
average issue recall. Rubrics therefore distinguish required criteria, secondary
criteria, prohibited claims, critical failures, and procedural constraints.

Rubric criteria are written as natural-language propositions with deterministic
keyword/anchor hints. The deterministic scorer is implementation #1 of each
criterion; a calibrated LLM judge can later become implementation #2 of the same
rubric for drafting-quality dimensions verifiers cannot reach. Judges never replace
the deterministic layer for citations, quotes, budgets, or gates.

## 10. Anti-gaming requirements

Before any reward is used for training:

- keyword-stuffed submissions without valid anchor citations must score at or below
  zero (enforced by `tests/test_adversarial.py`);
- fabricated quotes and reversed-allocation redlines must trip the critical gate;
- full-episode observation sweeps must show no hidden-state or rubric leakage;
- identical seed + actions must reproduce identical traces bit-for-bit.

Any newly discovered reward-hacking pattern gets a regression test before training
resumes.

## 11. Determinism

Given the same matter, seed, and action sequence, v0.3 produces the same
observations, rewards, terminal state, and trace — the scripted counterparty included.
LLM-based simulators and graders are excluded from the deterministic scoring layer.

## 12. Evaluation protocol

Every experiment reports (implemented in `playbook_legal.metrics`):

- normalized and raw reward;
- issue recall and required-issue recall;
- unsupported-issue count;
- citation validity;
- question recall and questions asked;
- escalation recall (against required and `critical_if_missed` escalations) and
  over-escalation count;
- redline completion and settled-issue ratio (against issues carrying a counterparty
  position);
- fabricated-quote count;
- critical-error-free completion rate;
- steps (and tokens, where available);
- and performance on the private held-out matter set.

## 13. Security, ethics, and provenance

Matter authors must not use confidential client materials, employer playbooks,
privileged work product, or recognizable reconstructed matters. Every matter includes
a provenance declaration (`synthetic: true`) and the project contamination canary
string, enforced by the linter. Synthetic documents must avoid reproducing
proprietary forms or distinctive confidential language. Matter content is fictional
and is not legal advice.
