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
| `submit_issue` | `issue_id`, `title`, `severity`, `citations`, `analysis`, `recommendation`, `quotes?` | Cite the operative provision **first**; `issue_id` is your own label |
| `propose_redline` | `issue_id`, `document_id`, `section`, `replacement_text`, `rationale` | Reuse your `issue_id` label to link to your issue |
| `submit_final` | `summary` | Ends the episode |

`quotes` entries are `{"citation": "msa §4.2", "text": "..."}` and must reproduce
cited section text verbatim (whitespace-normalized, case-insensitive, ≥ 15 chars).
A quotation that is not found in the cited section is a critical failure.

## Observations

```jsonc
{
  "matter":   {"matter_id", "title", "practice_area", "role", "assignment"},
  "documents": [{"id", "title", "sections": ["1.1", "4.2", ...]}],
  "protocol":  {...},          // the scoring-relevant rules, in prose
  "action_schemas": {...},     // full JSON Schema per action
  "budgets":  {"steps_remaining", "client_questions_remaining"},
  "learned_facts": {...},      // public facts + client answers earned so far
  "submitted_issue_ids": [...],        // your own labels
  "submitted_redline_issue_ids": [...],
  "last_result": {...}         // outcome of your previous action
}
```

What observations never contain: hidden facts you have not asked for, rubric
contents, or any scoring detail (matched criteria, matched concepts, component
points). Scoring detail is returned in `info["reward"]` and recorded in the trace
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
    "matched_issues": [...], "matched_redlines": [...],
    "valid_citation_count": 16, "invalid_citations": [...],
    "unsupported_issues": [...], "fabricated_quotes": [...],
    "reward_events": [...]     // every scoring event with components
  }
}
```

A critical failure caps `normalized_score` at the rubric's
`critical_failure_score_cap` (0.25 by default) regardless of points earned.
See [scoring.md](scoring.md) for exactly how each component is computed.
