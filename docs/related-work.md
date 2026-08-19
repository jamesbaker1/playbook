# Related work

Playbook is a gym for multi-step transactional legal work: an agent reads a matter,
spends a budget of client questions, flags anchor-cited issues, proposes redlines,
escalates what exceeds its authority, and negotiates against a deterministic scripted
counterparty, scored by deterministic verifiers with critical-failure gates.

This page is the map of the work Playbook builds on and the work it sits next to —
what each system does, in its own terms, and the one specific way Playbook differs.
It is maintained as a public record; the survey behind it was run in August 2026 and
the page is current as of 2026-08-19. Where a finding rests on secondary reporting,
it says so. Where we are asserting an absence, we say "no system we found," because a
literature sweep can establish what we saw and not what exists.

## Closest systems

### Harvey Legal Agent Benchmark (LAB)

The [Legal Agent Benchmark](https://www.harvey.ai/blog/introducing-harveys-legal-agent-benchmark)
launched 2026-05-06 and is open-source (MIT) at
[github.com/harveyai/harvey-labs](https://github.com/harveyai/harvey-labs). It contains
1,200+ multi-step agentic legal tasks (the repository now advertises up to 1,671) across
24 practice areas, each pairing a loose partner-style instruction with a closed universe
of matter documents and a deliverable graded against 75,000+ expert-written binary
rubric criteria. Grading is all-pass — no partial credit — and the
[initial results](https://www.harvey.ai/blog/legal-agent-benchmark-initial-results)
report frontier models completing well under a fifth of tasks. The
[In-House Contracting extension](https://www.harvey.ai/blog/legal-agent-benchmark-in-house-contracting)
(June 12, 2026) adds 500 tasks covering client playbooks, redline response, issues
lists, and escalation of non-standard terms; the
[M&A extension](https://www.harvey.ai/blog/legal-agent-bench-m-and-a-due-diligence)
(July 17, 2026) adds synthetic multi-thousand-document diligence environments. A
leaderboard on a private held-out set is reportedly hosted by Vals AI; we have not
independently characterized how that held-out set is governed. Harvey's own materials
name interactive benchmarks and autonomous negotiation as future work as of June 2026.

**Difference:** LAB tasks are single-output snapshots graded by an LLM judge applying
expert rubrics, where a Playbook episode is an interactive loop scored by deterministic
verifiers and re-checkable by replaying the trace.

### Crosby × micro1 RedlineBench

[RedlineBench](https://www.micro1.ai/benchmark/crosby-micro1-redlinebench) was announced
2026-06-17, with the dataset published on
[HuggingFace](https://huggingface.co/datasets/crosbylegal/RedlineBench/blob/main/README.md)
(CC-BY-4.0 data, MIT code) and results at
[intelligence.crosby.ai/benchmark](https://intelligence.crosby.ai/benchmark/). It runs
140 tasks across three multi-turn MSA negotiation scenarios — two SaaS MSAs and one
professional-services MSA — over four alternating turns, with side-specific client
playbooks and asymmetric information; from turn two onward a task presents the
counterparty's tracked-changes redline. Scoring uses attorney-authored weighted rubrics
(−10 to +10) applied by a three-model LLM judge panel across five dimensions, with
attorney golden redlines held back in a verifier layer. Reported frontier scores fall
in the 44–51% range. It is the closest published system to Playbook's negotiation core,
and the earliest such benchmark we found.

**Difference:** RedlineBench's counterparty turns are pre-scripted static snapshots and
scoring is LLM-judge, where Playbook's counterparty is a live engine that responds to
the moves the agent actually makes and every score is reproducible from the trace.

### Mercor APEX-Agents

[APEX-Agents](https://www.mercor.com/blog/introducing-apex-agents/)
([arXiv 2601.14242](https://arxiv.org/abs/2601.14242)) launched in January 2026 with 480
long-horizon agentic tasks — 160 of them corporate law, validated by Harvey — set inside
33 simulated work "worlds" averaging over 160 files each, spanning email, chat,
spreadsheets, a file system, and code execution. Tasks are graded against expert rubrics
under all-pass LLM-judge scoring, released openly (CC-BY) with the Archipelago harness,
and frontier models complete under a quarter of them. Its most relevant result for
Playbook is downstream: Applied Compute
[post-trained an open model](https://www.appliedcompute.com/case-studies/mercor) on
roughly 2,000 expert dev-set cases to reach the top of the corporate-law leaderboard
(Pass@1 26.6%), with reported transfer to GDPval — an eval corpus turned into training
signal in corporate law. Mercor has since written about
[scaling that data pipeline](https://www.mercor.com/blog/scaling-data-apex-agents/).

**Difference:** APEX-Agents sells and scores completed work products through an LLM
judge with no counterparty and no environment API for training, where Playbook exposes a
Gymnasium-shaped interface with SFT/DPO/GRPO scaffolds and scores interaction, not just
output.

## Methodological ancestors

**tau-bench / tau2-bench (Sierra).** [tau2-bench](https://github.com/sierra-research/tau2-bench)
is the reference design for policy-constrained interactive agent evaluation: a
tool-using agent converses with a simulated user under a written policy, and success is
checked deterministically against final database state. Playbook is, in shape, tau-bench
applied to transactional legal work, with negotiation and rubric-gated deliverables
added. The one part it does not inherit is the simulated user: tau-bench's LLM-simulated
user is a documented reliability weakness, analyzed in 2026 critiques such as
[arXiv 2601.17087](https://arxiv.org/abs/2601.17087). Playbook's counterparty is a
deterministic script rather than a model, which is a direct answer to that critique —
the same seed and the same actions produce the same counterparty behavior every run.

**TERMS-Bench (Stanford).** [TERMS-Bench](https://arxiv.org/abs/2605.13909)
([site](https://terms-bench.github.io/)) frames Bayesian-game negotiation so that the
environment itself is the verifier: a fixed stochastic simulator plays the counterpart,
episodes are seed-reproducible, and performance is measured as a gap from an oracle
optimum. It is independent support for the reproducibility argument behind a scripted
counterparty. Its subject is price bargaining — no documents, playbooks, redlines,
citations, or professional-duty constraints — so it is an ancestor of the mechanism
rather than of the content.

**SWE-Gym.** [SWE-Gym](https://github.com/SWE-Gym/SWE-Gym) is the clearest precedent for
the environment-to-training path Playbook is built for: a training environment for
software-engineering agents, with executable tasks whose verification comes from running
code rather than from a judge, used to produce trained models rather than only
leaderboard rows. Playbook borrows the lineage — deterministic verification first, then
trajectories, then training — and changes the domain.

**DLawBench.** [DLawBench](https://arxiv.org/abs/2606.13931) (June 2026) evaluates client
elicitation directly: the model must draw out the facts from a simulated client across
several personality types before it can answer well. It establishes elicitation as a
scorable mechanic in legal consultation. Playbook's budgeted client questions are the
same mechanic moved into deal execution, where every question spends a fixed budget and
is matched by concept against a rubric.

**LegalSim.** [LegalSim](https://arxiv.org/abs/2510.03405) (October 2025) trains agents
with PPO inside a simulation of litigation procedure. It is prior art for reinforcement
learning inside a legal environment, and the reason Playbook makes no claim to that
category. The domain is adversarial procedure rather than transactional drafting and
negotiation.

**LawFlow.** [LawFlow](https://arxiv.org/abs/2504.18942)
([code](https://github.com/minnesotanlp/LawFlow)) studies how legal work is actually
executed end to end — collecting and comparing human and model workflows on a complete
task rather than on isolated questions. It is a useful precedent for the premise that
the *process* of legal work, not just the final answer, is the object worth measuring.

## The rubric wave and static legal benchmarks

Single-turn legal evaluation is well covered, and expert-written rubrics are now
standard practice rather than a differentiator. [LegalBench](https://arxiv.org/abs/2308.11462)
established the collaboratively built, task-decomposed legal reasoning suite, alongside
earlier work such as [SARA](https://arxiv.org/abs/2005.05257),
[LexGLUE](https://arxiv.org/abs/2110.00976), and [LawBench](https://arxiv.org/abs/2309.16289),
and contract-specific datasets including [CUAD](https://arxiv.org/abs/2103.06268),
[MAUD](https://arxiv.org/abs/2301.00876), [ContractNLI](https://arxiv.org/abs/2110.01799),
and [ACORD](https://arxiv.org/abs/2501.06582). [LegalAgentBench](https://arxiv.org/abs/2412.17259)
([ACL](https://aclanthology.org/2025.acl-long.116/)) put "legal agent benchmark" into the
literature in 2024. The 2026 rubric wave —
[PLawBench](https://aclanthology.org/2026.acl-long.458/),
[LexRubric](https://arxiv.org/abs/2606.09389),
[LEGIT](https://aclanthology.org/2026.acl-long.150/), and
[Scale's PRBench-Legal](https://arxiv.org/abs/2511.11562)
([leaderboard](https://labs.scale.com/leaderboard/prbench-legal)) — converges on atomic,
expert-authored criteria applied by an LLM judge to a single response.
[GDPval](https://openai.com/index/gdpval/) (OpenAI, September 2025) does the same for
one-shot occupational deliverables across professions including law, graded by experts,
and names interactivity as future work.

Two things follow for Playbook. First, rubric scoring is not a contribution we claim;
what we claim about scoring is that the gates are deterministic and the result is
recomputable from a trace. Second, the training thesis has support from inside this
wave: LEGIT reports that rubric-derived reward is usable for reinforcement learning,
which is the same argument Playbook makes for a rubric-scored interactive environment.
On corpus governance, the sealed held-out split follows the institutional-benchmarking
argument set out in [PNAS](https://www.pnas.org/doi/10.1073/pnas.2509757122). The
critique that static benchmarks miss what lawyering actually involves is likewise not
ours — it is argued directly in
["Legal Reasoning Is Not Lawyering"](https://arxiv.org/abs/2606.23716) and in Harvey's
own framing of LAB.

## What Playbook claims, exactly

Claims Playbook does **not** make, and who owns the prior art:

- **"First legal agent benchmark."** [LegalAgentBench](https://arxiv.org/abs/2412.17259)
  (2024) and [Harvey LAB](https://www.harvey.ai/blog/introducing-harveys-legal-agent-benchmark)
  (2026) own that phrase.
- **"First multi-turn legal negotiation benchmark."**
  [RedlineBench](https://www.micro1.ai/benchmark/crosby-micro1-redlinebench) (June 2026)
  shipped multi-turn MSA negotiation with side-specific playbooks first.
- **"First interactive legal environment."** Interactive legal environments predate
  Playbook, including [LegalWorld / LongJud-Bench](https://arxiv.org/abs/2606.18728)
  (June 2026) in the litigation setting.
- **"First RL environment in law."** [LegalSim](https://arxiv.org/abs/2510.03405) trained
  agents with PPO inside litigation procedure in 2025, and an open
  [legal-negotiation RL environment](https://medium.com/@gandharvmahin11/teaching-language-models-to-negotiate-an-rl-environment-for-real-legal-contracts-8361e043d245)
  with a deterministic multi-component reward was published from an OpenEnv hackathon in
  May 2026.
- **"Rubric scoring is novel."** [PLawBench](https://aclanthology.org/2026.acl-long.458/),
  [LexRubric](https://arxiv.org/abs/2606.09389),
  [LEGIT](https://aclanthology.org/2026.acl-long.150/), and
  [PRBench-Legal](https://arxiv.org/abs/2511.11562) are the standard, and Harvey LAB's
  75,000+ binary criteria are the largest published instance.
- **"Static benchmarks miss legal work" as an original critique.** That argument is made
  in ["Legal Reasoning Is Not Lawyering"](https://arxiv.org/abs/2606.23716) and in
  Harvey's own launch materials.

Component precedents for individual mechanics, stated so the composition claim below is
readable: client elicitation is demonstrated by [DLawBench](https://arxiv.org/abs/2606.13931)
in consultation and by [TheAgentCompany](https://arxiv.org/abs/2412.14161) in software
work; environment-as-verifier negotiation is demonstrated by
[TERMS-Bench](https://arxiv.org/abs/2605.13909); escalation of non-standard terms appears
as a task type in Harvey's contracting extension; autonomous contract negotiation exists
as a production system in
[Luminance](https://www.luminance.com/press/luminance-enhances-the-legal-industrys-only-100-ai-autonomous-contract-negotiation-tool-to-show-the-why-behind-every-decision-and-opens-it-to-the-entire-enterprise/),
which is a commercial actor rather than a reproducible evaluation environment.

The claim we do make is a claim about composition:

> As of August 2026, we found no system that combines a live deterministic counterparty,
> deterministic critical-failure gates, replay-verifiable traces, budgeted client
> questions, and RL trainability on transactional legal work.

Three qualifications belong with it. The composition is the claim — every component
listed above has a 2026 precedent somewhere, and several have better-resourced
implementations than ours. The statement is bounded by what we searched: "no system we
found," never "nothing exists." And it is dated, because in this area a survey ages in
months; if a system we missed satisfies the combination, the honest response is to edit
this page.

## Corrections

If a system here is described inaccurately, credited to the wrong work, or missing
entirely, please open an issue. Corrections to this page are treated as bug reports
against the project's public claims, and are fixed the same way.
