# Work queue — implementation specs

*Companion to `plan-2026-08.md`. Each item is written as an implementation spec:
the files involved, required behavior, and acceptance check. As of 2026-08-02,
the repository implementation for W1–W20 is complete. W10 and W12 still require
approved paid model runs and human traces before results can be reported; W11 still
requires review by a practicing M&A lawyer; deployed social-card unfurls require a
post-deployment check. The detailed requirements remain below as the release audit.*

**Addendum, 2026-08-19.** The header above is a 2026-08-02 snapshot; its specifics
have moved. Re-verified in code today: **W14** — export pairs each action with the
preceding observation, enforced by
`tests/test_bench_export.py::test_export_pairs_actions_with_preceding_observations`
(with `test_export_rejects_legacy_trace_without_initial_observation`); **W15** —
the anchored-stuffing exploit is closed, enforced by
`tests/test_adversarial.py::test_anchored_rubric_stuffing_without_reads_scores_far_below_reference`;
**W16** — seeds are real, forwarded to every model request per
`tests/test_baseline.py::test_seed_is_forwarded_to_every_model_request` (with
`tests/test_bench_export.py::test_bench_rejects_duplicate_deterministic_replay_seeds`);
**W18** — SPDX headers now cover 65/65 Python files across `src/`, `training/`,
`compiler/`, and `engine-worker/src/`; **W20** — the vendored engine copy is
verified in CI by the `python engine-worker/vendor.py --check` step in
`.github/workflows/ci.yml`, which also lints `compiler/`. **W17** is now closed:
`CITATION.cff` in this tree carries `version: 0.4.0` and
`date-released: "2026-08-06"`.
**W19**'s "2 matters" count is superseded by the sealed-corpus status recorded in
`docs/report.md` §4 and `docs/playbook-1-plan.md` — six owner-reviewed families
as of 2026-08-08, five more drafted and blocked at adversarial pre-review,
against a frozen contract target of 15-30 families (interim floor: ten reviewed).

## W1. Link previews and favicon (plan A1)

**Files:** `web/index.html`, `web/build_site.py`, new `web/favicon.svg`, new
`web/og-card.png`.

- Add to `<head>`: `og:title` ("playbook — the legal agent gym"), `og:description`
  (reuse the meta description), `og:image` (absolute URL to `og-card.png`),
  `og:url`, `og:type=website`, `twitter:card=summary_large_image`, plus
  `<link rel="icon" href="favicon.svg">`.
- `og-card.png`: 1200×630, the design system's paper background, serif headline
  "Can you review a deal like a careful lawyer?", oxblood accent rule, wordmark.
  No screenshots of UI chrome; keep it typographic.
- `favicon.svg`: the wordmark's oxblood period on paper, or a minimal `§`.
- Extend the `build_site.py` copy list with both assets.
- **Accept:** pasting the site URL into a LinkedIn/Slack composer unfurls with
  image and title; `tests/test_web_bundle.py` asserts the new assets ship.

## W2. Visible failures and busy states (plan A2)

**Files:** `web/app.js` (`doStep`, ~line 440), `web/style.css`.

- In `doStep`'s `catch`: call `showWorkspace("activity")` so the error entry is
  actually visible; append a retry affordance that re-sends the same action
  without re-spending user form entry (the form is already preserved).
- Add CSS for `#composer[aria-busy="true"]` (attribute is already set/cleared in
  JS; no rule exists): dim the active form, disable pointer events, show an
  inline "scoring…" indicator near the submit button.
- Disable the active form's submit button while `requestInFlight` instead of
  silently returning `null` on double-click.
- **Accept:** kill the network in devtools, submit an issue → user sees the
  failure and a retry; every submit shows a busy state during the round-trip.

## W3. Client-side citation validation and quote pre-check (plan A3)

**Files:** `web/app.js` (issue + redline submit handlers; `sectionCache`;
`parseCitation`), `web/style.css` for inline error styling.

