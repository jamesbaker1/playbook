# Playbook dataset manifest v1

`playbook-dataset` writes three deterministic JSONL views and `manifest.json`.
The manifest is the reproducibility and contamination-control record for a dataset
build; it is not by itself approval to train.

## Hash contract

- Every input trace, registry, and output view is hashed with SHA-256 over its emitted bytes.
- Every JSONL record carries a SHA-256 content hash over its canonical JSON excluding the
  hash field itself.
- Logical filenames, never absolute machine paths, identify inputs and outputs.
- Rebuilding from identical bytes and arguments produces identical output and manifest bytes.
- A nonempty output directory is never overwritten.

## Family lineage

The registry assigns every matter to exactly one family and split. Generated families
also carry `template_sha256`, the canonical hash of the seed package and reference
trajectory. Registry validation rejects a template hash assigned to more than one split,
even when its family and matter identifiers have been renamed. When a sealed registry is
published, sealed families are to expose only identifiers, content hashes, template
lineage, and split—never matter contents. The mechanism exists and is tested
(`sealed_matter_hashes` in `src/playbook_legal/dataset.py`), but no sealed registry
artifact ships yet; one is published only when the private corpus clears review.

## Manifest fields

- `schema_version` and `generator_version` identify the format and builder.
- `registry`, `inputs`, and `outputs` provide logical paths, counts, and byte hashes.
- `provenance` records source, license or consent basis, reviewer, and review status.
- `inclusion_policy` records the enforced prompt, registry, and held-out-data rules.
- `statistics` records episode, critical-failure, family, split, action, and review coverage.

Before an immutable training release, copy the build into controlled storage and add the
reviewer-qualification record, inclusion/exclusion rationale, known limitations, command,
environment lock, and approval record. Live human-trace inboxes are never direct inputs to
training.
