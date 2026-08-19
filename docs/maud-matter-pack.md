# MAUD-informed M&A matter pack

The matters `public_merger_target_011`, `private_acquisition_buyer_012`, and a
private held-out carve-out/TSA matter (identifier withheld until the sealed
registry is published) are entirely synthetic. No agreement text, annotation
span, party name, or EDGAR language from MAUD is reproduced or required to solve
them. MAUD supplies only an issue taxonomy and aggregate answer frequencies used
to calibrate which counterparty positions are routine, which should draw one round
of resistance, and which make useful near-market traps. Client playbooks and hidden
facts—not prevalence—control the correct answer.

## Sources and method

- The Atticus Project, *Merger Agreement Understanding Dataset (MAUD) v1*,
  <https://www.atticusprojectai.org/maud/> (152 public-target agreements, 92 ABA
  deal-point questions, 47,000+ labels; CC BY 4.0).
- Steven H. Wang et al., *MAUD: An Expert-Annotated Legal NLP Dataset for Merger
  Agreement Understanding*, EMNLP 2023, <https://arxiv.org/abs/2301.00876>.
- Primary data repository, <https://github.com/TheAtticusProject/maud>, and the
  official dataset mirror, <https://huggingface.co/datasets/theatticusproject/maud>.

Counts below were computed on `MAUD_v1/MAUD_train.csv` from the official mirror on
2026-08-02. They are row counts, not estimates of current market practice; repeated
or counterfactual examples in MAUD mean they must not be presented as deal-level
percentages.

| MAUD question / answer | training rows |
| --- | ---: |
| ordinary-course buyer consent: not unreasonably withheld, conditioned or delayed | 200 |
| ordinary-course buyer consent: flat consent | 20 |
| industry-change MAE carveout has disproportionate-impact exception: yes / no | 95 / 19 |
| initial COR match: 4 business days / 5 business days / over 5 business days | 103 / 34 / 23 |
| constructive knowledge / actual knowledge | 112 / 96 |
| constructive knowledge based on inquiry / role | 117 / 8 |
| general antitrust efforts: reasonable best / commercially reasonable / flat | 163 / 126 / 12 |
| specific performance: entitled to / entitled to seek | 202 / 12 |
| general R&W bringdown at MAE standard / other answers | 205 / 5 |

MAUD is based on the ABA 2021 Public Target Deal Points Study. That ABA framing is
used through MAUD only; the private-company indemnity and TSA points are original
teaching scenarios and are not represented as MAUD distributions. CC BY 4.0
attribution applies to the taxonomy and aggregates above. The synthetic matter
text remains governed by this repository's license.

## Matter and gate results

Each matter deliberately mixes contested provisions with compliant controls, so the
agent must review 8–12 deal points without turning every clause into an issue.

| Matter | Split | Deal points | Reference score | Fabricated quote | Reversed redline |
| --- | --- | ---: | ---: | --- | --- |
| `public_merger_target_011` | public dev | 9 | 0.9453 | critical | critical |
| `private_acquisition_buyer_012` | public dev | 11 | 1.0000 | critical | critical |
| A private held-out carve-out/TSA matter (identifier withheld until the sealed registry is published) | private held-out | 12 | reference >0.9 | critical | critical |

All three packages pass `playbook-lint`; all references terminate without a critical
failure. The public and held-out trajectories are stored with their respective
repositories and are replayed by CI.

## Review status

Automated lint, replay, quote-fabrication, and redline-direction gates are recorded
by CI. A practicing M&A lawyer has **not yet reviewed or accepted** the commercial
ladder. Human review remains an explicit release acceptance item; this document
does not substitute automated validation for that judgment.