- Build a `knownCitations` set from `obs.documents` (doc id + section tokens are
  in every observation). On issue submit, parse each citation line with the
  existing `parseCitation`; block submission with a per-line inline error for:
  malformed syntax (missing `§`), unknown document id, unknown section. Offer
  one-click normalization for common forms (`MSA §4.2` → `msa §4.2`,
  `msa 4.2` / `msa sec. 4.2` → `msa §4.2`).
- Quote pre-check on submit: normalize exactly as the scorer does (lowercase,
  collapse whitespace — mirror `rewards.py` quote normalization) and check the
  quote is a substring of the cited section's text in `sectionCache`. If the
  section was never opened, warn "cited section not yet read — quote cannot be
  verified". If the check fails, hard-warn: "this is not verbatim text of
  <citation>; a non-verbatim quote is a critical failure" with an explicit
  "submit anyway" escape hatch.
- Add an "insert §" button beside citation inputs, and a per-section "copy
  citation" affordance in the document pane that copies `docid §token`.
- Show the document id in the matter pane (e.g. a mono chip `msa` beside the
  title) so the identifier users must cite is visible before spending a step.
- **Accept:** the four failure forms (`MSA §4.2`, `msa 4.2`, `msa sec. 4.2`,
  `msa § 4.2 (training)`) are caught before a step is spent; a paraphrased
  quote triggers the hard warning; a verbatim quote passes silently.

## W4. Escalation + negotiation UI (plan A4 — deferred to post-launch)

**Files:** `web/index.html`, `web/app.js`, `web/style.css`, `docs/web-gym.md`.

- Drive the action tab list from `observation.action_schemas` instead of the
  hardcoded five; new tabs appear only when the engine publishes the action.
- **Escalate form:** topic + reason textareas; render `escalations_remaining`
  in the budget bar; show returned supervisor guidance as a distinct entry
  style (it is hidden-state earned through the action — visually mark it).
- **Negotiate form:** issue-label select (from submitted issues), proposed
  language textarea for `send_markup`; an `accept_counterparty` button on the
  pending counter. Render the per-label `negotiation` map as status chips on
  issue cards (open / countered / settled / refused) and
  `negotiation_rounds_remaining` in the budget bar.
- Extend the Learn-mode preflight for matters with counterparty/escalation
  rubric surface (do not leak which topics are required — workflow warnings
  only, same rule as today).
- Update `docs/web-gym.md`, which currently never mentions either mechanic.
- **Interim measure (do first, ships alone):** mark `nego_saas_010` and
  `msa_provider_004` as "CLI-only" in the matter dropdown with a one-line
  explanation on selection, so the browser stops offering matters it cannot
  complete. Remove the marker when this item ships.
- **Accept:** a full `nego_saas_010` episode is completable in the browser and
  can reach the reference-trajectory score; `examples/nego_saas_010/good.jsonl`
  replayed through the web driver matches the CLI score exactly.

## W5. Episode guard and resume (plan A5)

**Files:** `web/app.js`.

- `confirm()` before `startMatter()` when an episode is active and unfinished
  (header `start matter` currently discards work silently).
- `beforeunload` handler while an episode is active.
- Optional (second pass): persist `{matter, seed, actions}` to localStorage
  after each step; on load, offer resume-by-replay (the engine is
  deterministic; the worker already reconstructs episodes from action lists).
- **Accept:** mid-episode refresh and mid-episode matter-switch both require
  explicit confirmation; with the second pass, refresh offers resume.

## W6. Score screen: diagnosis and the shareable artifact (plan A6)

**Files:** `web/app.js` (`maybeScore`), `web/style.css`.

- Itemize, not count: `breakdown.invalid_citations` and
  `breakdown.fabricated_quotes` are arrays of the offending strings — render
  them as lists ("correct these citations: …"). Fabricated quotes are the
  score-capping event and must be itemized first.
