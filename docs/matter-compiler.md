# The Matter Compiler

**Status: design + Phase A known-answer implementation.** The tracked-changes miner,
correspondence document type, and synthetic known-answer self-test work today
(`compiler/`, `tests/test_compiler.py`). Everything that requires access to a real
firm corpus remains specified here and stubbed in `compiler/pipeline.py`. Nothing in
this document changes the public repository's posture: **the public gym stays 100%
synthetic, and the compiler is self-hosted.**

---

## 1. The thesis

Playbook's architecture already contains the hard commitment that makes this
possible: *matters are data*. The runtime, the reward engine, the exporters, and the
training scaffolds never look at a matter's subject matter — they look at four files
and a section-addressing convention. `docs/architecture.md` says it directly:

> anything that can emit a valid matter package (an expert, a template generator, or
> a pipeline over a private document corpus) plugs into the same runtime, scoring,
> and training stack.

So the compiler's job is narrow and testable: **turn one deal's artifact trail into
a package that `playbook-lint` accepts and whose derived reference trajectory
replays to ≥ 0.7 with no critical failure.** If it can do that, everything
downstream — episodes, benchmarks, SFT, DPO, GRPO, the web player — comes free.

Why it matters commercially and scientifically: the synthetic matters encode *my*
model of good technology-transactions work. A firm's corpus encodes *its* model —
its actual positions, its actual escalation thresholds, its actual house style, and
(uniquely) its record of what the other side accepted. That is the institutional
knowledge that never makes it into a training set, because it cannot leave the
building. The compiler is the answer to "it cannot leave the building": we send the
compiler in instead of taking the data out.

### What a compiled matter looks like

```text
Real world                                    Compiled matter package
────────────────────────────────────────      ──────────────────────────────────
Draft MSA v1 from the other side          →   documents/msa.md (anonymized)
Partner's tracked changes on v3           →   rubric issues + redline_concepts
Associate's issues-list memo              →   rubric issue set + severities
Supervising partner's assigning email     →   documents/instructions.md
Client's answers to "does this process
  regulated data?"                        →   hidden_facts.client_answers
                                              + rubric questions.concepts
Counterparty's "we can't do 24 hours"     →   severity + leverage calibration
The partner's own sequence of work        →   examples/<id>/good.jsonl
```

---

## 2. Source inventory: what exists at a firm, and how to get it

The corpus is real but scattered across five systems with five different access
models. This section is the field guide. **Read-only everywhere; the compiler never
writes to a system of record.**

### 2.1 Email — Microsoft Graph (primary), PST (fallback)

Most firms are on Exchange Online. Graph is the supported path.

**Endpoints.** `GET /users/{id}/messages`, `GET /users/{id}/mailFolders/{id}/messages`,
`GET /users/{id}/messages/{id}/attachments`, and
`GET /users/{id}/mailFolders/{id}/messages/delta` for incremental sync (persist the
`@odata.deltaLink`). Batch with `POST /$batch` (20 requests max per batch).

**Fields that matter**, and why:

| Field | Why the compiler needs it |
| --- | --- |
| `internetMessageId`, `internetMessageHeaders` (`In-Reply-To`, `References`) | RFC 5322 threading — the only threading signal that survives crossing organizations |
| `conversationId`, `conversationIndex` | Exchange's own threading; `conversationIndex` is a 22-byte header plus 5-byte child blocks, so the *reply tree* (not just the flat set) is recoverable |
| `from`, `sender`, `toRecipients`, `ccRecipients`, `bccRecipients`, `replyTo` | Participant graph → matter clustering, and internal/client/counterparty classification, which drives both mining and privilege filtering |
| `sentDateTime`, `receivedDateTime` | Version-chain ordering; `sentDateTime` is authoritative for sequence |
| `subject`, `bodyPreview` | Client-matter numbers are conventionally in the subject (`[12345-0001]`) |
| `body` (`contentType` html/text), `uniqueBody` | `uniqueBody` strips the quoted history — essential, because top-posted threads otherwise duplicate every earlier message N times |
| `hasAttachments`, `attachments` (`fileAttachment.contentBytes`) | The redlines: attached `.docx` turns that never reached the DMS |
| `parentFolderId`, `categories` | Firm filing conventions; a folder named for the matter is free clustering |
| `isDraft` | Drafts are unsent thoughts — exclude from "what was actually communicated" |

Request `Prefer: IdType="ImmutableId"` so ids survive mailbox moves, and always
`$select` explicitly (payloads are large and throttling is per-mailbox).

**Permissions.** Two shapes, and the difference is an ethics question, not an IT
question:

- *Delegated* (`Mail.Read`, `Mail.ReadBasic`) — the compiler acts as a specific
  lawyer and sees exactly what that lawyer sees. Wall-safe by construction.
- *Application* (`Mail.Read` app permission) — the app can read **every** mailbox in
  the tenant. This punches straight through ethical walls and is unacceptable
  unscoped. Constrain it with an **Application Access Policy**
  (`New-ApplicationAccessPolicy` in Exchange Online PowerShell) restricting the app
  to a mail-enabled security group holding only the lawyers on consented matters,
  or use Exchange's newer RBAC for Applications. §5.3 treats this as a hard gate.

**Throttling.** The Outlook backend allows roughly 10,000 requests per app per
mailbox per 10 minutes with ~4 concurrent requests; ingestion must be resumable and
respect `Retry-After` on 429s. A single practice group's five-year mail history is a
multi-day crawl, not an afternoon.

**eDiscovery route.** Where the firm's records team owns collection (often the right
political answer), use Microsoft Purview eDiscovery: create an `ediscoveryCase`, a
`sourceCollection` scoped by KQL to custodians and date range, commit to a
`reviewSet`, and export. This yields already-deduplicated, already-defensible
collections with a load file — and it inherits the firm's existing legal-hold and
chain-of-custody discipline.

