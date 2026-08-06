# Playbook baseline comparison — 12 public matters (dev split)

| Model | Episodes | Score | Critical rate | Citation validity | Issue recall | Question recall | Unsupported/ep | Steps | Completion | Critical 95% CI |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Expert reference (replay) | 12 | 0.985 | 0.000 | 1.000 | 0.917 | 0.958 | 0.000 | 22.600 | 1.000 | — |
| Qwen2.5-7B-Instruct | 36 | 0.031 | 0.056 | 0.972 | 0.106 | 0.021 | 1.111 | 11.000 | 0.972 | [0.000, 0.139] |
| Qwen2.5-14B-Instruct | 36 | 0.165 | 0.139 | 1.000 | 0.312 | 0.000 | 0.417 | 8.200 | 1.000 | [0.000, 0.333] |
| Qwen2.5-32B-Instruct | 12 | 0.076 | 0.250 | 1.000 | 0.208 | 0.000 | 0.917 | 8.500 | 1.000 | [0.000, 0.500] |

Pooled means over all episodes per model; 32B pools a single seed. Critical-failure CI is a 95% cluster bootstrap resampled by matter family.