- Humanize criterion IDs in the audit table (minimum: `_`→space; better: add an
  optional `display_name` per rubric criterion, threaded through the worker's
  safe result payload — verify it leaks nothing beyond what the table already
  shows). Add a `<thead>` (criterion / event / points). Render the audit
  expanded by default — auditability is the product's central claim.
- Render `settled_issues` and `raised_escalations` metrics once W4 ships.
- **Result card:** client-side canvas render of a 1200×630 PNG — wordmark,
  matter title, mode, score band, three metric lines, site URL — with
  "download card" and "copy summary" buttons. This is the LinkedIn-postable
  artifact; keep it in the design system (paper, ink, oxblood).
- **Accept:** a run with two invalid citations shows both strings verbatim; a
  fabricated-quote run names the quote; the card downloads and reads cleanly
  at feed size.

## W7. Workflow polish (plan A7)

**Files:** `web/app.js`.

- After `submitIssue`/`proposeRedline`, navigate to Review (the pane that
  gained the card), not Activity. Keep `ask`/`search` landing on Activity
  (their results live there).
- Persistent "learned facts" panel (matter pane, under the document list):
  render `observation.learned_facts` so client answers survive scrollback.
- **Accept:** submitting an issue shows the new card without extra navigation;
  a client answer remains visible while drafting the related issue.

## W8. Voice, contribute flow, and consent copy (plan A8)

**Files:** `web/contribute.js`, `web/app.js`, `web/index.html`,
`web/worker/worker.js`, `docs/web-gym.md`.

- Voice rule (write into the top of `style.css` as a comment): landing =
  editorial sentence case with lowercase CTAs; workspace = terse lowercase.
  Sweep stragglers on both sides (empty-document pane, dialog headers,
  dropdown titles).
- Restyle `contribute.js` to the shared form styles (no inline `.style.*`, no
  bare `<br>`); move the contribute block to sit directly under the score
  summary rather than below the actions row.
- **Consent copy honesty (do before any launch):** the current copy says
  "anonymous — just your actions and scores" beside an optional handle field.
  State what happens: handle is stored with the raw contribution, excluded
  from training exports. Single-source the consent version and app version
  (both are duplicated literals today: `contribute.js` vs `worker.js`
  consent date; `app_version: "0.3"` vs the engine version already displayed
  in `#engine-line`).
- **Accept:** contribute UI is visually indistinguishable from the rest of the
  design system; consent text matches `training/human_data.py` behavior
  exactly; bumping the consent version requires editing one constant.

## W9. Local development against the engine

**Files:** `web/app.js`, `engine-worker/wrangler.toml`,
`engine-worker/src/entry.py`, `CONTRIBUTING.md`.

- `API_BASE` override via `?api=` query param or localStorage key; allowlist
  `http://localhost:8000` in the engine worker's origin check (the traces
  worker already does this).
- Document the local loop in `CONTRIBUTING.md`.
- **Accept:** `python -m http.server` in `web/` + `wrangler dev` in
  `engine-worker/` yields a playable local gym.

## W10. Baseline sprint procedure (plan B1 — awaiting budget approval)

**Blocked on:** owner-provided API key and model list. Nothing runs until then.

Local preparation is complete: `playbook-baseline-sprint` emits an auditable plan without
making requests, hard-gates execution on credentials and the private split, validates the
required metrics, and generates README/report-ready output only from measured scorecards.
See `docs/baseline-sprint.md`.

- `playbook-bench --runner baseline --model <m>` per model over `matters/`,
  then top models over the private split. Capture SPEC §10 metrics including
  escalation recall, over-escalation, settled-issue ratio.
- Verify the `nego_saas_010` trap counter trips capable models (ROADMAP Phase
  2.5 open item); add a regression note to the matter if it does not.
- Human baseline: author + early testers in Benchmark mode via the verified
  trace pipeline.
