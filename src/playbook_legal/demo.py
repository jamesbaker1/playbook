from __future__ import annotations

import json
from pathlib import Path

from .env import PlaybookEnv


def scripted_actions() -> list[dict]:
    return [
        {"type": "read_document", "document_id": "instructions", "section": "1"},
        {"type": "read_document", "document_id": "msa", "section": "4.2"},
        {"type": "read_document", "document_id": "playbook", "section": "3"},
        {
            "type": "ask_client",
            "question_id": "q_sensitive_data",
            "question": "Will the service process regulated or sensitive personal data?",
        },
        {
            "type": "ask_client",
            "question_id": "q_launch_deadline",
            "question": "Is there a fixed launch deadline affecting negotiation leverage?",
        },
        {
            "type": "submit_issue",
            "issue_id": "data_training",
            "title": "Provider model-training right exceeds client position",
            "severity": "high",
            "citations": ["msa §4.2", "playbook §3"],
            "analysis": (
                "The provider may use Customer Data and Outputs to train generalized models. "
                "The client playbook permits only aggregated usage analytics and requires an "
                "express prohibition on training with Customer Data or Outputs."
            ),
            "recommendation": "Delete the training right and preserve only aggregated analytics.",
        },
        {
            "type": "propose_redline",
            "issue_id": "data_training",
            "document_id": "msa",
            "section": "4.2",
            "replacement_text": (
                "Provider may use aggregated and de-identified usage analytics solely to operate "
                "and improve the Service, but shall not use Customer Data or Outputs to train, "
                "fine-tune, or develop any generalized artificial intelligence model."
            ),
            "rationale": "Implements the preferred playbook position while retaining analytics.",
        },
        {"type": "read_document", "document_id": "dpa", "section": "5.1"},
        {"type": "read_document", "document_id": "playbook", "section": "4"},
        {
            "type": "submit_issue",
            "issue_id": "incident_notice",
            "title": "Security incident notice is too slow",
            "severity": "high",
            "citations": ["dpa §5.1", "playbook §4"],
            "analysis": (
                "The DPA allows notice within 72 hours after confirmation, while the playbook "
                "requires notice without undue delay and no later than 24 hours after discovery."
            ),
            "recommendation": "Require notice within 24 hours after discovery.",
        },
        {
            "type": "propose_redline",
            "issue_id": "incident_notice",
            "document_id": "dpa",
            "section": "5.1",
            "replacement_text": (
                "Provider shall notify Customer without undue delay and in no event later than "
                "24 hours after discovering any Security Incident."
            ),
            "rationale": "Aligns incident timing with the client playbook.",
        },
        {"type": "read_document", "document_id": "msa", "section": "10.2"},
        {"type": "read_document", "document_id": "playbook", "section": "5"},
        {
            "type": "submit_issue",
            "issue_id": "liability_cap",
            "title": "Single low cap applies to core data and IP risks",
            "severity": "high",
            "citations": ["msa §10.2", "playbook §5"],
            "analysis": (
                "The fees-paid cap covers confidentiality, data-security, and IP indemnity claims. "
                "The playbook requires a higher supercap for those exposures."
            ),
            "recommendation": "Add a two-times-fees supercap for the specified claims.",
        },
        {
            "type": "propose_redline",
            "issue_id": "liability_cap",
            "document_id": "msa",
            "section": "10.2",
            "replacement_text": (
                "The general cap is fees paid in the prior 12 months; provided that liability "
                "arising from breach of confidentiality, a Security Incident, or Provider's IP "
                "indemnification obligations is capped at two times such fees."
            ),
            "rationale": "Creates the required supercap for heightened exposures.",
        },
        {"type": "read_document", "document_id": "dpa", "section": "9.2"},
        {
            "type": "submit_issue",
            "issue_id": "dpa_precedence",
            "title": "DPA lacks effective precedence over conflicting MSA terms",
            "severity": "medium",
            "citations": ["dpa §9.2", "playbook §6"],
            "analysis": (
                "The DPA says the MSA controls in a conflict, which can defeat negotiated data "
                "protections. The DPA should control for privacy and security subject matter."
            ),
            "recommendation": "Reverse the precedence rule for DPA subject matter.",
        },
        {"type": "read_document", "document_id": "msa", "section": "12.1"},
        {
            "type": "submit_issue",
            "issue_id": "auto_renewal",
            "title": "Automatic renewal requires operational calendaring",
            "severity": "medium",
            "citations": ["msa §12.1", "playbook §7"],
            "analysis": (
                "The agreement renews automatically unless notice is given 90 days before expiry. "
                "The playbook prefers 30 days and requires escalation if the business accepts more."
            ),
            "recommendation": "Reduce notice to 30 days or calendar and escalate the 90-day date.",
        },
        {
            "type": "submit_final",
            "summary": (
                "The principal issues are unrestricted provider training on Customer Data and "
                "Outputs, delayed incident notice, inadequate liability treatment for data and IP "
                "exposures, adverse DPA precedence, and a long renewal notice period. The launch "
                "deadline limits leverage, so the first three points should be treated as signature "
                "conditions and the renewal point can be managed operationally if necessary."
            ),
        },
    ]


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    matter_dir = repo_root / "matters" / "ai_saas_001"
    env = PlaybookEnv.from_directory(matter_dir)
    observation, _ = env.reset(seed=7)
    print(json.dumps(observation["matter"], indent=2))

    for action in scripted_actions():
        _, reward, terminated, truncated, info = env.step(action)
        print(f"step={len(env.trace):02d} action={action['type']:<18} reward={reward:>5.2f}")
        if terminated or truncated:
            break

    result = env.episode_result()
    print("\nRESULT")
    print(json.dumps(result, indent=2))
    path = env.save_trace(repo_root / "artifacts" / "demo_trajectory.json")
    print(f"\nTrace written to {path}")


if __name__ == "__main__":
    main()
