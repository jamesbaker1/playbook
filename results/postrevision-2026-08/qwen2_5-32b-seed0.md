# Playbook scorecard — Qwen/Qwen2.5-32B-Instruct

Split: `dev`

| Matter | Score | Issue recall | Question recall | Citation validity | Redlines | Unsupported | Critical | Steps |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ai_saas_001 | 0.258 | 0.400 | 0.000 | 1.000 | 0.667 | 0 | no | 7 |
| clean_msa_009 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 1 | no | 5 |
| cloud_msa_002 | 0.000 | 0.200 | 0.000 | 1.000 | 0.000 | 2 | no | 10 |
| fintech_vendor_007 | 0.000 | 0.200 | 0.000 | 1.000 | 0.000 | 1 | no | 7 |
| health_saas_006 | 0.068 | 0.200 | 0.000 | 1.000 | 0.333 | 0 | yes | 5 |
| ml_services_005 | 0.094 | 0.200 | 0.000 | 1.000 | 0.333 | 1 | no | 10 |
| msa_provider_004 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | 4 | no | 17 |
| nego_saas_010 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 2 | no | 9 |
| private_acquisition_buyer_012 | 0.051 | 0.250 | 0.000 | 1.000 | 0.250 | 0 | yes | 6 |
| public_merger_target_011 | 0.091 | 0.250 | 0.000 | 1.000 | 0.250 | 0 | yes | 11 |
| saas_renewal_003 | 0.182 | 0.400 | 0.000 | 1.000 | 0.333 | 0 | yes | 8 |
| source_license_008 | 0.169 | 0.400 | 0.000 | 1.000 | 0.000 | 0 | no | 7 |

## Aggregate

```json
{
  "episodes": 12,
  "normalized_score": 0.0761,
  "raw_score": 0.7406,
  "issue_recall": 0.2083,
  "required_issue_recall": 0.2708,
  "unsupported_issue_count": 0.9167,
  "citation_validity": 1.0,
  "question_recall": 0.0,
  "questions_asked": 0.25,
  "escalation_recall": 0.6667,
  "over_escalation_count": 0.25,
  "redline_completion": 0.3472,
  "settled_issue_ratio": 0.7986,
  "trap_counter_exposure_count": 0.0,
  "trap_counter_acceptance_count": 0.0,
  "fabricated_quote_count": 0.0833,
  "steps": 8.5,
  "critical_failure_free_rate": 0.6667,
  "critical_failure_rate": 0.3333,
  "completion_rate": 1.0
}
```
