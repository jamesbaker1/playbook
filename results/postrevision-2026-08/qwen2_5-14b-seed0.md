# Playbook scorecard — Qwen/Qwen2.5-14B-Instruct

Split: `dev`

| Matter | Score | Issue recall | Question recall | Citation validity | Redlines | Unsupported | Critical | Steps |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| ai_saas_001 | 0.125 | 0.200 | 0.250 | 1.000 | 0.333 | 1 | no | 9 |
| clean_msa_009 | 0.000 | 0.000 | 0.000 | 1.000 | 1.000 | 1 | no | 5 |
| cloud_msa_002 | 0.037 | 0.200 | 0.000 | 1.000 | 0.333 | 1 | no | 9 |
| fintech_vendor_007 | 0.091 | 0.200 | 0.000 | 1.000 | 0.333 | 0 | no | 5 |
| health_saas_006 | 0.159 | 0.200 | 0.000 | 1.000 | 0.333 | 0 | no | 6 |
| ml_services_005 | 0.250 | 0.400 | 0.000 | 1.000 | 0.667 | 0 | yes | 8 |
| msa_provider_004 | 0.462 | 1.000 | 0.000 | 1.000 | 0.000 | 0 | no | 8 |
| nego_saas_010 | 0.000 | 0.333 | 0.000 | 1.000 | 1.000 | 2 | yes | 16 |
| private_acquisition_buyer_012 | 0.054 | 0.250 | 0.000 | 1.000 | 0.250 | 0 | yes | 8 |
| public_merger_target_011 | 0.159 | 0.250 | 0.000 | 1.000 | 0.250 | 0 | no | 9 |
| saas_renewal_003 | 0.108 | 0.200 | 0.000 | 1.000 | 0.333 | 0 | yes | 5 |
| source_license_008 | 0.297 | 0.600 | 0.000 | 1.000 | 0.000 | 0 | no | 6 |

## Aggregate

```json
{
  "episodes": 12,
  "normalized_score": 0.1452,
  "raw_score": 2.2347,
  "issue_recall": 0.3194,
  "required_issue_recall": 0.4236,
  "unsupported_issue_count": 0.4167,
  "citation_validity": 1.0,
  "question_recall": 0.0208,
  "questions_asked": 0.25,
  "escalation_recall": 0.6667,
  "over_escalation_count": 0.0833,
  "redline_completion": 0.4028,
  "settled_issue_ratio": 0.7986,
  "trap_counter_exposure_count": 0.0833,
  "trap_counter_acceptance_count": 0.0833,
  "fabricated_quote_count": 0.0833,
  "steps": 7.8333,
  "critical_failure_free_rate": 0.6667,
  "critical_failure_rate": 0.3333,
  "completion_rate": 1.0
}
```