**PST fallback (offline).** Closed matters are often archived to PST. Parse with
`libpff`/`pypff` or `readpst`; the MAPI properties map to the Graph fields above —
`PR_INTERNET_MESSAGE_ID` (0x1035), `PR_CONVERSATION_INDEX` (0x0071),
`PR_CONVERSATION_TOPIC` (0x0070), `PR_CLIENT_SUBMIT_TIME` (0x0039),
`PR_TRANSPORT_MESSAGE_HEADERS` (0x007D), `PR_SENDER_SMTP_ADDRESS`. Two traps:
Exchange-native messages store addresses as X.500 `EX` DNs rather than SMTP (resolve
via the address book or `PR_SMTP_ADDRESS`), and rich-text messages arrive
TNEF-encapsulated (`winmail.dat`) with attachments inside. Google Workspace firms
substitute Vault exports (MBOX) with the same header logic.

**Known failure modes.** BCC recipients are invisible from the recipient's copy;
`conversationId` splits when someone edits the subject line; auto-appended
confidentiality footers pollute every body and must be stripped before concept
extraction; "external" tagging banners do the same; and a partner who negotiates by
phone leaves an empty thread with a one-line "per our call, revised attached."

### 2.2 Document management — iManage and NetDocuments

The DMS is where the compiler gets the most value for the least inference, because
**a human has already done the clustering**: the workspace *is* the matter.

**iManage Work.** REST at `/work/api/v2/customers/{customerId}/libraries/{lib}/…`:
`documents/{docId}` , `documents/{docId}/versions`, `documents/{docId}/download`,
`workspaces/{id}/children`, `documents/search`. Auth is OAuth 2.0 against the
iManage auth service (authorization-code for user-scoped access; client-credentials
for service access — see the wall problem in §5.3). Document identity is
`LIBRARY!docnum.version`, which gives version chains for free *when the turns were
actually saved as versions*. Profile metadata lives in `class`/`subclass` (document
type: `AGMT`, `CORR`, `MEMO`) and firm-configured `custom1..custom30` fields —
`custom1`/`custom2` are conventionally client and matter, but **verify per firm; the
profile schema is a firm-level configuration, not a standard**. The `/history`
endpoint (view/edit/check-in events per user) is the raw material for the reference
trajectory: it is literally a log of which documents the partner opened, in order.
Security is enforced by ACLs plus "Need to Know" security and, in many firms,
iManage Security Policy Manager.

**NetDocuments.** REST at `api.vault.netvoyage.com` with OAuth 2.0 scopes
(`read`, `full`, `organization`); objects are repository → cabinet → workspace →
document, with numbered profile attributes (client and matter are conventionally
attributes 22 and 23 — again firm-configured). Versions are first-class with an
"official version" designation, which is a strong signal for "this is the executed
one." NetDocuments' **ndMail** files email directly into the matter workspace: where
a firm uses it, correspondence arrives pre-clustered and pre-classified, which
collapses Stage 1 from a hard inference problem to a lookup.

**Others.** SharePoint/OneDrive (via Graph `driveItem`, with `versions`), OpenText
eDOCS, Worldox. Same shape: a matter container, versioned binaries, a profile.

**Known failure modes.** Version chains lie. Real turns arrive as email attachments
and get saved as *new documents* with names like `MSA v7 (Acme comments) (JB
edits).docx`; the document may be "version 1" while being the eighth turn. Documents
get moved between workspaces at matter close. Scanned executed PDFs have no text
layer. And the most valuable single artifact — the associate's **issues list** — is
usually filed as a `MEMO` with no distinguishing metadata at all.

### 2.3 Tracked changes — OOXML, parsed directly

This is the highest-signal source in the building and it is fully machine-readable
without a diff. A `.docx` is a zip; `word/document.xml` carries:

| Element | Meaning | Attributes |
| --- | --- | --- |
| `w:ins` | insertion; text in child `w:r/w:t` | `w:id`, `w:author`, `w:date` |
| `w:del` | deletion; text in child `w:r/w:delText` | `w:id`, `w:author`, `w:date` |
| `w:moveFrom` / `w:moveTo` | a move, as a matched pair | same |
| `w:rPrChange`, `w:pPrChange`, `w:tblPrChange`, `w:sectPrChange` | formatting-only revisions | same |
| `w:commentRangeStart` / `End` / `w:commentReference` | comment anchors | `w:id` |

`word/comments.xml` holds `w:comment` (author, initials, date, body);
`commentsExtended.xml` adds reply threading (`w15:paraIdParent`) and resolution
state (`w15:done`). Revisions also live in `footnotes.xml`, `endnotes.xml`, and
header/footer parts — a compiler that only reads `document.xml` silently drops
footnote edits.

**Author + timestamp is the point.** Every substantive edit is attributed and
time-ordered, which is what lets Stage 3 say "the *partner* changed this on the
third turn" rather than "the text differs." A comment that says *"playbook requires
2x; do not concede"* is a rubric criterion in the wild.

**Known failure modes**, all real:

- **Metadata cleaning.** Litera Metadact (and Word's own "Remove personal
  information from file properties on save", `w:removePersonalInformation` in
  `settings.xml`) rewrites every `w:author` to `Author`. Outbound documents are
  routinely cleaned, so attribution survives on *inbound* copies from the other side
  but is often destroyed on the firm's own sent copies. Prefer the sender's original
  in the DMS over the cleaned copy in the sent-mail folder.
- **Accepted changes.** Someone accepts all before saving. The redline then only
  exists as the *difference* between versions — hence `paragraph_views()` and the
  Stage 2 diff path.
- **Auto-numbering.** Clause numbers generated by `numbering.xml` do not appear in
  paragraph text at all, so a text-based section heuristic returns nothing. The
  emitter renumbers to `## X.Y` tokens anyway (§3.7), but anchoring during mining
  needs the `w:numPr`/`numbering.xml` resolution or a structural fallback.
- **Legacy `.doc`.** Not a zip. Convert (LibreOffice headless) before ingestion;
  `compiler.redline_miner` raises a clear `ValueError` rather than guessing.

### 2.4 Comparison outputs (Litera and friends)

Firms generate comparisons constantly — Litera Compare / Change-Pro / DeltaView,
Workshare Compare. Two output modes matter:

1. **Rendered comparison** — a `.docx` where insertions are underlined and deletions
   struck through as *direct character formatting*, not `w:ins`/`w:del`. Parsing
   requires reading `w:rPr` (`w:u`, `w:strike`) and the comparison's colour
   convention, which is configurable and therefore unreliable. Treat as second-best.
