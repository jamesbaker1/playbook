"""Playbook matter compiler — turn a firm's own deal record into matter packages.

Self-hosted by design: this package never ships firm data anywhere. It reads a
private corpus inside the firm's boundary and emits Playbook matter packages in the
format ``playbook_legal`` already loads, lints, and scores.

Working today: :mod:`compiler.redline_miner` (Word tracked changes) and
:mod:`compiler.correspondence` (email threads as Playbook documents). Everything in
:mod:`compiler.pipeline` is a typed stub. Design: ``docs/matter-compiler.md``.
"""

from __future__ import annotations

__all__ = ["correspondence", "pipeline", "redline_miner"]

# Submodules are imported on demand (``from compiler import redline_miner``) so that
# ``python -m compiler.redline_miner`` runs the CLI without a double-import warning.
