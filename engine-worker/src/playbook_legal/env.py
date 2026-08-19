# SPDX-License-Identifier: AGPL-3.0-only

from __future__ import annotations

import json
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

from .loaders import load_documents, load_yaml
from .models import ActionType, TraceEvent
from .rewards import RewardEngine
from .schemas import PROTOCOL, action_schemas

_NEGOTIATION_ACTIONS = ("send_markup", "accept_counterparty")
_DEFAULT_ESCALATION_GUIDANCE = (
    "Noted. Proceed in accordance with the playbook and flag it in your final summary."
)


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
        counterparty: dict[str, Any] | None = None,
    ) -> None:
        self.matter_dir = matter_dir
        self.matter = matter
        self.rubric = rubric
        self.hidden_facts = hidden_facts
        self.documents = documents
        self.counterparty = counterparty or {}
        self.negotiation_enabled = bool(self.counterparty.get("positions"))
        self.reward_engine = RewardEngine(rubric, documents, self.counterparty)
        self._has_reset = False
        self._terminated = False
        self._truncated = False
        self._step_count = 0
        self._last_result: dict[str, Any] = {}
        self._learned_facts: dict[str, Any] = {}
        self._issue_submissions: list[dict[str, Any]] = []
        self._redline_submissions: list[dict[str, Any]] = []
        self._work_product_submissions: list[tuple[str, dict[str, Any]]] = []
        self._escalation_topics: list[str] = []
        self._negotiation_state: dict[str, dict[str, Any]] = {}
        self._negotiation_labels: dict[str, str] = {}
        self._negotiation_rounds_used = 0
        self.trace: list[TraceEvent] = []

    @classmethod
    def from_directory(cls, matter_dir: str | Path) -> PlaybookEnv:
        path = Path(matter_dir)
        matter = load_yaml(path / "matter.yaml")
        rubric = load_yaml(path / "rubric.yaml")
        hidden_facts = load_yaml(path / "hidden_facts.yaml")
        counterparty_path = path / "counterparty.yaml"
        counterparty = load_yaml(counterparty_path) if counterparty_path.exists() else {}
        documents = load_documents(path, matter.get("documents", []))
        return cls(
            matter_dir=path,
            matter=matter,
            rubric=rubric,
            hidden_facts=hidden_facts,
            documents=documents,
            counterparty=counterparty,
        )

    @property
    def max_steps(self) -> int:
        return int(self.matter.get("constraints", {}).get("maximum_steps", 30))

    @property
    def max_client_questions(self) -> int:
        return int(self.matter.get("constraints", {}).get("maximum_client_questions", 5))

    @property
    def max_escalations(self) -> int:
        return int(self.matter.get("constraints", {}).get("maximum_escalations", 2))

    @property
    def max_negotiation_rounds(self) -> int:
        return int(self.matter.get("constraints", {}).get("maximum_negotiation_rounds", 8))

    def action_schemas(self) -> dict[str, dict[str, Any]]:
        """The action contract this matter actually supports."""
        schemas = action_schemas()
        if not self.negotiation_enabled:
            for name in _NEGOTIATION_ACTIONS:
                schemas.pop(name, None)
        return schemas

    def reset(self, *, seed: int | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        self._seed = seed
        self._has_reset = True
        self._terminated = False
        self._truncated = False
        self._step_count = 0
        self._last_result = {"message": "Matter opened."}
        self._learned_facts = deepcopy(self.matter.get("public_facts", {}))
        self._issue_submissions = []
        self._redline_submissions = []
        self._work_product_submissions = []
        self._escalation_topics = []
        self._negotiation_state = {}
        self._negotiation_labels = {}
        self._negotiation_rounds_used = 0
        self.trace = []
        self.reward_engine.reset()
        observation = self._observation()
        self._initial_observation = deepcopy(observation)
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
            if action_type.value in _NEGOTIATION_ACTIONS and not self.negotiation_enabled:
                self._last_result = {
                    "error": f"Action '{action_type.value}' is unavailable on this matter."
                }
                info = {
                    "valid": False,
                    "protocol_error": "negotiation actions require a scripted counterparty",
                }
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
            "seed": self._seed,
            "initial_observation": self._initial_observation,
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
        self.reward_engine.record_document_read(
            document_id, str(section) if section is not None else None
        )
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

    def _handle_escalate(self, action: dict[str, Any]) -> tuple[float, dict[str, Any]]:
        if self.reward_engine.state.escalations_total >= self.max_escalations:
            self._last_result = {"error": "Escalation budget exhausted."}
            return -0.5, {"valid": False}
        topic = str(action.get("topic", "")).strip()
        reason = str(action.get("reason", "")).strip()
        if not topic or not reason:
            self._last_result = {"error": "escalate requires a 'topic' and a 'reason'."}
            return -0.25, {"valid": False}
        reward, reward_info, matched_id = self.reward_engine.score_escalation(topic, reason)
        self._escalation_topics.append(topic)
        guidance = None
        if matched_id is not None:
            guidance = self.hidden_facts.get("escalation_answers", {}).get(matched_id)
        if guidance is None:
            self._last_result = {"topic": topic, "guidance": _DEFAULT_ESCALATION_GUIDANCE}
            return reward, {"valid": False, "reward": reward_info}
        self._learned_facts[matched_id] = guidance
        self._last_result = {"topic": topic, "guidance": guidance}
        return reward, {"valid": True, "reward": reward_info}

    def _handle_submit_issue(self, action: dict[str, Any]) -> tuple[float, dict[str, Any]]:
        required = ["issue_id", "title", "severity", "citations", "analysis", "recommendation"]
        missing = [field for field in required if field not in action]
        if missing:
            self._last_result = {"error": "Missing issue fields.", "missing": missing}
            return -0.25, {"valid": False}
        reward, reward_info = self.reward_engine.score_issue(action)
        self._issue_submissions.append(deepcopy(action))
        self._work_product_submissions.append(("issue", deepcopy(action)))
        # Scoring detail stays harness-side (info/trace); the agent-visible
        # observation only acknowledges receipt, so the rubric cannot be probed.
        self._last_result = {"message": "Issue submitted.", "issue_id": action["issue_id"]}
        return reward, {"valid": True, "reward": reward_info}

    def _handle_revise_issue(self, action: dict[str, Any]) -> tuple[float, dict[str, Any]]:
        required = ["issue_id", "title", "severity", "citations", "analysis", "recommendation"]
        missing = [field for field in required if field not in action]
        if missing:
            self._last_result = {"error": "Missing issue fields.", "missing": missing}
            return -0.25, {"valid": False}
        label = str(action["issue_id"])
        index = next(
            (i for i, item in enumerate(self._issue_submissions) if str(item["issue_id"]) == label),
            None,
        )
        if index is None:
            self._last_result = {"error": "Issue revision target does not exist.", "issue_id": label}
            return -0.25, {"valid": False}
        revised = deepcopy(action)
        self._issue_submissions[index] = revised
        self._replace_work_product("issue", lambda item: str(item["issue_id"]) == label, revised)
        reward = self._rescore_work_products()
        reward_info = {"type": "issue_revision", "criterion": label, "points": round(reward, 4)}
        self._last_result = {"message": "Issue revised.", "issue_id": label}
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
        self._work_product_submissions.append(("redline", deepcopy(action)))
        self._last_result = {"message": "Redline submitted.", "issue_id": action["issue_id"]}
        return reward, {"valid": True, "reward": reward_info}

    def _handle_revise_redline(self, action: dict[str, Any]) -> tuple[float, dict[str, Any]]:
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
        key = (str(action["issue_id"]), document_id, section)
        index = next(
            (
                i
                for i, item in enumerate(self._redline_submissions)
                if (str(item["issue_id"]), str(item["document_id"]), str(item["section"])) == key
            ),
            None,
        )
        if index is None:
            self._last_result = {"error": "Redline revision target does not exist."}
            return -0.25, {"valid": False}
        revised = deepcopy(action)
        self._redline_submissions[index] = revised
        self._replace_work_product(
            "redline",
            lambda item: (
                str(item["issue_id"]), str(item["document_id"]), str(item["section"])
            ) == key,
            revised,
        )
        reward = self._rescore_work_products()
        reward_info = {
            "type": "redline_revision",
            "criterion": key[0],
            "points": round(reward, 4),
        }
        self._last_result = {"message": "Redline revised.", "issue_id": key[0]}
        return reward, {"valid": True, "reward": reward_info}

    def _replace_work_product(
        self,
        kind: str,
        matches: Callable[[dict[str, Any]], bool],
        revised: dict[str, Any],
    ) -> None:
        for index, (item_kind, item) in enumerate(self._work_product_submissions):
            if item_kind == kind and matches(item):
                self._work_product_submissions[index] = (kind, deepcopy(revised))
                return
        raise RuntimeError("Work-product revision target disappeared.")

    def _rescore_work_products(self) -> float:
        previous = self.reward_engine.state.raw_score
        self.reward_engine.clear_work_product_scores()
        for kind, item in self._work_product_submissions:
            if kind == "issue":
                self.reward_engine.score_issue(item)
            else:
                self.reward_engine.score_redline(item)
        return self.reward_engine.state.raw_score - previous

    def _handle_send_markup(self, action: dict[str, Any]) -> tuple[float, dict[str, Any]]:
        if self._negotiation_rounds_used >= self.max_negotiation_rounds:
            self._last_result = {"error": "Negotiation-round budget exhausted."}
            return -0.5, {"valid": False}
        required = ["issue_id", "document_id", "section", "proposed_text"]
        missing = [field for field in required if field not in action]
        if missing:
            self._last_result = {"error": "Missing markup fields.", "missing": missing}
            return -0.25, {"valid": False}

        label = str(action["issue_id"])
        proposed = str(action["proposed_text"])
        target = f"{action['document_id']} §{action['section']}"
        rubric_id = self.reward_engine.state.issue_labels.get(label)
        if rubric_id is None:
            criterion = self.reward_engine.anchor_map.get(target)
            rubric_id = str(criterion["id"]) if criterion else None

        # An unsupported markup still burns a round: sending the wrong paper across
        # the table costs the same negotiating capital as sending the right paper.
        self._negotiation_rounds_used += 1
        if rubric_id is None or rubric_id not in self.reward_engine.issue_map:
            reward, reward_info = self.reward_engine.score_unsupported_markup(
                label, "markup matches no submitted issue label and no operative anchor"
            )
            self._last_result = {
                "error": "That markup does not correspond to an issue you have opened."
            }
            return reward, {"valid": False, "reward": reward_info}
        if rubric_id not in self.reward_engine.positions:
            reward, reward_info = self.reward_engine.score_unsupported_markup(
                label, "the counterparty holds no position on that provision"
            )
            self._last_result = {"error": "The counterparty is not negotiating that provision."}
            return reward, {"valid": False, "reward": reward_info}

        position = self.reward_engine.positions[rubric_id]
        state = self._negotiation_entry(rubric_id, label)
        if state["status"] == "closed":
            reward, reward_info = self.reward_engine.score_settlement(
                rubric_id, proposed, str(state["closed_by"])
            )
            self._last_result = {
                "response": "closed",
                "message": "That point is already closed.",
            }
            return reward, {"valid": False, "reward": reward_info}

        state["rounds_used"] += 1
        acceptable = self._counterparty_accepts(position, proposed)
        counters = list(position.get("counters", []) or [])

        if acceptable and state["rounds_used"] > int(position.get("resist_rounds", 0)):
            message = "Agreed. We will take your language."
            state.update(
                status="closed",
                closed_by="ours",
                closed_text=proposed,
                outstanding_counter=None,
                last_message=message,
            )
            self._last_result = {"response": "accepted", "message": message}
            reward, reward_info = self.reward_engine.score_settlement(rubric_id, proposed, "ours")
            return reward, {"valid": True, "reward": reward_info}

        if state["counters_used"] < len(counters):
            counter = counters[state["counters_used"]]
            state["counters_used"] += 1
            message = str(counter.get("message", ""))
            counter_text = str(counter.get("text", ""))
            state.update(
                outstanding_counter=counter_text,
                last_message=message,
                last_counter_text=counter_text,
            )
            self._last_result = {
                "response": "counter",
                "message": message,
                "counter_text": counter_text,
            }
            reward, reward_info = self.reward_engine.record_counterparty_response(
                rubric_id, "counter"
            )
            return reward, {"valid": True, "reward": reward_info}

        message = str(position.get("reject_message", "We cannot move further on this point."))
        state["last_message"] = message
        self._last_result = {"response": "rejected", "message": message}
        reward, reward_info = self.reward_engine.record_counterparty_response(rubric_id, "reject")
        return reward, {"valid": True, "reward": reward_info}

    def _handle_accept_counterparty(self, action: dict[str, Any]) -> tuple[float, dict[str, Any]]:
        if self._negotiation_rounds_used >= self.max_negotiation_rounds:
            self._last_result = {"error": "Negotiation-round budget exhausted."}
            return -0.5, {"valid": False}
        label = str(action.get("issue_id", ""))
        # Accepting resolves through the agent's own labels only: there is no anchor
        # to fall back on, and an outstanding counter always has a label behind it.
        labels = {**self.reward_engine.state.issue_labels, **self._negotiation_labels}
        rubric_id = labels.get(label)
        state = self._negotiation_state.get(rubric_id) if rubric_id else None
        if state is None or state["status"] == "closed" or not state["outstanding_counter"]:
            self._last_result = {
                "error": "There is no outstanding counterparty proposal on that issue."
            }
            return -0.25, {"valid": False}

        self._negotiation_rounds_used += 1
        counter_text = str(state["outstanding_counter"])
        message = "Accepted on the counterparty's language."
        state.update(
            status="closed",
            closed_by="theirs",
            closed_text=counter_text,
            last_message=message,
        )
        state["rounds_used"] += 1
        self._last_result = {
            "response": "accepted",
            "message": message,
            "accepted_text": counter_text,
        }
        reward, reward_info = self.reward_engine.score_settlement(
            str(rubric_id), counter_text, "theirs"
        )
        return reward, {"valid": True, "reward": reward_info}

    def _negotiation_entry(self, rubric_id: str, label: str) -> dict[str, Any]:
        self._negotiation_labels[label] = rubric_id
        return self._negotiation_state.setdefault(
            rubric_id,
            {
                "status": "open",
                "rounds_used": 0,
                "counters_used": 0,
                "outstanding_counter": None,
                "last_message": None,
                "last_counter_text": None,
                "closed_by": None,
                "closed_text": None,
            },
        )

    @staticmethod
    def _counterparty_accepts(position: dict[str, Any], proposed_text: str) -> bool:
        """A proposal is acceptable if every concept of any accept variant appears."""
        text = " ".join(proposed_text.lower().split())
        for variant in position.get("accept_concepts", []) or []:
            concepts = [" ".join(str(item).lower().split()) for item in variant]
            if concepts and all(concept in text for concept in concepts):
                return True
        return False

    def _handle_submit_final(self, action: dict[str, Any]) -> tuple[float, dict[str, Any]]:
        summary = str(action.get("summary", ""))
        reward, reward_info = self.reward_engine.score_final(summary)
        self._terminated = True
        self._last_result = {"message": "Final work product submitted."}
        return reward, {"valid": True, "reward": reward_info, "result": self.episode_result()}

    def _observation(self) -> dict[str, Any]:
        protocol = dict(PROTOCOL)
        if not self.negotiation_enabled:
            protocol.pop("negotiation", None)
        budgets = {
            "steps_remaining": max(0, self.max_steps - self._step_count),
            "client_questions_remaining": max(
                0,
                self.max_client_questions - self.reward_engine.state.questions_asked_total,
            ),
            "escalations_remaining": max(
                0,
                self.max_escalations - self.reward_engine.state.escalations_total,
            ),
        }
        if self.negotiation_enabled:
            budgets["negotiation_rounds_remaining"] = max(
                0, self.max_negotiation_rounds - self._negotiation_rounds_used
            )
        observation: dict[str, Any] = {
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
            "protocol": protocol,
            "action_schemas": self.action_schemas(),
            "budgets": budgets,
            "learned_facts": deepcopy(self._learned_facts),
            "submitted_issue_ids": [item["issue_id"] for item in self._issue_submissions],
            "submitted_redline_issue_ids": [item["issue_id"] for item in self._redline_submissions],
            "submitted_escalation_topics": list(self._escalation_topics),
            "last_result": deepcopy(self._last_result),
        }
        if self.negotiation_enabled:
            observation["negotiation"] = self._negotiation_view()
        return observation

    def _negotiation_view(self) -> dict[str, dict[str, Any]]:
        """Per-issue negotiation status, keyed by the label the agent used.

        Only what the counterparty has actually said reaches the agent: their
        acceptance thresholds, resistance, undelivered counters, and the settlement
        rubric stay hidden.
        """
        view: dict[str, dict[str, Any]] = {}
        for label, rubric_id in self._negotiation_labels.items():
            state = self._negotiation_state[rubric_id]
            entry: dict[str, Any] = {
                "status": state["status"],
                "rounds_used": state["rounds_used"],
                "last_message": state["last_message"],
                "last_counter_text": state["last_counter_text"],
            }
            if state["status"] == "closed":
                entry["closed_by"] = state["closed_by"]
            view[label] = entry
        return view

    @staticmethod
    def _snippet(text: str, query: str, radius: int = 100) -> str:
        lower = text.lower()
        index = lower.find(query)
        if index < 0:
            return text[: radius * 2]
        start = max(0, index - radius)
        end = min(len(text), index + len(query) + radius)
        return text[start:end].replace("\n", " ")
