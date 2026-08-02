# Using the web gym

The [Playbook web gym](https://jamesbaker1.github.io/playbook/) lets a person work
the same synthetic matters, under the same budgets and deterministic scoring
rules, as an automated legal agent. It is designed to feel like a compact legal
workspace: a matter file on the left, a document in the center, and work-product
controls on the right.

The gym is an evaluation and research tool, not legal advice. All shipped matters
are synthetic.

## First-time use

1. Open the web gym and wait for **matters ready**. The first visit downloads the
   Python/WebAssembly runtime, scoring engine, and synthetic matter files. Expand
   the startup-status row only if you want to see those details.
2. Choose **try the guided matter** for the recommended introduction, or select a
   matter in the header and choose **start matter**.
3. Open the supervising-lawyer instructions and playbook before reviewing the
   contract. Opening a section is an action and spends one step.
4. Work the matter using the controls described below. The budget indicator in the
   header shows the steps and client questions that remain.
5. Add a final supervising-lawyer update, choose **submit final work product**, and
   review the preflight check. Final submission ends the matter and cannot be
   undone.
6. Inspect the criterion-level score. You may download the audit trace, optionally
   contribute it, or choose another matter.

Use **how to play** in the header for a shorter reminder inside the application.

## The desktop workspace

The layout borrows familiar ideas from Outlook, Word, and Teams without attempting
to reproduce those products.

| Area | Purpose |
| --- | --- |
| **Matter** | The left pane is the matter file. It lists documents and their sections. Select a section to read it. Previously opened sections are marked. |
| **Document** | The center workspace displays the current provision. Citations in submitted issues can reopen their source text. |
| **Work** | The right pane contains the actions used to investigate the matter and create work product. |
| **Issues** | The center **Review** tab collects submitted issues, their priority, analysis, citations, recommendation, and redline status. It is the closest view to a working issues list. |
| **Activity** | The center **Activity** tab is the chronological audit trail: actions, client responses, search results, incremental rewards, errors, and the final score. |

The progress checklist in the Work pane is orientation, not a guarantee of a good
score. Legal correctness, grounding, prioritization, and drafting quality still
matter.

## Actions

Every action spends a step, including reading and searching. The exact environment
contract is documented in [Environment API](environment.md); the web controls map
to it as follows.

### Read a provision

Select a document section in **Matter**. Read selectively: opening every section
can exhaust the step budget. The supervising-lawyer instructions and playbook
usually provide the best starting context.

### Ask the client

Use **ask client** for a fact that could change the advice, risk level, or
negotiating position. Every question consumes both a step and the limited client-
question budget, including repetitive or unproductive questions.

### Search the record

Use **search** to find a term across documents. Search is a case-insensitive
substring search and the query must contain at least three characters. Results
appear in Activity; opening a resulting section is a separate action.

### Add an issue

Use **add issue** to submit:

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

Submit the issue first, then use **redline** or **Draft a redline** on its issue
card. Choose the linked issue, identify the provision, supply complete replacement
language, and explain how it implements the client position. Merely describing a
change is not replacement language.

### Finish the review

Use **finish** for a concise update to the supervising lawyer. Lead with material
risks, relevant learned facts, recommended positions, and anything that should
block signature.

The preflight dialog reports sections reviewed, questions asked, issues submitted,
redline coverage, and steps remaining. It warns about obvious workflow gaps, such
as a high-priority issue without draft language. It does **not** assess whether the
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
benchmark; they are not a credential or a measure of general legal competence.

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

## Privacy and local execution

Matter actions and scoring run locally in the browser using the repository's real
Python engine through WebAssembly. There is no account and no scoring API. Loading
the page still downloads ordinary website assets and the Python runtime from their
hosts, as any web application does.

No trace is uploaded during play or when you choose **download trace**. After a
completed matter, the gym separately offers **contribute trace**. Contribution is
optional and requires an explicit click. The uploaded payload contains the action
trace and score plus an optional handle; contributed traces are replay-verified
before they are accepted for training use. Review a downloaded trace before
contributing if you want to see exactly what it contains. Do not enter real client
information: these are synthetic exercises.

## Common pitfalls

- **Loose quotation:** never put a paraphrase in a quote field. A non-verbatim quote
  is treated as fabrication and triggers the score cap.
- **Budget drift:** reads, searches, questions, issues, redlines, and final
  submission all consume steps. Every client question also consumes its separate
  budget.
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
