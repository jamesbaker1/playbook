from __future__ import annotations

import json
import random
from copy import deepcopy
from pathlib import Path
from typing import Any

from .loaders import load_documents, load_yaml
from .models import ActionType, TraceEvent
from .rewards import RewardEngine
from .schemas import PROTOCOL, action_schemas


class PlaybookEnv:
    """A deterministic, partially observable legal-agent environment."""

    def __init__(
        self,
        *,
        matter_dir: Path,
        matter: dict[str, Any],
        rubric: dict[str, Any],
        hidden_facts: dict[str, Any],
        documents: dict[str, dict[str, Any]],
    ) -> None:
        self.matter_dir = matter_dir
        self.matter = matter
        self.rubric = rubric
        self.hidden_facts = hidden_facts
        self.documents = documents
        self.reward_engine = RewardEngine(rubric, documents)
        self._rng = random.Random()
        self._has_reset = False
        self._terminated = False
        self._truncated = False
        self._step_count = 0
        self._last_result: dict[str, Any] = {}
        self._learned_facts: dict[str, Any] = {}
        self._issue_submissions: list[dict[str, Any]] = []
        self._redline_submissions: list[dict[str, Any]] = []
        self.trace: list[TraceEvent] = []

    @classmethod
    def from_directory(cls, matter_dir: str | Path) -> PlaybookEnv:
        path = Path(matter_dir)
        matter = load_yaml(path / "matter.yaml")
        rubric = load_yaml(path / "rubric.yaml")
        hidden_facts = load_yaml(path / "hidden_facts.yaml")
        documents = load_documents(path, matter.get("documents", []))
        return cls(
            matter_dir=path,
            matter=matter,
            rubric=rubric,
            hidden_facts=hidden_facts,
            documents=documents,
        )

    @property
    def max_steps(self) -> int:
        return int(self.matter.get("constraints", {}).get("maximum_steps", 30))

    @property
    def max_client_questions(self) -> int:
        return int(self.matter.get("constraints", {}).get("maximum_client_questions", 5))

    def reset(self, *, seed: int | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        self._rng.seed(seed)
        self._has_reset = True
        self._terminated = False
        self._truncated = False
        self._step_count = 0
        self._last_result = {"message": "Matter opened."}
        self._learned_facts = deepcopy(self.matter.get("public_facts", {}))
        self._issue_submissions = []
        self._redline_submissions = []
        self.trace = []
        self.reward_engine.reset()
        observation = self._observation()
        return observation, {"matter_id": self.matter["matter_id"], "seed": seed}

    def step(
        self, action: dict[str, Any]
    ) -> tuple[dict[str, Any], float, bool, bool, dict[str, Any]]:
        if not self._has_reset:
            raise RuntimeError("Call reset() before step().")
        if self._terminated or self._truncated:
            raise RuntimeError("Episode is complete. Call reset() to begin another episode.")

        self._step_count += 1
        reward = 0.0
        info: dict[str, Any] = {}

        try:
            action_type = ActionType(str(action.get("type")))
        except ValueError as exc:
            reward = -0.5
            self._last_result = {"error": f"Unknown action type: {action.get('type')}"}
            info["error"] = str(exc)
        else:
            handler = getattr(self, f"_handle_{action_type.value}")
            reward, info = handler(action)

        if self._step_count >= self.max_steps and not self._terminated:
            self._truncated = True
            self._last_result = {
                "error": "Step budget exhausted.",
                "maximum_steps": self.max_steps,
            }

        observation = self._observation()
        event = TraceEvent(
            step=self._step_count,
            action=deepcopy(action),
            observation=deepcopy(observation),
            reward=reward,
            terminated=self._terminated,
            truncated=self._truncated,
            info=deepcopy(info),
        )
        self.trace.append(event)
        return observation, reward, self._terminated, self._truncated, info

    def episode_result(self) -> dict[str, Any]:
        return self.reward_engine.result(
            terminated=self._terminated,
            truncated=self._truncated,
            steps=self._step_count,
            matter_id=self.matter["matter_id"],
        )

    def save_trace(self, path: str | Path) -> Path:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "matter": self.matter["matter_id"],
            "events": [
                {
                    "step": event.step,
                    "action": event.action,
                    "observation": event.observation,
                    "reward": event.reward,
                    "terminated": event.terminated,
                    "truncated": event.truncated,
                    "info": event.info,
                }
                for event in self.trace
            ],
            "result": self.episode_result(),
        }
        destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return destination

    def _handle_read_document(self, action: dict[str, Any]) -> tuple[float, dict[str, Any]]:
        document_id = str(action.get("document_id", ""))
        section = action.get("section")
        document = self.documents.get(document_id)
        if document is None:
            self._last_result = {"error": f"Unknown document: {document_id}"}
            return -0.2, {"valid": False}
        if section:
            content = document["sections"].get(str(section))
            if content is None:
                self._last_result = {
                    "error": f"Section {section} not found in {document_id}",
                    "available_sections": sorted(document["sections"]),
                }
                return -0.1, {"valid": False}
        else:
            content = document["text"]
        self._last_result = {
            "document_id": document_id,
            "section": section,
            "content": content,
        }
        return 0.0, {"valid": True}

    def _handle_search_matter(self, action: dict[str, Any]) -> tuple[float, dict[str, Any]]:
        query = str(action.get("query", "")).strip().lower()
        if len(query) < 3:
            self._last_result = {"error": "Search query must contain at least three characters."}
            return -0.1, {"valid": False}
        hits: list[dict[str, str]] = []
        for document_id, document in self.documents.items():
            for section, content in document["sections"].items():
                if query in content.lower():
                    hits.append(
                        {
                            "document_id": document_id,
                            "section": section,
                            "snippet": self._snippet(content, query),
                        }
                    )
        self._last_result = {"query": query, "hits": hits[:20], "hit_count": len(hits)}
        return 0.0, {"valid": True, "hit_count": len(hits)}

    def _handle_ask_client(self, action: dict[str, Any]) -> tuple[float, dict[str, Any]]:
        if self.reward_engine.state.questions_asked_total >= self.max_client_questions:
            self._last_result = {"error": "Client-question budget exhausted."}
            return -0.5, {"valid": False}
        question = str(action.get("question", "")).strip()
        if not question:
            self._last_result = {"error": "ask_client requires a 'question'."}
            return -0.25, {"valid": False}
        reward, reward_info, matched_id = self.reward_engine.score_question(question)
        answer = None
        if matched_id is not None:
            answer = self.hidden_facts.get("client_answers", {}).get(matched_id)
        if answer is None:
            self._last_result = {
                "question": question,
                "answer": (
                    "The client has no responsive information beyond the matter file."
                ),
            }
            return reward, {"valid": False, "reward": reward_info}
        self._learned_facts[matched_id] = answer
        self._last_result = {"question": question, "answer": answer}
        return reward, {"valid": True, "reward": reward_info}

    def _handle_submit_issue(self, action: dict[str, Any]) -> tuple[float, dict[str, Any]]:
        required = ["issue_id", "title", "severity", "citations", "analysis", "recommendation"]
        missing = [field for field in required if field not in action]
        if missing:
            self._last_result = {"error": "Missing issue fields.", "missing": missing}
            return -0.25, {"valid": False}
        reward, reward_info = self.reward_engine.score_issue(action)
        self._issue_submissions.append(deepcopy(action))
        # Scoring detail stays harness-side (info/trace); the agent-visible
        # observation only acknowledges receipt, so the rubric cannot be probed.
        self._last_result = {"message": "Issue submitted.", "issue_id": action["issue_id"]}
        return reward, {"valid": True, "reward": reward_info}

    def _handle_propose_redline(self, action: dict[str, Any]) -> tuple[float, dict[str, Any]]:
        required = ["issue_id", "document_id", "section", "replacement_text", "rationale"]
        missing = [field for field in required if field not in action]
        if missing:
            self._last_result = {"error": "Missing redline fields.", "missing": missing}
            return -0.25, {"valid": False}
        document_id = str(action["document_id"])
        section = str(action["section"])
        if document_id not in self.documents or section not in self.documents[document_id]["sections"]:
            self._last_result = {"error": "Redline target does not exist."}
            return -0.75, {"valid": False}
        reward, reward_info = self.reward_engine.score_redline(action)
        self._redline_submissions.append(deepcopy(action))
        self._last_result = {"message": "Redline submitted.", "issue_id": action["issue_id"]}
        return reward, {"valid": True, "reward": reward_info}

    def _handle_submit_final(self, action: dict[str, Any]) -> tuple[float, dict[str, Any]]:
        summary = str(action.get("summary", ""))
        reward, reward_info = self.reward_engine.score_final(summary)
        self._terminated = True
        self._last_result = {"message": "Final work product submitted."}
        return reward, {"valid": True, "reward": reward_info, "result": self.episode_result()}

    def _observation(self) -> dict[str, Any]:
        return {
            "matter": {
                "matter_id": self.matter["matter_id"],
                "title": self.matter["title"],
                "practice_area": self.matter["practice_area"],
                "role": self.matter["role"],
                "assignment": self.matter["assignment"],
            },
            "documents": [
                {
                    "id": document_id,
                    "title": document["title"],
                    "sections": sorted(key for key in document["sections"] if key != "full"),
                }
                for document_id, document in self.documents.items()
            ],
            "protocol": dict(PROTOCOL),
            "action_schemas": action_schemas(),
            "budgets": {
                "steps_remaining": max(0, self.max_steps - self._step_count),
                "client_questions_remaining": max(
                    0,
                    self.max_client_questions
                    - self.reward_engine.state.questions_asked_total,
                ),
            },
            "learned_facts": deepcopy(self._learned_facts),
            "submitted_issue_ids": [item["issue_id"] for item in self._issue_submissions],
            "submitted_redline_issue_ids": [item["issue_id"] for item in self._redline_submissions],
            "last_result": deepcopy(self._last_result),
        }

    @staticmethod
    def _snippet(text: str, query: str, radius: int = 100) -> str:
        lower = text.lower()
        index = lower.find(query)
        if index < 0:
            return text[: radius * 2]
        start = max(0, index - radius)
        end = min(len(text), index + len(query) + radius)
        return text[start:end].replace("\n", " ")
