# SPDX-License-Identifier: AGPL-3.0-only

"""Text normalization shared by the reward engine and the critic.

Every content comparison in Playbook — quotation verification, concept matching,
concession-pattern matching — happens on lowercased text with runs of whitespace
collapsed to single spaces. Anything that has to reproduce an engine verdict outside
the engine has to normalize identically, so the rule lives in one place instead of
being restated per module.
"""

from __future__ import annotations


def normalize_text(text: str) -> str:
    """Lowercase ``text`` and collapse every run of whitespace to a single space."""
    return " ".join(str(text).lower().split())
