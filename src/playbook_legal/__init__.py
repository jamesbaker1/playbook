"""Playbook: environments for realistic legal-agent work."""

from .env import PlaybookEnv
from .models import ActionType, EpisodeResult

__all__ = ["ActionType", "EpisodeResult", "PlaybookEnv"]
__version__ = "0.1.0"