2. **Comparison emitted as tracked changes** — most tools can do this; then it parses
   with the normal miner, but the `w:author` is the *comparison tool*, not a lawyer.

Comparison documents are the fallback when the version chain has holes: a `v3 vs v7`
comparison filed in the DMS recovers the net effect of turns 4–6 even when those
turns are gone. Litera's change-summary table is also a usefully pre-classified
inventory of edit locations.

### 2.5 Matter, billing, and governance metadata

- **Practice management** (Elite 3E, Aderant Expert): matter master with client and
  matter numbers, practice-area/department codes, responsible/originating/billing
  timekeepers, open and close dates, matter type. This is where `practice_area` and
  `role` in `matter.yaml` come from, and where "who was the partner" is answered
  authoritatively rather than by mailbox heuristics.
- **E-billing / time entries** (LEDES 1998B: `LINE_ITEM_TASK_CODE`,
  `ACTIVITY_CODE`, narrative text). UTBMS Project codes (P300 drafting, P400
  negotiation) and activity codes are quietly the best labelled data in the firm.
  In particular the activity codes distinguish communications by counterparty —
  in-firm, with client, with opposing counsel — which is simultaneously a matter
  classifier *and* a privilege signal. And time narratives partially recover the
  missing phone-call rationale: *"T/c with opposing counsel re liability cap;
  agreed 2x supercap for security incidents"* is exactly the reasoning that never
  appears in the document trail. Caveat: narratives are terse, sometimes
  reconstructed days later, and are themselves confidential client information.
- **Engagement letters and outside counsel guidelines (OCGs)** — the consent layer
  (§5.2). Machine-readability is poor; treat as a human-reviewed registry.
- **Conflicts / ethical-wall systems** (Intapp Walls, iManage SPM) — the authority
  on which matters a given identity may see. The compiler must *respect* it, not
  route around it.
- **Closing checklists and closing binders** — a curated index of a deal's final
  document set and open points. For transactional matters this is close to a
  ready-made document manifest.

### 2.6 What is not in the corpus

Stated plainly, because the compiler's honesty depends on it:

- **Phone and hallway negotiation.** The single most common failure. The document
  changes; the *reason* was spoken. Partial recovery: billing narratives (above),
  "per our call" emails, and the associate's summary memo. Where the reason cannot
  be recovered, Stage 5 must mark the issue `rationale: unrecovered` and a lawyer
  must supply it or the issue is dropped. An invented rationale is worse than a
  missing one — it teaches a model to confabulate deal history.
- **Teams/Slack chat**, unless the firm retains and exports it (Graph
  `chatMessage` with `Chat.Read.All` — a much more sensitive permission than mail).
- **Judgment calls that produced no edit.** The clause the partner read and
  deliberately left alone is invisible; absence of a redline is not evidence of
  approval. This biases derived rubrics toward *changed* provisions and is a real
  scientific limitation of the whole approach, not a bug to be fixed.

---

## 3. The reconstruction pipeline

Nine stages. Each one reads the previous stage's checkpoint and writes its own, as
JSONL plus a manifest (stage name, code version, input hashes, output hash,
operator, timestamp). Checkpoints exist so a lawyer can inspect and correct the
intermediate product, and so a rejected package can be traced to the stage that got
it wrong. Stages 3–5 additionally emit a **review queue** — the unit of human work.

```text
 0 intake    → 1 cluster → 2 order → 3 redlines ┐
                                                ├→ 5 rubric → 6 anonymize → 7 emit → 8 validate
                                4 correspondence┘        ▲                              │
                                                         └───── lawyer review ──────────┘
```

Implementation status: Stage 3's extractor and Stage 4's renderer are written
(`compiler/redline_miner.py`, `compiler/correspondence.py`); the stage functions
themselves are typed stubs in `compiler/pipeline.py` that name the section here.

### 3.0 Stage 0 — Intake and chain of custody

Every artifact gets a `SourceArtifact` record: origin system, that system's stable
external id (iManage `LIB!docnum.version`, NetDocuments `ndmid`, Graph immutable
message id), SHA-256 of the bytes, capture timestamp, and the operator identity that
performed the capture. Bytes land in a write-once vault with a retention clock.
Nothing downstream re-reads a system of record — reproducibility and audit both
require that the compiler run against the frozen intake set.

Gate: an artifact whose matter is not on the consent register (§5.2) is rejected at
intake and never written to the vault.

### 3.1 Stage 1 — Cluster artifacts into matters

Signals, in descending order of reliability:

1. **DMS workspace membership** — authoritative; a human filed it. Where every
   artifact is filed, Stage 1 is a lookup and should say so in `rationale`.
2. **Client-matter number** in a subject line, filename, or profile field.
3. **Participant graph + time window** — the set of internal lawyers plus external
   domains, bounded by the matter's open/close dates from practice management.
4. **Thread identity** — `internetMessageId`/`References`, then `conversationIndex`.
5. **Content similarity** — MinHash/TF-IDF over normalized text, for the loose
   drafts saved to someone's OneDrive with a meaningless name.

Output is a `MatterCluster` with a confidence and a written rationale. Low-confidence
clusters go to review rather than into the pipeline: a *contaminated* cluster (two
matters merged) is the single most dangerous error in the system, because it can put
Client A's confidential position into Client B's compiled matter. Bias hard toward
precision; dropping a matter costs one training example.

### 3.2 Stage 2 — Order the version chain

Build a DAG per logical document (the "MSA", the "DPA"), not per file. Order by:
DMS version number where the chain is intact; otherwise `sentDateTime` of the email
that carried the attachment; break ties by content similarity to the neighbours.
Detect and **report** gaps rather than smoothing over them:

- a `w:ins` in version *N* whose text is absent from version *N−1* as a base → a
  missing intermediate turn;
- an executed version whose text diverges from the last known draft by more than a
  threshold → turns negotiated outside the captured channel;
- two "version 4" documents from different senders → parallel markups.

`VersionChain.gaps` is a first-class output. A chain with gaps can still produce a
valid matter (the executed document plus one clean redline is enough), but the
derived reference trajectory must not claim a sequence it cannot support.

### 3.3 Stage 3 — Mine the redlines