- Deliverables: scorecard table in `README.md` + `docs/report.md` (the ▢
  placeholders exist); dev-vs-held-out delta stated explicitly.

## W11. M&A matter pack from MAUD deal points (plan C1 — post-launch)

**Sources:** MAUD (CC BY 4.0) deal-point categories and answer distributions;
ABA deal-points framing. Schema conversion only — no MAUD/EDGAR text becomes
load-bearing scored content (contamination).

- Pick 2–3 archetypes (e.g. private-target acquisition agreement for the
  buyer; public-target merger agreement responding to a target markup;
  carve-out with a transition-services overlay).
- For each: select 8–12 deal points (MAE definition and carve-outs,
  interim-operating covenants, fiduciary-out, termination-fee triggers,
  indemnification caps/baskets/survival, closing conditions); MAUD's answer
  distributions define the counterparty's `accept_concepts`, `resist_rounds`,
  plausible trap counters, and `non_negotiable` red lines.
- Author per `AUTHORING.md`: synthetic documents, canary, hidden facts (e.g. a
  diligence finding that changes MAE severity), reference + adversarial
  trajectories, CI green, one matter held out to the private split.
- **Accept:** `playbook-lint --all` passes; reference ≥ 0.7 with no critical;
  fabricated-quote and reversed-redline trajectories trip the gate; a
  practicing M&A reviewer says the deal-point ladder reads as real.

## W12. Harvey LAB delta experiment (plan C3 — post-launch)

- Audit `harveyai/harvey-labs` (MIT): what contracting tasks and environment
  materials actually ship in the repo vs. held out.
- Adapt a batch (target 20–50) into interactive episodes: same documents and
  playbooks, plus hidden facts, question budgets, and counterparty scripts;
  keep a mapping table from LAB task id → Playbook matter.
- Run the same models on both forms; report the score delta with the thesis
  "static rubric grading over a fully observable bundle overstates agent
  capability vs. an interactive, partially observable environment."
- Contamination caveat in the writeup: LAB is public since May 2026.

## W13. Compiler Phase A self-test (plan E2 — engine-side, independent)

Per `docs/matter-compiler.md` §6 Phase A: build the synthetic evidence-bundle
generator (fabricated `.docx` version chains with tracked changes + fabricated
threads for an existing matter), run Stages 2–8 on it, and measure how much of
the hand-authored rubric the pipeline recovers. This is the cheapest test of
the compiler thesis and requires zero firm access. Deliverable: a recovery
scorecard (issues recovered / severities matched / concepts matched) in
`docs/matter-compiler.md`.

## W14. Fix the training-export off-by-one (launch blocker)

**Files:** `src/playbook_legal/export.py`, `training/build_pairs.py`,
`artifacts/human_sft.jsonl`, new test.

- `convert()` pairs each action with `event.observation` — the observation
  *produced by* that action. The model is asked to predict `read_document`
  from an observation that already contains the section text it returned. Pair
  each action with the **previous** event's observation (the `reset()`
  observation for the first action, which currently never appears in exports).
- `build_pairs.py` slices `best_chat["messages"][:2]` as the DPO prompt and
  inherits the bug — verify after the fix that the prompt no longer contains
  the first action's result.
- Regenerate every committed export artifact (including
  `artifacts/human_sft.jsonl`); add a regression test asserting the content
  returned by action *i* first appears in the user turn *after* it.
- This contaminates `playbook-export`, `generate_rollouts`, `build_pairs`,
  and `human_data` outputs equally — one fix in `convert()` covers all, but
  all downstream artifacts must be rebuilt.

## W15. Close the anchored-stuffing reward hole (hard gate before any RL)

**Files:** `src/playbook_legal/rewards.py`, `tests/test_adversarial.py`.

- Demonstrated exploit: submit each rubric issue citing its own anchor with
  analysis/recommendation set to the concatenated `required_concepts`,
  redline text = concatenated `redline_concepts`, questions/summary likewise
  → **0.875 normalized, no critical failure, zero documents read** (reference
  is 0.9375). The current adversarial suite only tests *un-anchored* stuffing.
