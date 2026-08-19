# Playbook scorecard — Qwen/Qwen2.5-7B-Instruct

Split: `dev`

| Matter | Score | Issue recall | Question recall | Citation validity | Redlines | Unsupported | Critical | Steps |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ai_saas_001 | 0.147 | 0.200 | 0.250 | 1.000 | 0.333 | 0 | no | 7 |
| clean_msa_009 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 1 | no | 7 |
| cloud_msa_002 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | 3 | no | 14 |
| fintech_vendor_007 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | 1 | no | 6 |
| health_saas_006 | 0.070 | 0.200 | 0.000 | 1.000 | 0.333 | 0 | no | 7 |
| ml_services_005 | 0.048 | 0.200 | 0.000 | 1.000 | 0.000 | 0 | no | 7 |
| msa_provider_004 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | 1 | no | 7 |
| nego_saas_010 | 0.000 | 0.000 | 0.333 | 1.000 | 1.000 | 3 | no | 34 |
| private_acquisition_buyer_012 | 0.054 | 0.250 | 0.000 | 1.000 | 0.000 | 0 | no | 9 |
| public_merger_target_011 | 0.025 | 0.250 | 0.000 | 1.000 | 0.000 | 0 | no | 7 |
| saas_renewal_003 | 0.079 | 0.200 | 0.000 | 1.000 | 0.333 | 0 | yes | 6 |
| source_license_008 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | 1 | no | 7 |

## Aggregate

```json
{
  "episodes": 12,
  "normalized_score": 0.0352,
  "raw_score": -0.5201,
  "issue_recall": 0.1083,
  "required_issue_recall": 0.1875,
  "unsupported_issue_count": 0.8333,
  "citation_validity": 1.0,
  "question_recall": 0.0486,
  "questions_asked": 1.3333,
  "escalation_recall": 0.6667,
  "over_escalation_count": 0.5,
  "redline_completion": 0.25,
  "settled_issue_ratio": 0.75,
  "trap_counter_exposure_count": 0.0,
  "trap_counter_acceptance_count": 0.0,
  "fabricated_quote_count": 0.0,
  "steps": 9.8333,
  "critical_failure_free_rate": 0.9167,
  "critical_failure_rate": 0.0833,
  "completion_rate": 0.9167
}
```