For each adjacent pair in the chain:

1. **Parse tracked changes** with `compiler.redline_miner.extract_edits()` — author,
   date, inserted/deleted text, paragraph context, section hint.
2. **Diff where changes were accepted** — `paragraph_views()` yields both the
   reject-all and accept-all rendering of every paragraph; a paragraph-aligned diff
   against the prior version recovers the net edit.
3. **Merge substitutions** — `merge_substitutions()` collapses an adjacent
   delete/insert by one author into a single "was X, now Y" record, which is the
   shape a rubric issue actually has.
4. **Classify** each edit as substantive / conforming (defined terms, cross-refs,
   numbering) / typographic / formatting. Only substantive edits become candidates.
   This is the classifier with the most leverage in the whole system and the one
   most in need of firm-specific training data; the first version is rules
   (edit length, provision type, whether a monetary or temporal quantity changed,
   whether the author is a partner) plus a model proposal, reviewed by a lawyer.
5. **Weight by author seniority** from practice-management data. A partner's edit on
   a fourth turn that *survived to execution* is the strongest possible signal; an
   associate's first-pass edit that was later reverted is a negative example (and is
   genuinely useful later as a `bad_*.jsonl` trajectory).
6. **Emit a `CandidateIssue`**: `anchor_hint` (the provision the edit sits in),
   `title`, `severity` (initially from survival-to-execution and escalation
   language), `redline_concepts` (content-bearing phrases from the inserted text),
   `required_concepts` (from the associated comment or memo language), and
   `evidence_ids` pointing back to intake records.

`redline_concepts` derived mechanically from inserted text is the sharpest edge in
the pipeline: it will contain the firm's distinctive drafting, which is precisely
what §3.6 must rewrite, and it must never contain generic filler that a keyword-
stuffing agent could hit (the repository's adversarial tests exist to catch exactly
that — see `AUTHORING.md`, "Good rubric criteria").

### 3.4 Stage 4 — Mine the correspondence

Threads are rendered with `compiler.correspondence` and classified by participant
role, which comes from the domain plus the practice-management/UTBMS signals:

| Thread type | Becomes |
| --- | --- |
| Supervising lawyer → associate ("please review against the playbook, we need X") | `documents/instructions.md`, plus `matter.yaml.assignment` and `role` |
| Internal precedent / "our standard position is" | `documents/playbook.md` positions |
| Lawyer → client questions and the **client's answers** | `hidden_facts.client_answers` + the rubric `questions` (concepts drawn from the question actually asked, aliases from paraphrases across matters) |
| Counterparty negotiation | severity and leverage calibration: what was conceded immediately (low), what took three turns (high), what was escalated to the client (critical) |
| Anything with an adverse party on it | privilege review (§5.3) before any use |

The client-answer path is the most valuable and the most delicate. A question the
partner actually asked, and the answer that actually changed the analysis, is a
perfect rubric question — the environment's whole "ask under budget" mechanic is a
simulation of this exchange. It is also, verbatim, confidential client information;
it must survive Stage 6 as a *fact shape* (e.g. "processes regulated health data,
no HIPAA PHI expected") rather than as the client's words.

Design constraint that falls out of the environment's contract: a fact that appears
in a correspondence document **cannot** also be a hidden fact, because the agent can
just read it. Stage 4 must therefore *split* the record — the question thread goes
to `hidden_facts.yaml`, and only the messages a reviewing associate would have been
handed go into `documents/`.

### 3.5 Stage 5 — Model-assisted rubric derivation (always lawyer-reviewed)

A model running **inside the firm's tenant** receives the evidence bundle (candidate
issues, the redline records with authors and dates, mined instructions and
positions, the executed text) and proposes a draft `rubric.yaml`. Every proposed
element must carry an `evidence_ids` list; a proposal that cannot cite the artifact
it came from is rejected automatically. The model proposes:

- the issue set and each issue's `anchor` (unique, resolving, and in
  `required_citations` — the linter enforces all three);
- `severity`, justified by the negotiation record;
- `required_concepts` and `redline_concepts`;
- `critical_failure_patterns` — derived from what the firm treats as unacceptable
  (the escalation emails are the source: "we cannot agree to this without client
  sign-off");
- questions and their `concepts`/`aliases`.

**The lawyer review is not a formality; it is the product.** A reviewer accepts,
edits, or rejects each element, and the acceptance ledger (who, when, what changed)
is stored with the package. Under Model Rule 5.3 the compiler is nonlawyer
assistance, and the reviewing lawyer owns the output; under 5.1 the supervising
lawyer owns the review process. The review UI should show, for each proposed issue,
the exact redline and the exact email that produced it — reviewing a rubric criterion
without its evidence is not review.

Anti-gaming carries over unchanged: derived concepts are checked against the
adversarial suite's standard (a keyword-stuffed submission without a valid anchor
citation must score ≤ 0) before a package is accepted.

### 3.6 Stage 6 — Anonymization and synthesis

De-identification is table stakes and is not sufficient. Three layers:

1. **Entity substitution**, consistently across every file: parties, people,
   affiliates, products, domains, addresses, matter numbers. Consistency matters —
   inconsistent aliasing both breaks the documents and leaks (two aliases for one
   party reveal the substitution map's structure).
2. **Quantity transformation**: monetary caps, notice periods, terms, and dates get
   jittered while **preserving the relationships the rubric depends on**. If the
   issue is "90-day notice versus the playbook's 30", the compiled matter needs two
   numbers with the same relation, not the same numbers. Order-preserving,
   relation-preserving, magnitude-plausible.
3. **Distinctive-language rewrite**: the firm's signature drafting is a fingerprint.
   Provisions are re-expressed — a model rewrite, lawyer-reviewed — so the package
   instantiates the same *issue* without reproducing the same *text*. This is also
   what protects the counterparty firm's work product, which is in the corpus too
   and belongs to neither the firm nor its client.

Then a **k-anonymity check** over (practice area, deal shape, party archetypes,
issue set): if fewer than *k* real matters in the corpus share the profile, the
package identifies its source and must not be emitted. A "€2.4bn cross-border
semiconductor carve-out with an unusual IP-escrow trigger" is identifiable no matter
how thoroughly names are swapped. `k_threshold` defaults to 5 and is a policy dial
the firm sets, not the vendor.

Two consequences engineers get wrong:

- **Rubric concepts and hidden facts must be rewritten too.** They are text lifted
  from source documents. Anonymizing `documents/` alone leaves the client's language
  sitting in `rubric.yaml`.
- **Reference-trajectory quotes must be regenerated from the emitted text**, after
  anonymization, or the verbatim quote verifier will treat them as fabricated and
  trip the critical gate on the firm's own best example. Order matters: anonymize,
  emit, *then* build `good.jsonl`.

Provenance semantics need a decision (§7, open question 2). `matter.yaml` currently
declares `provenance.synthetic: true`, and `SPEC.md` §11 forbids "recognizable
reconstructed matters". A compiled package is neither purely synthetic nor a
reconstruction if Stage 6 did its job. The proposal is a v0.3 provenance block —

```yaml
provenance:
  synthetic: true            # after full resynthesis; false until then
  derivation: compiled       # authored | compiled | generated
  release: internal          # internal | public  (public requires synthetic: true)
  consent_record: cr-2026-0142
  k_anonymity: 7
  review: { reviewer: "<bar id>", accepted_at: "2026-03-30T00:00:00Z" }
```

— plus a `playbook-lint --profile public` that refuses `release: internal`. The
linter is not modified by this work; this is a specification for the next version.

### 3.7 Stage 7 — Emit

Write the package in exactly the format `playbook_legal.loaders` parses:

- `documents/*.md`, every scoreable provision under a `## X.Y Title` heading, with
  the section token unique per document. Word numbering (whether literal text or
  `numbering.xml`) is **renumbered** on the way out, and the mapping from source
  clause to emitted token is kept in the checkpoint so evidence stays traceable.
- Citations as `<document_id> §<section>`, matching `rewards.RewardEngine`.
- `rubric.yaml` with anchors resolving and unique; no `max_score` (the engine derives
  it); `critical_failure_score_cap` set.
- `hidden_facts.client_answers` keyed to every rubric question id.
- `matter.yaml` with `matter_id` carrying **no client name** (e.g.
  `firm_tech_txn_0142`), `constraints` calibrated to the real work (a partner who
  read nine documents and asked the client three questions gives real budgets), the
  project canary (`playbook_legal.lint.CANARY`, required verbatim by the linter),
  and a **firm-specific second canary** in provenance. The firm canary is the leak
  detector: if it ever appears in a public model's output, firm data escaped.

Correspondence is emitted as its own document (§4) so the mail is *in the gym*
rather than only in the pipeline.

### 3.8 Stage 8 — Validate and replay

Two gates, both mechanical:

1. `playbook-lint` with zero errors.
2. **Replay the partner's own work.** The DMS history log (which documents were
   opened, in what order), the real client questions, the candidate issues, the
   actual inserted redline text, and the closing email become a `good.jsonl`. It
   must replay to ≥ 0.7 normalized with no critical failure — the same bar CI holds
   the public matters to.

This is the calibration loop, and it is the only automatic check on Stage 5: **if
the partner's actual work scores badly against the derived rubric, the rubric is
wrong, not the partner.** A low replay score sends the package back to Stage 5 with
the failing criteria attached. It also produces the honest negative examples —
earlier turns that were later reverted become `bad_*.jsonl`.

### 3.9 Failure-mode register

| Failure | Detection | Response |
| --- | --- | --- |
| Privilege contamination (adverse-party or non-consented material in a cluster) | participant-domain classification, consent register join, cluster confidence | reject the cluster; alert; never "filter and continue" |
| Two matters merged into one cluster | client-matter number disagreement, participant-graph disconnection | reject; require manual re-clustering |
| Version-chain gaps | unmatched insertions, executed-vs-draft divergence, duplicate version numbers | emit `VersionChain.gaps`; degrade to single-redline matter; never interpolate |
| Metadata-cleaned redlines (`w:author` = "Author") | author cardinality of 1 across a whole document | fall back to the inbound original; else drop attribution-dependent severity signals |
| Accepted-before-save redlines | tracked changes absent but versions differ | diff path via `paragraph_views()` |
| OCR'd or image-only PDFs (executed sets, signature pages) | no text layer; OCR confidence scores | never anchor a rubric issue or a verifiable quote on OCR'd text — the quote verifier is exact-match and OCR noise manufactures fabrication failures. Re-key by hand or exclude |
| Negotiation by phone | edits with no correspondence within the window | mark `rationale: unrecovered`; lawyer supplies or the issue is dropped |
| Model hallucinating a rubric issue | every element must carry `evidence_ids` | auto-reject uncited proposals; lawyer review |
| Anonymization leak | k-anonymity check, distinctive-n-gram scan against the source corpus, canary scan | block emit |
| Derived rubric gameable | run the adversarial suite against the new package | block emit |

---

## 4. Email inside the gym

### 4.1 What works today: the `correspondence` document type

No runtime change is needed. `loaders._parse_sections` addresses any `## <token>`
heading, so a thread renders as one section per message:

```markdown
# Matter Correspondence

## 3.1 From: A. Okafor — Re: Acme MSA — training rights

**From:** A. Okafor <aokafor@northstar.example>
**To:** D. Whitfield <dwhitfield@firm.example>
**Date:** 2026-03-02T09:12:00Z
**Subject:** Acme MSA — training rights

Dana — can the provider train on our data? Procurement needs an answer.
```

The token is `<thread>.<message>`, so one document holds several threads and every
message is independently citable — `emails §3.1` — in `required_citations`, or even
as an issue `anchor`. `compiler.correspondence.render_document()` produces this;
`tests/test_compiler.py` asserts round-tripping through the real `load_documents()`.

Two mechanical guarantees the renderer provides, both tested: section tokens are
unique (the linter rejects reuse), and a quoted Markdown heading inside a message
body cannot forge a new section (leading `#` runs are escaped). Without the second,
any counterparty who pastes a numbered clause into an email silently corrupts the
document's section map.

What this unlocks *now*, with zero engine changes:

- **Issues anchored in correspondence.** "The client's 3 March email states training
  is non-negotiable; §4.2 as drafted contradicts it" — an issue whose
  `required_citations` span a contract provision and an email.
