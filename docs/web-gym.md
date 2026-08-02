# Using the deal review workspace

The [Playbook deal review workspace](https://jamesbaker1.github.io/playbook/) lets a person work
the same synthetic matters, under the same budgets and deterministic scoring
rules, as an automated legal agent. It is designed to feel like a compact legal
workspace: a matter file on the left, a document in the center, and work-product
controls on the right.

The gym is an evaluation and research tool, not legal advice. All shipped matters
are synthetic.

## First-time use

1. Open the web gym and wait briefly for **matters ready** while the page checks the
   scoring service. No Python runtime or matter internals are downloaded.
2. Choose **Guided review** for workflow guidance and a final completeness check, or
   **Assessment review** for an independent attempt with no prompts or pre-submit warnings. Then
   open the recommended matter or choose another from the header.
3. Open the supervising-lawyer instructions and playbook before reviewing the
   contract. A document opens in full and is cached for the rest of the review.
4. Work the matter using the controls described below. The budget indicator in the
   header shows the steps, client questions, escalations, and (when applicable)
   negotiation rounds that remain.
5. Add a final supervising-lawyer update, choose **submit final work product**, and
   review the preflight check. Final submission ends the matter and cannot be
   undone.
6. Inspect the criterion-level score. You may download the audit trace, optionally
   contribute it, or choose another matter.

Use **workspace guide** in the header for a shorter reminder inside the application.

## Leaving and resuming

While a matter is unfinished, the browser saves its matter ID, seed, mode, and exact
accepted action sequence in local storage after every action. Unsent form drafts are
saved separately in the browser's IndexedDB after a short pause in typing, with a
local-storage fallback when IndexedDB is unavailable. If you return on the same
device, choose **resume review** to replay that sequence through the scoring service and
reconstruct the workspace deterministically. The browser warns before a page exit or
before replacing an active review. Final submission and an explicit discard remove the
saved episode.

## The desktop workspace

The layout borrows familiar ideas from Outlook, Word, and Teams without attempting
to reproduce those products.

| Area | Purpose |
| --- | --- |
| **Matter** | The left pane is the matter file. It lists documents and their outlines, followed by facts learned from the client or supervising counsel. Open a document by title or jump directly to a section. |
| **Document** | The center workspace displays the complete document. Select clause text to flag an issue, begin a draft change, or copy its citation. Citations reopen and highlight their source. |
| **Deal team & work product** | The right pane contains client, supervisor, and counterparty communications alongside issue, drafting, search, and status-report tools. |
| **Issues** | The center **Review** tab collects submitted issues, their priority, analysis, citations, recommendation, and redline status. It is the closest view to a working issues list. |
| **Activity** | The center **Activity** tab is the chronological audit trail: actions, client responses, search results, errors, and the final score. Questions and searches navigate here automatically. Intermediate rewards are deliberately withheld. |

Submitting an issue or redline navigates to **Review**, so the new work product and its
status are immediately visible.

The progress checklist in Guided review is orientation, not a guarantee of a good
score. Assessment review hides this guidance. Legal correctness, grounding,
prioritization, and drafting quality still matter.

## Actions

Canonical actions spend a step, including opening a new document and searching. Moving
within an already-open document, selecting text, and editing local drafts do not. The exact environment
contract is documented in [Environment API](environment.md); the web controls map
to it as follows.

### Review a document

Select a document title in **Matter** to open its complete text. Its outline jumps
to sections without another request. The supervising-lawyer instructions and playbook
usually provide the best starting context. `Ctrl/Cmd+Shift+F` opens matter search;
`Alt+I` and `Alt+R` move to issue and drafting work.

### Ask the client

Use **ask client** for a fact that could change the advice, risk level, or
negotiating position. Every question consumes both a step and the limited client-
question budget, including repetitive or unproductive questions.

### Search the record

Use **search** to find a term across documents. Search is a case-insensitive
substring search and the query must contain at least three characters. Results
appear in Activity; opening a resulting section is a separate action.

### Add an issue

Select operative language and choose **flag issue** to prefill its citation and a
stable internal label, then complete:

- your own short internal label;
- a clear title and priority;
- one citation per line, with the operative contract provision first;
- analysis explaining the conflict, consequence, and relevant client fact; and
- the preferred position and any acceptable fallback.

Write citations as `document §section`, for example `msa §4.2`. The internal label
is only a stable link between your issue and its redline; it is not a rubric code.

Quotes are optional. If you add one, copy it exactly from the cited section. Put
paraphrases in the analysis instead. Quote verification ignores capitalization and
normalizes whitespace, but invented or inaccurate quoted language is a critical
failure. See [The scoring contract](scoring.md#quote-verification--the-fabrication-gate).

### Draft a redline

Submit the issue first, then select language and choose **draft change**, or use
**Draft a redline** on its issue
card. Choose the linked issue, identify the provision, supply complete replacement
language, and explain how it implements the client position. Merely describing a
change is not replacement language.

### Escalate a decision

When the engine publishes **escalate**, use it for a point outside your delegated
authority. Name the topic and explain the counterparty position, business impact,
and reason approval is required. A valid escalation spends the limited escalation
budget. Guidance returned by supervising counsel appears as a distinct earned entry
in Activity.

### Negotiate markup

Matters with a scripted counterparty publish **negotiate**. First submit the issue,
then choose that issue label, identify the provision, and send complete proposed
language. The issue card shows whether the point is open, countered, settled, or
refused. A pending counterparty proposal can be accepted explicitly. Each markup
sent and each acceptance consumes a negotiation round. Check a counter against the
playbook before accepting it: plausible language can still cross a non-negotiable
boundary.

### Finish the review

Use **status report** for a concise update to the supervising lawyer. The workspace
generates an editable first draft from the ordered issue list. Lead with material
risks, relevant learned facts, recommended positions, and anything that should
block signature.

In Learn mode, the preflight dialog reports sections reviewed, questions asked, issues submitted,
redline coverage, escalation and negotiation workflow counts, and steps remaining.
It warns about obvious workflow gaps, such as a high-priority issue without draft
language, an unused escalation workflow, or an open negotiated issue. These are
workflow reminders only: the browser does not identify required escalation topics
or reveal what the counterparty will accept. It does **not** assess whether the
legal judgment is correct. Choose **Keep reviewing** to return safely, or confirm
submission to end the episode.

## Score and audit trace

The result is shown on a 0–100 scale with raw points and a criterion-level event
table. Positive and negative events remain separate so the result is auditable.
Running out of steps truncates the episode. A critical failure caps the normalized
score even if other work earned points.

Choose **download trace** to save the complete JSON audit trail locally. For the
meaning of each scoring component, penalties, and caps, read
[The scoring contract](scoring.md). Scores measure performance on a synthetic
practice environment; they are not a credential or a measure of general legal competence.

The terminal audit deliberately includes criterion IDs, matched concepts, and reward events. That
detail makes practice feedback useful, but repeated runs can reveal the rubric. All matters served by
the public web gym are therefore the assumed-contaminated **development split**. A web-gym score is
not a reportable benchmark number. Held-out evaluations run through the private harness and do not
publish matters, rubrics, or terminal traces.

## Mobile use

On a narrow screen the workspace becomes one pane at a time. The persistent bottom
navigation keeps the same mental model:

- **Matter** — choose a document section;
- **Document** — read the open section;
- **Work** — ask, search, submit issues, draft redlines, and finish;
- **Issues** — review submitted work product and start linked redlines; and
- **Activity** — inspect responses, results, errors, and score events.

A practical mobile loop is **Matter → Document → Work → Issues**. Use Activity
when you need a client answer, search result, or action history. Draft text may be
awkward on a phone, so prepare long replacement language elsewhere if needed, then
paste and verify it before submission. Do not rely on the browser Back button to
move between workspace panes; use the bottom navigation.

## Privacy and service processing

The website sends the selected synthetic matter ID and your action history to the
Playbook scoring service. The service runs the canonical Python environment and
returns safe observations, client answers earned through actions, and terminal
results. Rubrics, hidden facts, counterparty positions, and scorer source remain on
the service and are not included in the website bundle.

The scoring service necessarily processes your actions during play. Choosing
**download trace** does not send the completed trace to the separate training-data
collector. After a completed matter, **contribute trace** offers that additional,
optional upload and requires explicit, versioned training/evaluation consent. Its
payload contains the action trace, score, Learn/Benchmark mode, application version,
and optional professional-background category and handle. The optional handle is
stored with the restricted raw contribution as provenance, then deliberately omitted
by `training/human_data.py` from every training export. Contributions are
replay-verified before export.
Do not enter real client or confidential information: these are synthetic exercises.

The consent version has one source, `web/policy.json`, read by the upload UI, trace
worker, and replay/export verifier. The application version is the engine version
returned by the canonical scoring service and displayed in the footer; the browser
does not maintain a separate version literal.

## Common pitfalls

- **Loose quotation:** never put a paraphrase in a quote field. A non-verbatim quote
  is treated as fabrication and triggers the score cap.
- **Budget drift:** reads, searches, questions, issues, redlines, escalations,
  negotiation actions, and final submission all consume steps. Questions,
  escalations, and negotiation rounds also have separate budgets.
- **Redline before issue:** redlines must link to one of your submitted issue
  labels. Submit and check the issue first.
- **Wrong citation order:** cite the operative contract provision first, then the
  playbook or supporting provisions. The first qualifying anchor controls issue
  matching.
- **Invalid citation syntax:** use the displayed document identifier and exact
  section, formatted `document §section`.
- **Keyword-only analysis:** citing a provision or repeating expected terminology
  is not a substitute for explaining the conflict and consequence.
- **Premature final submission:** final submission is irreversible. Use the
  preflight check and preserve enough steps to submit.
- **Treating Activity as the document:** Activity is the audit trail. Return to
  Document to verify source language and to Issues to review the work product.

## Related documentation

- [Environment API](environment.md) — actions, observations, budgets, and results
- [Scoring](scoring.md) — deterministic matching, quote verification, redlines,
  and critical failures
- [Architecture](architecture.md) — how the engine and repository fit together
- [Evaluation](evaluation.md) — running and interpreting benchmark evaluations
