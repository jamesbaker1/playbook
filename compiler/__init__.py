# SPDX-License-Identifier: AGPL-3.0-only

"""Playbook matter compiler — turn a firm's own deal record into matter packages.

Self-hosted by design: this package never ships firm data anywhere. It reads a
private corpus inside the firm's boundary and emits Playbook matter packages in the
format ``playbook_legal`` already loads, lints, and scores.

Working today: :mod:`compiler.redline_miner` (Word tracked changes),
:mod:`compiler.correspondence` (email threads as Playbook documents), and the
publishable known-answer experiment in :mod:`compiler.phase_a_selftest`. Everything
in :mod:`compiler.pipeline` remains a typed production stub. Design:
``docs/matter-compiler.md``.
"""

from __future__ import annotations

__all__ = ["correspondence", "phase_a_selftest", "pipeline", "redline_miner"]

# Submodules are imported on demand (``from compiler import redline_miner``) so that
# ``python -m compiler.redline_miner`` runs the CLI without a double-import warning.
