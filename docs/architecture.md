# Architecture

Playbook separates three layers so that everything matter-specific is data, and the
runtime never needs to change when the corpus grows.

```text
┌─ Matter package (data — one folder per matter) ───────────────┐
│  documents/*.md      what the agent can see                   │
│  hidden_facts.yaml   what the client knows (revealed only by  │
│                      asking good questions)                   │
│  rubric.yaml         expert answer key: issues anchored to    │
│                      provisions, concepts, severities, gates  │
│  matter.yaml         role, assignment, budgets, provenance,   │
│                      contamination canary                     │
└───────────────────────────────────────────────────────────────┘
                ↓ loaded by
┌─ Environment (runtime, matter-agnostic) ──────────────────────┐
│  PlaybookEnv: partially observable episode loop with budgets. │
│  Actions: read_document / search_matter / ask_client /        │
│  escalate / submit_issue / propose_redline / send_markup /    │
│  accept_counterparty / submit_final (negotiation conditional) │
│  (also published as OpenAI-compatible tool definitions).      │
└───────────────────────────────────────────────────────────────┘
                ↓ every action scored by
┌─ Reward engine (deterministic verifiers) ─────────────────────┐
│  Issues matched by cited operative provision, questions by    │
│  concept match, quotations verified verbatim. Critical        │
│  failures (fabrication, reversed allocations, prohibited      │
│  claims) cap the episode score. Full audit event log.         │
└───────────────────────────────────────────────────────────────┘
                ↓ the trace is the canonical artifact
   exporters: SFT chat data · DPO pairs · env-owned reward for GRPO
   consumers: pytest suites · playbook-bench scorecards · web player
```

## Why these boundaries

**Matters are data.** Authoring a matter requires zero code: four YAML/Markdown
files plus example trajectories. The linter (`playbook-lint`) is the contract
enforcer — anchors resolve and are unique, every rubric question has a hidden
answer, regexes compile, the canary is present. This is what makes a future
*matter compiler* possible: anything that can emit a valid matter package (an
expert, a template generator, or a pipeline over a private document corpus)
plugs into the same runtime, scoring, and training stack.

**The environment is honest.** Observations carry the full action contract and
protocol rules, so no agent needs out-of-band knowledge — but never carry hidden
facts, rubric contents, or scoring detail. Scoring detail lives in `info` and the
trace (harness-side) so the rubric cannot be probed mid-episode. The adversarial
test suite sweeps full episodes to enforce this.

**The reward is deterministic first.** Same matter, seed, and actions → identical
traces, bit for bit. LLM judges are deliberately excluded from this layer; the
planned judge (for drafting nuance) will be a second implementation of the same
rubric propositions, never a replacement for citation, quote, budget, or gate
verification.

## Trace lifecycle

`env.save_trace()` writes the complete episode: every action, the observation that
followed, per-step reward, and the final criterion-level breakdown. One trace
format feeds everything downstream:

- `playbook-render` → self-contained HTML audit report;
- `playbook-export` → chat-format SFT record (tagged with its agent source:
  scripted, `model:<name>`, or human);
- `training/build_pairs.py` → DPO preference pairs;
- `training/grpo_env_reward.py` → the environment itself as the RL reward.

## Browser gym

GitHub Pages is a static delivery layer, not a second implementation of Playbook.
`web/build_site.py` emits only HTML, CSS, and JavaScript assets. The client sends a
matter ID, seed, and action history to a dedicated Cloudflare Python Worker. The Worker
creates a fresh `PlaybookEnv`, deterministically replays the history, and returns the
current safe observation or terminal result.

Stateless replay means the service needs no session database and trusts no
browser-provided observation, score, trace, or step number. Rubrics, hidden facts,
counterparty positions, matter files, and scorer source are bundled only with the
Worker. Nonterminal responses omit harness-side reward details that could expose
rubric internals.

The interface maintains presentation-only state such as the selected document,
review cards, drafts, mobile pane, and final preflight. None of that state awards
points. The environment remains authoritative for budgets, transitions, reward,
termination, and the audit trace.

Optional trace contribution is isolated in `web/contribute.js`. The browser posts
the trace only after affirmative user action. A Cloudflare Worker applies origin,
shape, event-count, and payload-size checks before storing it in KV. Because client
input remains untrusted, `training/human_data.py` reconstructs and deterministically
replays every candidate before export.
