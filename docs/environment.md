# Environment API

## PlaybookEnv

```python
from playbook_legal import PlaybookEnv

env = PlaybookEnv.from_directory("matters/ai_saas_001")
observation, info = env.reset(seed=7)
observation, reward, terminated, truncated, info = env.step(action)
result = env.episode_result()
path = env.save_trace("artifacts/trace.json")
```

`step()` follows the Gymnasium five-tuple. The episode ends when the agent calls
`submit_final` (`terminated`) or exhausts `maximum_steps` (`truncated`). Stepping a
finished episode raises `RuntimeError`. A Gymnasium adapter is available as
`playbook_legal.gym_adapter.PlaybookGymEnv` (install the `gym` extra).

## Actions

Every action is a JSON-serializable dict with a `type` field. The same contract is
published as JSON Schemas inside every observation (`observation["action_schemas"]`)
and as OpenAI-compatible tools (`playbook_legal.tool_definitions()`).

| Action | Fields | Notes |
| --- | --- | --- |
| `read_document` | `document_id`, `section?` | Omit `section` for full text |
| `search_matter` | `query` | Case-insensitive substring search, ≥ 3 chars |
| `ask_client` | `question` | Free text; **every** question consumes budget |
| `escalate` | `topic`, `reason` | Free text; **every** escalation consumes budget |
| `submit_issue` | `issue_id`, `title`, `severity`, `citations`, `analysis`, `recommendation`, `quotes?` | Cite the operative provision **first**; `issue_id` is your own label |
| `propose_redline` | `issue_id`, `document_id`, `section`, `replacement_text`, `rationale` | Reuse your `issue_id` label to link to your issue |
| `send_markup` | `issue_id`, `document_id`, `section`, `proposed_text` | Negotiation matters only; consumes a round; counterparty answers deterministically |
| `accept_counterparty` | `issue_id` | Negotiation matters only; closes the point on their outstanding counter |
| `submit_final` | `summary` | Ends the episode |

`quotes` entries are `{"citation": "msa §4.2", "text": "..."}` and must reproduce
cited section text verbatim (whitespace-normalized, case-insensitive, ≥ 15 chars).
A quotation that is not found in the cited section is a critical failure.

### escalate

`topic` and `reason` are concatenated and matched against the rubric's `escalations`
block by concept phrase, exactly as `ask_client` is matched. A match returns the
supervisor's or client decision maker's guidance in
`last_result.guidance` and files it in `learned_facts`; a miss returns a neutral
acknowledgement that reveals nothing. Both consume budget. Omitting `topic` or
`reason` is rejected (−0.25) *before* budget is consumed.

### send_markup and accept_counterparty

These two actions **only appear on matters that ship a `counterparty.yaml` with
positions**. On every other matter they are absent from `action_schemas`, the
`protocol` block has no `negotiation` key, `budgets` has no
`negotiation_rounds_remaining`, and the observation has no `negotiation` map — so an
agent is never offered a table that does not exist.

`send_markup` is answered deterministically per issue. `last_result.response` is one
of:

| `response` | Meaning |
| --- | --- |
| `"accepted"` | The point closed on **your** text (`closed_by: "ours"`) |
| `"counter"` | Their counter is in `last_result.counter_text` and `message` |
| `"rejected"` | Counters exhausted; the issue stays open and unscored |
| `"closed"` | You marked up a point that was already closed (duplicate) |

`accept_counterparty` closes the point on their outstanding counter
(`closed_by: "theirs"`) and resolves through your own `issue_id` labels only.
Accepting with nothing outstanding costs −0.25 and no round. A markup that matches no
submitted issue and no anchor, or that targets a provision the counterparty holds no
position on, costs −0.5 **and still burns a round**.

## Budgets

| Budget | Constraint | Default |
| --- | --- | --- |
| `steps_remaining` | `constraints.maximum_steps` | 30 |
| `client_questions_remaining` | `constraints.maximum_client_questions` | 5 |
| `escalations_remaining` | `constraints.maximum_escalations` | 2 |
| `negotiation_rounds_remaining` | `constraints.maximum_negotiation_rounds` | 8 |

`negotiation_rounds_remaining` is present only when the matter has a counterparty.
Acting past a budget costs −0.5 and returns an error rather than terminating the
episode. Every well-formed `send_markup` and every successful `accept_counterparty`
consumes a negotiation round — including a markup on a point that is already closed.
An action rejected for missing fields consumes nothing.

## Observations

```jsonc
{
  "matter":   {"matter_id", "title", "practice_area", "role", "assignment"},
  "documents": [{"id", "title", "sections": ["1.1", "4.2", ...]}],
  "protocol":  {...},          // the scoring-relevant rules, in prose
  "action_schemas": {...},     // full JSON Schema per action
  "budgets":  {"steps_remaining", "client_questions_remaining",
               "escalations_remaining",
               "negotiation_rounds_remaining"},   // last key: negotiation matters only
  "learned_facts": {...},      // public facts + client answers + escalation guidance
  "submitted_issue_ids": [...],        // your own labels
  "submitted_redline_issue_ids": [...],
  "submitted_escalation_topics": [...],  // the topic strings you escalated, in order
  "negotiation": {...},        // negotiation matters only; see below
  "last_result": {...}         // outcome of your previous action
}
```

`negotiation` is a per-issue status map **keyed by your own `issue_id` label**, and an
issue appears in it only once you have marked it up:

```jsonc
"negotiation": {
  "notice": {                         // your issue_id label, not the rubric's
    "status": "open",                 // "open" | "closed"
    "rounds_used": 1,                 // rounds spent on THIS issue
    "last_message": "48 hours is our standard; the security team cannot commit to less.",
    "last_counter_text": "Provider shall notify Customer within 48 hours ..."
  },
  "cap": {
    "status": "closed",
    "rounds_used": 2,
    "last_message": "Accepted on the counterparty's language.",
    "last_counter_text": "Provider's aggregate liability shall not exceed ...",
    "closed_by": "theirs"             // present only when status == "closed"
  }
}
```

What observations never contain: hidden facts you have not asked for, escalation
guidance you have not earned, rubric contents, any counterparty configuration
(`accept_concepts`, `resist_rounds`, `reject_message`, undelivered `counters`, the
settlement rubric), or any scoring detail (matched criteria, matched concepts,
component points). Delivered counterparty *speech* is fair game; everything behind it
is hidden. Scoring detail is returned in `info["reward"]` and recorded in the trace
for harness-side auditing.

## Rewards and results

`step()` returns an incremental reward per action. `episode_result()` returns:

```jsonc
{
  "matter_id": "...",
  "raw_score": 15.0, "max_score": 16.0, "normalized_score": 0.9375,
  "critical_failure": false,
  "terminated": true, "truncated": false, "steps": 20,
  "breakdown": {
    "asked_questions": [...], "questions_asked_total": 3,
    "raised_escalations": [...], "escalations_total": 2,
    "matched_issues": [...], "matched_redlines": [...],
    "settled_issues": [...],
    "valid_citation_count": 16, "invalid_citations": [...],
    "unsupported_issues": [...], "fabricated_quotes": [...],
    "reward_events": [...]     // every scoring event with components
  }
}
```

A critical failure caps `normalized_score` at the rubric's
`critical_failure_score_cap` (0.25 by default) regardless of points earned.
See [scoring.md](scoring.md) for exactly how each component is computed.
