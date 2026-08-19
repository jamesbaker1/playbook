# Playbook scorecard — Qwen/Qwen2.5-14B-Instruct

Split: `dev`

| Matter | Score | Issue recall | Question recall | Citation validity | Redlines | Unsupported | Critical | Steps |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ai_saas_001 | 0.109 | 0.200 | 0.000 | 1.000 | 0.333 | 0 | no | 6 |
| clean_msa_009 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 3 | no | 10 |
| cloud_msa_002 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | 1 | no | 6 |
| fintech_vendor_007 | 0.106 | 0.200 | 0.000 | 1.000 | 0.333 | 0 | no | 6 |
| health_saas_006 | 0.023 | 0.200 | 0.000 | 1.000 | 0.333 | 0 | yes | 6 |
| ml_services_005 | 0.289 | 0.400 | 0.000 | 1.000 | 0.333 | 0 | no | 7 |
| msa_provider_004 | 0.442 | 1.000 | 0.000 | 1.000 | 0.333 | 0 | no | 13 |
| nego_saas_010 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 1 | no | 7 |
| private_acquisition_buyer_012 | 0.038 | 0.250 | 0.000 | 1.000 | 0.250 | 0 | yes | 9 |
| public_merger_target_011 | 0.232 | 0.250 | 0.000 | 1.000 | 0.250 | 0 | no | 15 |
| saas_renewal_003 | 0.115 | 0.200 | 0.000 | 1.000 | 0.333 | 0 | yes | 5 |
| source_license_008 | 0.301 | 0.600 | 0.000 | 1.000 | 0.000 | 0 | no | 7 |

## Aggregate

```json
{
  "episodes": 12,
  "normalized_score": 0.138,
  "raw_score": 1.9469,
  "issue_recall": 0.275,
  "required_issue_recall": 0.375,
  "unsupported_issue_count": 0.4167,
  "citation_validity": 1.0,
  "question_recall": 0.0,
  "questions_asked": 0.25,
  "escalation_recall": 0.75,
  "over_escalation_count": 0.25,
  "redline_completion": 0.375,
  "settled_issue_ratio": 0.7708,
  "trap_counter_exposure_count": 0.0,
  "trap_counter_acceptance_count": 0.0,
  "fabricated_quote_count": 0.0833,
  "steps": 8.0833,
  "critical_failure_free_rate": 0.75,
  "critical_failure_rate": 0.25,
  "completion_rate": 1.0
}
```
