# Playbook baseline comparison - 12 public matters (dev split), post-revision instrument

| Model | Episodes | Score | Critical rate | Citation validity | Issue recall | Question recall | Unsupported/ep | Steps | Completion | Critical 95% CI |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Expert reference (replay) | 12 | 0.985 | 0.000 | 1.000 | 0.917 | 0.958 | 0.000 | 22.600 | 1.000 | - |
| Qwen2.5-32B-Instruct | 12 | 0.076 | 0.333 | 1.000 | 0.208 | 0.000 | 0.917 | 8.500 | 1.000 | [0.083, 0.583] |
| Qwen2.5-14B-Instruct | 36 | 0.142 | 0.306 | 1.000 | 0.320 | 0.007 | 0.417 | 8.300 | 1.000 | [0.111, 0.528] |
| Qwen2.5-7B-Instruct | 36 | 0.034 | 0.083 | 0.944 | 0.103 | 0.039 | 0.833 | 9.600 | 0.972 | [0.000, 0.222] |

Pooled means over all episodes per model; 32B pools a single seed. Critical-failure CI is a 95% cluster bootstrap resampled by matter family. Measured on the post-revision instrument; not comparable to results/v0.4.0.

Protocol failures (turns that returned no usable tool call, pooled per row): Expert reference (replay) 0, Qwen2.5-32B-Instruct 3, Qwen2.5-14B-Instruct 1, Qwen2.5-7B-Instruct 3.
