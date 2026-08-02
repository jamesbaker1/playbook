"""Gymnasium adapter: PlaybookEnv as a text-in / text-out gymnasium.Env.

Language-agent convention: observations and actions are JSON strings. The action
string must parse to one structured action dict; unparseable actions are passed
through as an unknown action (penalized by the environment, never crashing the
loop). Install with the ``gym`` extra: ``pip install "playbook-legal[gym]"``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

try:
    import gymnasium
    from gymnasium import spaces
except ImportError as exc:  # pragma: no cover - exercised only without the extra
    raise ImportError(
        "PlaybookGymEnv needs gymnasium: pip install 'playbook-legal[gym]'"
    ) from exc

from .env import PlaybookEnv

_MAX_TEXT = 2**20


class PlaybookGymEnv(gymnasium.Env):
    metadata: ClassVar[dict[str, Any]] = {"render_modes": ["ansi"]}

    def __init__(self, matter_dir: str | Path) -> None:
        super().__init__()
        self._env = PlaybookEnv.from_directory(matter_dir)
        self.observation_space = spaces.Text(max_length=_MAX_TEXT)
        self.action_space = spaces.Text(max_length=_MAX_TEXT)

    def reset(
        self, *, seed: int | None = None, options: dict[str, Any] | None = None
    ) -> tuple[str, dict[str, Any]]:
        super().reset(seed=seed)
        observation, info = self._env.reset(seed=seed)
        return json.dumps(observation, ensure_ascii=False), info

    def step(self, action: str) -> tuple[str, float, bool, bool, dict[str, Any]]:
        try:
            parsed = json.loads(action)
            if not isinstance(parsed, dict):
                parsed = {"type": "invalid"}
        except (json.JSONDecodeError, TypeError):
            parsed = {"type": "invalid"}
        observation, reward, terminated, truncated, info = self._env.step(parsed)
        return (
            json.dumps(observation, ensure_ascii=False),
            float(reward),
            terminated,
            truncated,
            info,
        )

    def render(self) -> str:
        last = self._env.trace[-1].observation["last_result"] if self._env.trace else {}
        return json.dumps(last, ensure_ascii=False, indent=2)

    def episode_result(self) -> dict[str, Any]:
        return self._env.episode_result()