- **Fact-finding realism.** Some facts should be discoverable by *reading* rather
  than by spending client-question budget, which is exactly the tradeoff junior
  lawyers get wrong.
- **Instruction fidelity.** `documents/instructions.md` is already a stylized email;
  the real one, rendered, is better.

### 4.2 Proposed for v0.3: `read_email` and `draft_email`

Reading email works through `read_document` today and needs nothing. Drafting does
not exist, and it is the most common actual work product of a transactional
associate — the note to the supervising partner, the markup cover email to opposing
counsel, the question to the client. Proposed additions:

```python
"draft_email": {
    "description": (
        "Draft one email. Recipients are scored: sending client confidences to "
        "opposing counsel is a critical failure."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "email_id":  {"type": "string"},   # agent's own label
            "to":        {"type": "array", "items": {"type": "string"}},
            "cc":        {"type": "array", "items": {"type": "string"}},
            "subject":   {"type": "string"},
            "body":      {"type": "string"},
            "privileged": {"type": "boolean"},
        },
        "required": ["email_id", "to", "subject", "body"],
    },
}
```

`read_email(thread, message?)` is a thin alias over `read_document` that returns a
thread in reply order; it earns its place only if threads become large enough that
section-by-section reading is unnatural.

**Reward contract for a drafted email** — the same deterministic shape as issues and
redlines, so nothing about the scoring philosophy changes:

```yaml
emails:
  - id: partner_update
    recipients:            # role tokens resolved from matter.yaml participants
      required: [supervising_lawyer]
      prohibited: [opposing_counsel, client_business_team]
    required_concepts: ["model training", "24 hours", "supercap", "recommend"]
    prohibited_concepts: ["guarantee", "no risk"]
    base_points: 1.0
    concept_points: 0.5
    recipient_points: 0.5
    critical_failure_patterns:
      - "client (?:will|would) accept"        # revealing the reservation price
      - "our fallback position is"
  - id: counterparty_markup_cover
    recipients:
      required: [opposing_counsel]
      prohibited: []
    required_concepts: ["attached", "revised", "training"]
    critical_failure_patterns:
      - "client (?:is|will be) under (?:a )?deadline"   # leverage disclosure
      - "walk away"
```

Scoring rules, in the existing idiom:

1. **Recipient matching by role, not address.** `matter.yaml` declares participants
   with roles (`supervising_lawyer`, `client_business_team`, `opposing_counsel`,
   `co_counsel`); the reward maps drafted addresses to roles. A required recipient
   missing loses points; a **prohibited recipient present is a critical failure**,
   full stop, capped by `critical_failure_score_cap` exactly like a fabricated quote.
2. **Content by concept matching**, identical to `required_concepts` on issues, with
   the same anti-gaming discipline (content-bearing phrases only).
3. **Privilege-leak patterns** as regexes over the body, evaluated *conditionally on
   the recipient role*: "the client will accept 2x" is correct analysis in a note to
   the partner and a serious error in a note to the other side. This conditionality
   is the whole point and is what a generic "prohibited phrase" list cannot express.
4. **Verbatim quotes** reuse the existing verifier: a quoted contract provision in an
   email is checked against the cited section, so fabrication is gated the same way.
5. **No simulated replies.** `draft_email` produces work product; it does not elicit
   a counterparty response. A simulated counterparty needs a model in the loop,
   which would destroy the determinism guarantee in `SPEC.md` §9. If adversarial
   negotiation is wanted later, it belongs in a separate, explicitly non-deterministic
   environment mode — never in the deterministic reward layer.

Compiled matters supply all of this for free: the real cover email is the reference
`draft_email` action, its recipients are the real role assignment, and the real
"do not tell them about the deadline" instruction is a real `critical_failure_pattern`.

---

## 5. Confidentiality, privilege, and ethics

This section is the reason the compiler is a separate, self-hosted, licensed artifact
rather than a feature of the public repository. It is written to be shown to a
general counsel.

### 5.1 The architectural commitment

**Firm data never leaves the firm's boundary, and no compiled package ever enters
the public repository.** Not "is anonymized before leaving" — does not leave.
Everything below implements that one sentence.

```text
┌──────────────────────── FIRM TENANT / VPC (no egress) ─────────────────────────┐
│                                                                                │
│  Systems of record (READ-ONLY, scoped identity)                                │
│  ┌───────────┐ ┌──────────────┐ ┌───────────┐ ┌────────────────┐               │
│  │ Exchange/ │ │ iManage /    │ │ Practice  │ │ Consent + wall │               │
│  │ Graph     │ │ NetDocuments │ │ mgmt / TE │ │ registry       │               │
│  └─────┬─────┘ └──────┬───────┘ └─────┬─────┘ └───────┬────────┘               │
│        └──────────────┴───────────────┴───────────────┘                        │
│                             │ consent gate (default deny)                      │
│                    ┌────────▼─────────┐                                        │
│                    │ Intake vault     │  write-once, hashed, retention clock   │
│                    └────────┬─────────┘                                        │
│                    ┌────────▼─────────┐   ┌────────────────────────┐           │
│                    │ Compiler stages  │◄──┤ In-tenant model        │           │
│                    │ 1–8 (this repo)  │   │ (local weights or the  │           │
│                    └────────┬─────────┘   │ firm's own no-training │           │
│                             │             │ Azure OpenAI instance) │           │
│                    ┌────────▼─────────┐   └────────────────────────┘           │
│                    │ Lawyer review UI │  accept / edit / reject + ledger       │
│                    └────────┬─────────┘                                        │
│                    ┌────────▼─────────┐   ┌────────────────────────┐           │
│                    │ Internal matter  │──►│ In-tenant training     │           │
│                    │ registry         │   │ (SFT / DPO / GRPO)     │           │
│                    └──────────────────┘   └────────────────────────┘           │
│                                                                                │
│  Egress policy: DENY ALL. No telemetry, no model API, no package upload.       │
└────────────────────────────────────────────────────────────────────────────────┘
            ▲                                            ✗ (no path exists)
            │ signed releases, one direction only                │
   ┌────────┴─────────┐                        ┌─────────────────▼───────────────┐
   │ Public repo:     │                        │ Public gym (GitHub Pages) +     │
   │ engine, linter,  │                        │ Cloudflare trace collector      │
   │ compiler code,   │                        │ — synthetic matters only        │
   │ synthetic matters│                        └─────────────────────────────────┘
   └──────────────────┘
```

