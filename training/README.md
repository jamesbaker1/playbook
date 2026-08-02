# Training plan

Do not begin with online RL. Use this sequence:

1. Establish base-model results on private held-out matters.
2. Generate and legally review strong trajectories.
3. Export trajectories with `export_sft.py`.
4. Train a LoRA adapter with supervised fine-tuning.
5. Generate multiple rollouts and retain high-scoring, critical-error-free trajectories.
6. Build chosen/rejected pairs and run DPO.
7. Adversarially test the reward function.
8. Connect the environment-owned episode reward to GRPO.

A prompt-only GRPO dataset should contain the initial matter prompt plus a matter identifier.
The rollout integration should instantiate a fresh environment for every completion, parse
tool actions, execute them, and return `env.episode_result()["normalized_score"]`.

Keep the training and private evaluation matters disjoint by document structure, not merely
party names.
