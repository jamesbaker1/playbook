"""Baseline-runner tests using a fake OpenAI-compatible client (no network)."""

from __future__ import annotations

import json
from types import SimpleNamespace

from conftest import EXAMPLES, MATTERS, replay

from playbook_legal import PlaybookEnv
from playbook_legal.baseline import SYSTEM_PROMPT, run_episode

MATTER = MATTERS / "ai_saas_001"


class FakeClient:
    """Replays a scripted list of responses in OpenAI response shape."""

    def __init__(self, responses: list[SimpleNamespace]) -> None:
        self._responses = list(responses)
        self.requests: list[dict] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        message = self._responses.pop(0)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def tool_call_message(action: dict) -> SimpleNamespace:
    action = dict(action)
    name = action.pop("type")
    return SimpleNamespace(
        content="",
        tool_calls=[
            SimpleNamespace(
                id="call_0",
                function=SimpleNamespace(name=name, arguments=json.dumps(action)),
            )
        ],
    )


def text_message(content: str) -> SimpleNamespace:
    return SimpleNamespace(content=content, tool_calls=None)


def load_good_actions() -> list[dict]:
    lines = (EXAMPLES / "ai_saas_001" / "good.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_fake_model_replaying_good_trajectory_matches_direct_replay() -> None:
    actions = load_good_actions()
    client = FakeClient([tool_call_message(action) for action in actions])
    env = PlaybookEnv.from_directory(MATTER)
    result = run_episode(env, client, model="fake", seed=0)
    direct = replay(MATTER, EXAMPLES / "ai_saas_001" / "good.jsonl")
    assert result["normalized_score"] == direct["normalized_score"]
    assert result["critical_failure"] is False
    assert result["protocol_failures"] == 0
    # Tool schemas were offered on every request.
    assert all("tools" in request for request in client.requests)
    assert all(request["seed"] == 0 for request in client.requests)


def test_seed_is_forwarded_to_every_model_request() -> None:
    actions = load_good_actions()
    client = FakeClient([tool_call_message(action) for action in actions])
    env = PlaybookEnv.from_directory(MATTER)
    run_episode(env, client, model="fake", seed=42)
    assert client.requests
    assert all(request["seed"] == 42 for request in client.requests)


def test_system_prompt_defaults_to_the_baseline_prompt() -> None:
    actions = load_good_actions()
    client = FakeClient([tool_call_message(action) for action in actions])
    env = PlaybookEnv.from_directory(MATTER)
    run_episode(env, client, model="fake", seed=0)
    assert client.requests[0]["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}


def test_system_prompt_override_replaces_the_baseline_prompt() -> None:
    actions = load_good_actions()
    client = FakeClient([tool_call_message(action) for action in actions])
    env = PlaybookEnv.from_directory(MATTER)
    run_episode(env, client, model="fake", seed=0, system_prompt="scaffolded workflow")
    systems = {request["messages"][0]["content"] for request in client.requests}
    assert systems == {"scaffolded workflow"}
    assert SYSTEM_PROMPT not in systems


def test_missing_tool_call_is_nudged_then_recovers() -> None:
    actions = load_good_actions()
    responses = [text_message("Let me think about this matter first.")]
    responses += [tool_call_message(action) for action in actions]
    client = FakeClient(responses)
    env = PlaybookEnv.from_directory(MATTER)
    result = run_episode(env, client, model="fake", seed=0)
    assert result["protocol_failures"] == 1
    assert result["terminated"] is True


def test_persistent_protocol_failure_forces_final() -> None:
    client = FakeClient([text_message("I refuse to use tools.") for _ in range(4)])
    env = PlaybookEnv.from_directory(MATTER)
    result = run_episode(env, client, model="fake", seed=0, max_protocol_retries=2)
    assert result["terminated"] is True
    assert result["protocol_failures"] == 3


def test_malformed_arguments_do_not_crash() -> None:
    broken = SimpleNamespace(
        content="",
        tool_calls=[
            SimpleNamespace(
                id="call_0",
                function=SimpleNamespace(name="search_matter", arguments="{not json"),
            )
        ],
    )
    client = FakeClient([broken, tool_call_message({"type": "submit_final", "summary": "x" * 150})])
    env = PlaybookEnv.from_directory(MATTER)
    result = run_episode(env, client, model="fake", seed=0)
    assert result["terminated"] is True
    assert result["protocol_failures"] == 1
