# Playbook scorecard — Qwen/Qwen2.5-7B-Instruct

Split: `dev`

| Matter | Score | Issue recall | Question recall | Citation validity | Redlines | Unsupported | Critical | Steps |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ai_saas_001 | 0.147 | 0.200 | 0.250 | 1.000 | 0.333 | 0 | no | 8 |
| clean_msa_009 | 0.220 | 0.000 | 0.000 | 1.000 | 1.000 | 1 | no | 7 |
| cloud_msa_002 | 0.000 | 0.000 | 0.000 | 0.500 | 0.000 | 2 | no | 14 |
| fintech_vendor_007 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | 1 | no | 6 |
| health_saas_006 | 0.000 | 0.000 | 0.000 | 0.500 | 0.000 | 1 | no | 7 |
| ml_services_005 | 0.002 | 0.200 | 0.000 | 1.000 | 0.000 | 0 | no | 10 |
| msa_provider_004 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | 1 | no | 7 |
| nego_saas_010 | 0.000 | 0.333 | 0.000 | 1.000 | 1.000 | 3 | yes | 25 |
| private_acquisition_buyer_012 | 0.038 | 0.250 | 0.000 | 1.000 | 0.000 | 0 | no | 6 |
| public_merger_target_011 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | 1 | no | 15 |
| saas_renewal_003 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | 1 | no | 8 |
| source_license_008 | 0.000 | 0.000 | 0.000 | 1.000 | 0.000 | 1 | no | 7 |

## Aggregate

```json
{
  "episodes": 12,
  "normalized_score": 0.0339,
  "raw_score": -1.6243,
  "issue_recall": 0.0819,
  "required_issue_recall": 0.1528,
  "unsupported_issue_count": 1.0,
  "citation_validity": 0.9167,
  "question_recall": 0.0208,
  "questions_asked": 1.5,
  "escalation_recall": 0.6667,
  "over_escalation_count": 0.6667,
  "redline_completion": 0.1944,
  "settled_issue_ratio": 0.75,
  "trap_counter_exposure_count": 0.0833,
  "trap_counter_acceptance_count": 0.0,
  "fabricated_quote_count": 0.0833,
  "steps": 10.0,
  "critical_failure_free_rate": 0.9167,
  "critical_failure_rate": 0.0833,
  "completion_rate": 1.0
}
```
