# Playbook

**Train legal agents on the work, not just the law.**

Playbook is an open environment for evaluating and training AI agents on realistic,
multi-step legal work. An agent receives a matter file, client facts, documents,
professional instructions, and a negotiation playbook. It must inspect the record,
ask limited questions, identify material issues, propose work product, and submit a
final answer. The environment scores the agent's actions against deterministic checks
and expert-authored rubrics.

This repository is a runnable **v0.1 vertical slice**. It includes one synthetic
customer-side AI SaaS contract-review matter, a stateful environment, a deterministic
reward engine, trajectory logging, tests, and export utilities for supervised fine-tuning.

## Why the package is called `playbook-legal`

The public project name is **Playbook**. The `playbook` and `playbooks` package names are
already occupied on PyPI, so this starter uses the distribution name `playbook-legal`
and the Python import namespace `playbook_legal`.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
python -m playbook_legal.demo
```

The demo runs a transparent scripted agent through the included matter and writes a
complete episode trace to `artifacts/demo_trajectory.json`.

## Core API

```python
from pathlib import Path
from playbook_legal import PlaybookEnv

matter_dir = Path("matters/ai_saas_001")
env = PlaybookEnv.from_directory(matter_dir)
observation, info = env.reset(seed=7)

observation, reward, terminated, truncated, info = env.step({
    "type": "read_document",
    "document_id": "msa",
    "section": "4.2"
})
```

`step()` follows the modern Gymnasium shape:

```text
observation, reward, terminated, truncated, info
```

The core package does not require Gymnasium. A thin adapter can be added after the
language-agent interface stabilizes.

## Included matter

`ai_saas_001` asks the agent to review an AI-enabled SaaS agreement and DPA for a
customer using a client negotiation playbook. The matter tests:

- provider use of customer data and outputs for model training;
- security-incident notification timing;
- limitation-of-liability treatment of confidentiality, data, and IP risks;
- DPA precedence over conflicting agreement terms;
- renewal and termination-management risk;
- targeted client fact gathering;
- citation-grounded issue submission;
- and operative redline drafting.

All matter content is synthetic and intentionally simplified. It is not legal advice.

## Repository map

```text
src/playbook_legal/       Environment, schemas, scoring, trace logging, CLI
matters/ai_saas_001/      First complete synthetic legal matter
examples/                 Agent examples
training/                 SFT export and training-plan scaffolding
tests/                    Unit and end-to-end tests
SPEC.md                    v0.1 technical specification
AUTHORING.md               How to create the next matter
ROADMAP.md                 Four-week build plan
```

## Design principles

1. **Score actions, not prose similarity.**
2. **Separate hidden state from agent observations.**
3. **Use deterministic verifiers wherever possible.**
4. **Treat critical legal failures as gates, not small average penalties.**
5. **Log every action for auditability and training-data generation.**
6. **Keep public evaluation matters separate from private held-out matters.**
7. **Use only synthetic, licensed, or clearly public source materials.**

## Next milestone

The next release should add nine more technology-transactions matters, a model client
simulator constrained by structured hidden state, a baseline runner for local/API models,
and a calibrated human-review workflow for drafting-quality scores.