Enforcement, not just intention:

- The compiler VPC/subnet has **egress denied** at the network layer. It cannot call
  a model API, a telemetry endpoint, or the trace collector even if some future code
  path tried to.
- The model used in Stage 5 is either local weights or the firm's own tenant-scoped
  deployment under contractual no-training terms. Prompts containing client
  documents are themselves confidential information — this is the exact analysis
  firms already run before using any cloud AI tool.
- The public repository and the firm deployment share **no credentials and no
  storage**. The compiler is code that ships in; packages never ship out.
- The public gym is static assets plus a Cloudflare Worker whose `POST /api/traces`
  is *deliberately anonymous and untrusted* (see `web/worker/README.md`). It exists
  to collect human play on synthetic matters. A firm package placed in the web
  bundle would be published to the internet; a firm trace uploaded to the collector
  would be stored outside the firm on infrastructure the firm has not diligenced.
  Both are prevented structurally (separate deployments, no shared build), and
  detectably (the firm canary, plus a CI check that every public matter declares
  `provenance.synthetic: true`).
- The firm canary is the tripwire in the other direction: a distinct per-deployment
  string in every compiled package means any leak into a public corpus — or into a
  public model's output — is attributable and provable.

### 5.2 Consent and outside-counsel guidelines

Default deny. A matter enters the corpus only if the consent register says so, and
the register is populated by human review of:

- the **engagement letter** and any data-handling addendum;
- the client's **OCGs**, which increasingly (2023–2026) contain explicit provisions
  on AI use, restrict use of client materials to the matter, prohibit third-party
  access without consent, and require destruction or return at matter close. An OCG
  that says "materials may be used solely in connection with the Matter" is
  dispositive: that client's matters are out absent specific consent;
- any protective order, NDA, common-interest agreement, or clean-team protocol,
  which bind independently of the client's own wishes;
- **legal hold** status — matters under hold are excluded, full stop.

The register is keyed by client-matter number and joined at Stage 0. Consent is
per-client, revocable, and time-stamped. Practical note that must be said out loud:
**revocation cannot un-train a model.** Deleting the package and the vault copy is
achievable; extracting a client's contribution from an already-trained adapter is
not. Therefore consent must be obtained *before* training, the corpus composition of
every trained adapter must be recorded, and the honest remedy for revocation is
retraining without that client. Any vendor claiming otherwise is wrong.

### 5.3 Privilege, confidentiality, and the applicable rules

- **Model Rule 1.6(a)** — no revealing information relating to the representation
  without informed consent. The compiler is engineered so that no revealing occurs:
  processing happens inside the firm, and the emitted artifact is resynthesized.
  Consent is still obtained, because 1.6(a)'s scope is broader than "disclosure to
  the public" and because clients care.
- **Model Rule 1.6(c)** — reasonable efforts to prevent unauthorized access.
  Comment [18]'s factors (sensitivity, likelihood of disclosure absent safeguards,
  cost, difficulty, effect on the representation) map directly onto the topology
  above: in-boundary processing, egress denial, least-privilege scoped identities,
  encryption, access logging, retention limits.
- **Model Rule 1.9(c)** — most of the corpus is *closed* matters, so former-client
  duties govern: no use of information relating to the former representation to that
  client's disadvantage, and no revealing it, except as the Rules permit or when the
  information has become generally known. Training an internal model to negotiate
  better is not obviously adverse to a former client — but the analysis must be
  documented per client rather than assumed, and this is precisely the kind of
  question a GC will ask first.
- **Model Rules 5.1 and 5.3** — the compiler is nonlawyer assistance; a lawyer
  supervises it and owns its output. Stage 5's mandatory review, with the acceptance
  ledger, is the mechanism.
- **Rule 1.7 / ethical walls** — the compiler must run under an identity subject to
  the same wall enforcement as a human. A tenant-wide application permission that
  reads every mailbox is a wall breach dressed as an integration; §2.1's Application
  Access Policy scoping is the mitigation, and matter-level allowlisting is better.
- **Work product and third-party rights** — the redlines from opposing counsel are
  *their* work product, and joint-defense or common-interest materials carry
  third-party privilege that the firm's client cannot waive alone. Threads with an
  adverse party present get privilege review before use; common-interest material is
  excluded by default.
- **ABA Formal Opinions 477R** (securing communication) and **483** (breach
  obligations) frame the security posture and the notification duty if the vault is
  ever compromised — which is a reason to keep the vault small, hashed, and on a
  retention clock rather than accumulating a firm-wide shadow corpus.
- **Non-US**: EU/UK firms add GDPR Article 6 lawful basis and Article 9 for special
  categories, purpose limitation (the deal file was collected to do the deal), and a
  DPIA. Personal data of individuals mentioned in the documents is in scope even
  when the client consents — the client cannot consent for them, which is another
  independent argument for Stage 6 being real synthesis rather than masking.

### 5.4 Why the open repository must stay synthetic

Beyond the confidentiality argument, there are two research arguments:

1. **Benchmark integrity.** Public matters carry a contamination canary so that
   leakage into training corpora is detectable. That machinery only works if the
   public set is publishable in the first place.
2. **Credibility.** The moment a public matter is suspected of being a real deal in
   costume, every result built on the benchmark is contestable. "All public matters
   are synthetic, and here is the linter that enforces it" is a much stronger claim
   than any assurance about anonymization quality.

---

## 6. Phasing and commercial shape

### Phase A — buildable now, zero firm access (partially done)

- ✅ `compiler/redline_miner.py` — OOXML tracked-changes extraction, stdlib only,
  tested against an in-memory `.docx` with nested revisions.
- ✅ `compiler/correspondence.py` — email threads as Playbook documents, verified
  against the real section parser and `load_documents()`.
- ✅ `compiler/phase_a_selftest.py` — fabricated tracked-change version chains and
  correspondence for `ai_saas_001`, scoped Stage 2–7 recovery adapters, and real
  Stage 8 lint/replay validation.
