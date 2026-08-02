"""Baseline runner: let any OpenAI-compatible chat model play a Playbook matter.

The environment's actions are presented as native tool calls, so any model with
function calling can play without a bespoke prompt protocol. The client is
injectable, which keeps the runner testable without network access and lets the
same code target OpenAI, vLLM, Ollama, or any other compatible endpoint via
``base_url``.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .env import PlaybookEnv
from .schemas import tool_definitions

SYSTEM_PROMPT = (
    "You are a technology-transactions lawyer working a matter inside the Playbook "
    "environment. Each user message is the current environment observation as JSON. "
    "Respond with EXACTLY ONE tool call per turn choosing your next action. Ground every "
    "issue in provisions you have actually read, cite the operative provision first, "
    "reproduce quotations verbatim, ask the client only questions that could change the "
    "negotiating position, and finish with submit_final before the step budget runs out. "
    "Follow the observation's 'protocol' rules exactly."
)

_STATIC_KEYS = ("action_schemas", "protocol")


def _slim(observation: dict[str, Any], *, keep_static: bool) -> dict[str, Any]:
    """Drop the static contract keys from repeat observations to save tokens."""
    if keep_static:
        return observation
    return {key: value for key, value in observation.items() if key not in _STATIC_KEYS}


def run_episode(
    env: PlaybookEnv,
    client: Any,
    *,
    model: str,
    seed: int = 0,
    temperature: float = 0.2,
    max_protocol_retries: int = 2,
) -> dict[str, Any]:
    """Run one full episode with a chat model driving the environment."""
    observation, _ = env.reset(seed=seed)
    tools = tool_definitions()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(_slim(observation, keep_static=True), ensure_ascii=False),
        },
    ]
    protocol_failures = 0
    terminated = truncated = False

    while not (terminated or truncated):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            temperature=temperature,
        )
        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None) or []

        if not tool_calls:
            protocol_failures += 1
            if protocol_failures > max_protocol_retries:
                action: dict[str, Any] = {"type": "submit_final", "summary": message.content or ""}
                observation, _, terminated, truncated, _ = env.step(action)
                break
            messages.append({"role": "assistant", "content": message.content or ""})
            messages.append(
                {"role": "user", "content": "Respond with exactly one tool call for your next action."}
            )
            continue

        call = tool_calls[0]
        try:
            arguments = json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError:
            protocol_failures += 1
            arguments = {}
        action = {"type": call.function.name, **arguments}
        observation, _, terminated, truncated, _ = env.step(action)

        messages.append(
            {
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    {
                        "id": getattr(call, "id", "call_0"),
                        "type": "function",
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        },
                    }
                ],
            }
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": getattr(call, "id", "call_0"),
                "content": json.dumps(_slim(observation, keep_static=False), ensure_ascii=False),
            }
        )

    result = env.episode_result()
    result["protocol_failures"] = protocol_failures
    return result


def build_client(base_url: str | None, api_key: str | None) -> Any:
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - exercised only without extra installed
        raise SystemExit(
            "The baseline runner needs the 'openai' package: pip install 'playbook-legal[baselines]'"
        ) from exc
    return OpenAI(base_url=base_url, api_key=api_key or "not-needed")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a chat model against one matter.")
    parser.add_argument("matter", type=Path, help="Path to a matter directory")
    parser.add_argument("--model", default=os.environ.get("PLAYBOOK_MODEL", "gpt-4o-mini"))
    parser.add_argument(
        "--base-url",
        default=os.environ.get("PLAYBOOK_BASE_URL") or os.environ.get("OPENAI_BASE_URL"),
        help="OpenAI-compatible endpoint; defaults to the official API",
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--trace", type=Path, default=Path("artifacts/baseline_trace.json"))
    args = parser.parse_args()

    client = build_client(args.base_url, os.environ.get("OPENAI_API_KEY"))
    env = PlaybookEnv.from_directory(args.matter)
    result = run_episode(env, client, model=args.model, seed=args.seed, temperature=args.temperature)
    env.save_trace(args.trace)
    print(json.dumps(result, indent=2))
    print(f"Trace: {args.trace}")


if __name__ == "__main__":
    main()
