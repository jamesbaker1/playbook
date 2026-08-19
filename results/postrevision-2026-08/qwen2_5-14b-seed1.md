# Playbook scorecard — Qwen/Qwen2.5-14B-Instruct

Split: `dev`

| Matter | Score | Issue recall | Question recall | Citation validity | Redlines | Unsupported | Critical | Steps |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ai_saas_001 | 0.234 | 0.400 | 0.000 | 1.000 | 0.333 | 0 | no | 7 |
| clean_msa_009 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 3 | no | 10 |
| cloud_msa_002 | 0.100 | 0.200 | 0.000 | 1.000 | 0.333 | 0 | no | 6 |
| fintech_vendor_007 | 0.091 | 0.200 | 0.000 | 1.000 | 0.333 | 0 | no | 6 |
| health_saas_006 | 0.129 | 0.200 | 0.000 | 1.000 | 0.333 | 0 | no | 6 |
| ml_services_005 | 0.039 | 0.200 | 0.000 | 1.000 | 0.333 | 0 | yes | 6 |
| msa_provider_004 | 0.521 | 1.000 | 0.000 | 1.000 | 0.000 | 0 | no | 8 |
| nego_saas_010 | 0.013 | 0.333 | 0.000 | 1.000 | 1.000 | 2 | no | 12 |
| private_acquisition_buyer_012 | 0.054 | 0.250 | 0.000 | 1.000 | 0.250 | 0 | yes | 12 |
| public_merger_target_011 | 0.250 | 1.000 | 0.000 | 1.000 | 1.000 | 0 | yes | 21 |
| saas_renewal_003 | 0.108 | 0.200 | 0.000 | 1.000 | 0.333 | 0 | yes | 6 |
| source_license_008 | 0.192 | 0.400 | 0.000 | 1.000 | 0.000 | 0 | no | 7 |

## Aggregate

```json
{
  "episodes": 12,
  "normalized_score": 0.1442,
  "raw_score": 2.9986,
  "issue_recall": 0.3653,
  "required_issue_recall": 0.4861,
  "unsupported_issue_count": 0.4167,
  "citation_validity": 1.0,
  "question_recall": 0.0,
  "questions_asked": 0.1667,
  "escalation_recall": 0.6667,
  "over_escalation_count": 0.1667,
  "redline_completion": 0.4375,
  "settled_issue_ratio": 0.8333,
  "trap_counter_exposure_count": 0.0,
  "trap_counter_acceptance_count": 0.0,
  "fabricated_quote_count": 0.1667,
  "steps": 8.9167,
  "critical_failure_free_rate": 0.6667,
  "critical_failure_rate": 0.3333,
  "completion_rate": 1.0
}
```