- First: add the anchored-stuffing episode as a failing regression test.
- Then pick a mitigation (evaluate in this order): (a) issue credit requires
  the anchor's section to have been read this episode — cheap, thematically
  right ("cite what you've read"), and closes the zero-read variant entirely;
  (b) a phrase-overlap ceiling — analysis that is mostly a concatenation of
  matched concept strings earns degraded credit; (c) partial-credit curve on
  concept density. Whatever ships must keep the reference trajectories ≥ 0.7.
- Related small hole: quotes under `MINIMUM_QUOTE_CHARACTERS = 15` are
  silently ignored — raise the floor or count a too-short quote as
  unverified rather than invisible.
- **No GRPO run happens before this ships** — the one-shot script-generation
  shape of `grpo_env_reward.py` would optimize directly into the exploit.

## W16. Make seeds real or remove them

**Files:** `src/playbook_legal/env.py`, `bench.py`, `baseline.py`.

- `self._rng` is seeded and never used; `playbook-bench --seeds 0 1 2` emits
  identical rows per matter and averages them as if independent.
- Either thread the seed into something real (pass it to the model client as
  sampling seed/temperature in `baseline.py`, the only stochastic element) or
  delete `--seeds` and the duplicate-row aggregation. Do not leave a
  replication flag that fabricates replication.

## W17. Documentation truth sweep (launch blocker)

- `docs/evaluation.md`: "six actions" → nine. `docs/report.md`: "8 public dev
  matters" → ten; reference-trajectory "≥ 0.97" → the real floor (0.7; lowest
  actual 0.9375); fill or remove the ▢ placeholder tables before launch.
- `docs/architecture.md` stale counts; README repository map is missing
  `compiler/`.
- README web-gym paragraph currently implies full parity ("same budgets and
  gates the models face") while the client exposes five of nine actions —
  qualify it until W4 ships.
- `CITATION.cff` `date-released` should be set at release, not today.
- Scorecards should record which split produced them (`bench.py` output
  currently carries no split label; the dev/held-out discipline lives only
  in prose).

## W18. Licensing and repo hygiene

- Add `SPDX-License-Identifier: AGPL-3.0-only` headers across `src/`,
  `compiler/`, `training/`, `engine-worker/src/` (zero files carry one today).
- `playbook-private`: add LICENSE and a minimal CI (lint + reference replay
  with the 0.7 floor).
- Stale `User-Agent: playbook-human-data/0.2` in `training/human_data.py`.

## W19. Private split hardening

- The held-out split (2 matters, both customer-side review) exercises none of
  v0.3: no escalations, no counterparty, no clean matter — so escalation
  recall and settled-issue ratio return vacuous 1.0 on the split SPEC §10
  says to report. Add at minimum: one negotiation matter, one
  escalation-bearing matter, one clean (no-material-issues) matter, each with
  adversarial trajectories.

## W20. CI and worker integrity

- CI check that the vendored engine copy inside `engine-worker/` matches
  `src/playbook_legal` (`vendor.py` output is currently unverified; a stale
  vendor dir would deploy silently). Add a test for `entry.py` with `js`/
  `workers` mocked.
- Lint `compiler/` in CI (the compiler README instructs it; CI omits it).
- Decide the terminal-trace posture for the web gym: on termination the
  worker returns the full breakdown (criterion IDs, matched concepts), which
  lets a user reconstruct rubric internals across a handful of episodes.
  Acceptable for the assumed-contaminated dev split, but then say so: web
  scores on public matters are not benchmark numbers. Alternatively trim the
  breakdown returned in Benchmark mode.
- Negotiation handlers accept `send_markup` on matters with no counterparty
  (degrades to −0.5; unpublished action surface) — reject as protocol error
  instead.