- Next, still with no firm data:
  - the substantive/conforming **edit classifier** with rules plus a small labelled
    set drawn from synthetic redlines;
  - the emitter and the `--profile public|internal` lint proposal;
  - the `correspondence` document type in one public matter, and the `draft_email`
    action behind a v0.3 flag with its own adversarial tests.

#### Phase A known-answer self-test

`compiler/phase_a_selftest.py` now performs the cheapest falsifiable test of the
compiler thesis against `ai_saas_001`. It generates ten structurally valid `.docx`
files (a clean v1 and tracked-change v2 for each of five issues) plus five fabricated
partner-to-associate messages. It then:

1. orders each two-file chain using synthetic DMS version metadata (Stage 2);
2. extracts the actual OOXML revisions with `redline_miner`, including intake-hash
   verification (Stage 3);
3. mines anchor, severity, and required concepts from the fabricated correspondence
   record (Stage 4);
4. makes a deterministic rubric proposal with an evidence id on every field and
   compares it with the hand-authored rubric (Stage 5);
5. applies an identity resynthesis adapter that refuses non-synthetic inputs and
   emits the already-fictional source package (Stages 6–7); and
6. runs the production linter and replays `examples/ai_saas_001/good.jsonl` through
   `PlaybookEnv` (Stage 8).

Reproduce it from the repository root:

```bash
python -m compiler.phase_a_selftest --work-dir /tmp/playbook-phase-a --json
```

Known-answer scorecard (2026-08-02, deterministic):

| Measure | Recovered | Hand-authored | Recovery |
| --- | ---: | ---: | ---: |
| Issues | 5 | 5 | 100% |
| Severities | 5 | 5 | 100% |
| Required concepts | 18 | 18 | 100% |
| Redline concepts | 11 | 11 | 100% |
| All concepts | 29 | 29 | 100% |

The emitted package has zero lint errors; its reference trajectory scores **0.9375**
with **no critical failure**. These numbers establish that the evidence format can
carry the known answer and that the package/replay boundary works. They do **not**
measure generalization: the generator deliberately encodes a labelled synthetic
record, the Stage 2–7 adapters understand only that published format, and Stage 6 is
an identity operation because the input is already fictional. The production
functions in `compiler/pipeline.py` therefore remain honest stubs pending a
design-partner corpus and lawyer review.

### Phase B — needs a design-partner firm

Read-only Graph and DMS connectors; the consent register; Stages 1–2 on real data;
the lawyer review UI; one compiled matter validated end to end. The acceptance test
is blunt and behavioural: **hand the compiled matter to two of the firm's own
associates and ask whether it reads like a real matter and whether the rubric
reflects how the firm actually negotiates.** A second test: does a model that trains
on the firm's compiled matters beat one trained on the synthetic set, *on the firm's
own held-out matters*? That is the number that justifies the whole programme.

Design-partner selection matters more than the code: a firm with iManage (clean
version chains), Exchange Online, a single dominant practice area, and a
KM/innovation function that already owns precedent projects.

### Phase C — scale

A practice group's five-year corpus; a firm-specific benchmark (score any model
against *your* standards — this is a product on its own, before any training
happens); in-tenant adapter training; per-practice-area held-out sets.

### Commercial shape

- **Open source (AGPL-3.0-only), forever**: the environment, reward engine, linter,
  schemas, exporters, the synthetic matters, the public gym — and the compiler's
  format-level code (the redline miner and the correspondence type). The engine's
  credibility *is* the moat's foundation; a closed benchmark convinces no one.
- **Commercially licensed** (see `COMMERCIAL-LICENSING.md`): the compiler
  distribution — connectors, consent registry, anonymization and k-anonymity
  tooling, the review UI, deployment support. Priced per firm, deployed in the
  firm's tenant, no data-sharing clause in either direction. The AGPL is doing real
  work here rather than being decorative: a firm running a *modified* Playbook as a
  network service inherits source-availability obligations, and firms that want
  proprietary connectors or an AGPL exception take the commercial license. Note that
  a purely internal, non-networked deployment triggers neither — the commercial
  license is bought for the connectors, the consent tooling, and the indemnity, not
  to unlock the engine.
- **Buyer**: the KM / practice-innovation / legal-ops function, sponsored by a
  practice-group head who wants the group's standards enforced consistently. Not IT,
  though IT and the GC both hold a veto — which is why §5 exists in this much detail.
- **Non-goals**: not an e-discovery platform, not a DMS, not a drafting assistant.
  The compiler produces training and evaluation environments. Its output is a matter
  package, and its buyer should be able to read one.

---

## 7. Open questions for the owner

1. **Where does the reference trajectory's authority come from?** Stage 8 treats the
   partner's actual work as `good.jsonl` and uses a low replay score as evidence the
   *rubric* is wrong. That is a strong assumption: partners are inconsistent, some
   matters were handled badly, and outcomes reflect leverage as much as skill.
   Alternatives: require a second reviewer to certify the matter as exemplary before
   compiling; weight by outcome (did the position survive to execution?); or accept
   only matters where a post-closing review exists. This choice determines whether
   compiled matters are *gold* or merely *typical*, and everything downstream
   inherits it.

2. **How synthetic must a compiled matter be — and what does `provenance` say?**
   The `synthetic: true` flag and `SPEC.md` §11 currently assume authored matters.
   A compiled-then-resynthesized package needs its own vocabulary, a lint profile,
   and a defensible threshold for "no longer a recognizable reconstruction". The
   k-anonymity framing in §3.6 is a proposal, not an answer, and it is the thing a
   client's GC will interrogate hardest.

3. **What is the minimum viable corpus, and does the value survive anonymization?**
   Nobody knows how many compiled matters are needed to beat the synthetic set, or
   whether Stage 6's rewriting destroys the very specificity that made the firm's
   data valuable. Cheapest way to find out before any firm access: run Phase A's
   synthetic evidence-bundle generator, compile the twelve public matters *back* from
   fabricated artifact trails, and measure how much of the hand-authored rubric the
   pipeline recovers. If the compiler cannot recover a rubric it was given the
   evidence for, no amount of real data will help.
