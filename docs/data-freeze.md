# Dataset freeze gate

A dataset build is not approved training data. `playbook-dataset-freeze` promotes a
verified build into a separate content-addressed release only when accompanied by an
approved `playbook.freeze.v1` data card.

The data card must record the release identifier, intended use, exact dataset-manifest
hash, inclusion and exclusion criteria, qualified reviewers, complete episode review
coverage, known limitations, and approval identity/date. The dataset records must already
carry the same reviewer identity and a reviewed or approved status.

For `positive_sft`, the freeze gate rejects held-out splits and every episode with a
critical failure. Preference and evaluation releases preserve failures when their data
cards explicitly identify those uses.

The frozen directory contains the complete dataset build, the exact data-card snapshot,
and a manifest enumerating every file and SHA-256 digest. Re-running
`playbook-dataset-freeze-check` detects any later modification. Release directories are
never overwritten, and live trace inboxes are not accepted as frozen releases.
