# Training

All GPU work is designed to run on **Modal** (`modal_app.py`) — nothing in this
directory executes automatically, requires local torch, or spends compute without an
explicit `modal run` command.

## Sequence

Do not begin with online RL. Use this order:

1. **Baseline.** Establish base-model results on the public dev matters and the
   private held-out matters: `playbook-bench --runner baseline --model <model>`.
2. **Rollouts.** `python training/generate_rollouts.py` — sample N trajectories per
   matter from an API model (temperature > 0), scored by the environment.
3. **SFT data.** Keep high-scoring, critical-free trajectories; each rollout is
   already exported as a chat record. Concatenate the `.chat.json` files into one
   JSONL. Legally review the important actions before training on them.
4. **SFT.** `modal run training/modal_app.py::sft` — LoRA fine-tune (default
   Qwen2.5-7B-Instruct) on the filtered trajectories (`sft_lora.py`).
5. **Preference pairs.** `python training/build_pairs.py` — chosen/rejected pairs
   within each matter (best clean rollout vs. clearly worse or critical ones).
6. **DPO.** `modal run training/modal_app.py::dpo` (`dpo_lora.py`).
7. **Adversarial reward testing.** `pytest tests/test_adversarial.py` must pass, and
   any new reward-hacking pattern found in rollouts gets a regression test, BEFORE
   any online RL.
8. **GRPO.** `modal run training/modal_app.py::grpo` (`grpo_env_reward.py`) — the
   completion is a full action script; the reward instantiates a fresh environment
   per completion and returns the environment-owned `normalized_score`, so the
   critical-failure cap applies during training by construction.

## Evaluation discipline

- Report every metric in SPEC §10 on the **private held-out matters**
  (the `playbook-private` repository), never only on public dev matters.
- Pre-register the metric you expect to move before each run.
- Keep training and held-out matters disjoint by document structure and defined-term
  vocabulary, not merely party names.
