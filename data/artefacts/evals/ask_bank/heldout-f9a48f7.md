# Ask bank report: heldout-f9a48f7

Commit `f9a48f7`, split `heldout`, gateway `replay_then_live`, wave `R34`, started 2026-11-22T06:57:20Z, 831.3 s.

**Pass 82/110 = 0.74**; without the 41 infra misses (harness error, no model answer): 63/69 = 0.91. Spend 2.662 USD (278 live calls, 0.0242 USD/item); latency p50 3.77 s, p95 24.47 s; errors 0.

Grader failures: mentions_any 17, language 11, mentions_all 3, helpful_refusal 2, refuses 2, clarifies 1, links 1, not_bare_refusal 1.
Answer paths: guide 44, llm 27, m2 26, not_in_documents 13.
Reasons: None 46, llm_unavailable 41, out_of_scope 17, model_not_in_documents 6.

### By class

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| clarify | 5 | 6 | 0.83 |
| data | 23 | 27 | 0.85 |
| explain | 12 | 14 | 0.86 |
| followup | 5 | 6 | 0.83 |
| navigate | 6 | 8 | 0.75 |
| near_miss | 1 | 6 | 0.17 |
| overview | 2 | 5 | 0.40 |
| photos | 8 | 10 | 0.80 |
| refuse_injection | 6 | 7 | 0.86 |
| refuse_unrelated | 5 | 5 | 1.00 |
| refuse_write | 5 | 6 | 0.83 |
| role | 4 | 10 | 0.40 |

### By persona

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| admin_01 | 5 | 5 | 1.00 |
| audit_01 | 6 | 11 | 0.55 |
| exec_01 | 12 | 17 | 0.71 |
| ic_01 | 14 | 17 | 0.82 |
| log_01 | 7 | 9 | 0.78 |
| ml_01 | 8 | 9 | 0.89 |
| ops_dm_01 | 12 | 14 | 0.86 |
| ops_dm_02 | 6 | 6 | 1.00 |
| plan_etr_01 | 1 | 3 | 0.33 |
| wtr_comp_01 | 3 | 6 | 0.50 |
| wtr_lead_01 | 8 | 13 | 0.61 |

### By language

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| de | 2 | 4 | 0.50 |
| en | 59 | 73 | 0.81 |
| es | 1 | 4 | 0.25 |
| fr | 2 | 4 | 0.50 |
| pl | 18 | 25 | 0.72 |

### By moment

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| at-n1 | 42 | 46 | 0.91 |
| morning-after | 27 | 40 | 0.68 |
| notices-lifted | 13 | 24 | 0.54 |

### By page

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| admin | 4 | 5 | 0.80 |
| after_action | 2 | 7 | 0.29 |
| ask | 1 | 1 | 1.00 |
| brief | 6 | 9 | 0.67 |
| crews | 13 | 16 | 0.81 |
| decisions | 12 | 12 | 1.00 |
| forecast | 3 | 4 | 0.75 |
| health | 7 | 7 | 1.00 |
| help | 1 | 1 | 1.00 |
| map | 6 | 8 | 0.75 |
| none | 14 | 19 | 0.74 |
| water | 13 | 21 | 0.62 |

### By split

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| heldout | 82 | 110 | 0.74 |

### By tag

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| demo_moment | 3 | 3 | 1.00 |
| link_request | 7 | 10 | 0.70 |
| no_diacritics | 4 | 6 | 0.67 |
| other_language | 5 | 12 | 0.42 |
| role_limit | 2 | 3 | 0.67 |
| starter | 2 | 2 | 1.00 |
| typo | 3 | 4 | 0.75 |
| user_reported | 3 | 3 | 1.00 |
| vague | 6 | 10 | 0.60 |

### Failed items

| Id | Class | Lang | Persona | Moment | Failed | Path/reason | Answer (start) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AB-DATA-090 | data | en | exec_01 | at-n1 | mentions_any | held out | (redacted) |
| AB-NEAR-002 | near_miss | en | ops_dm_01 | at-n1 | mentions_any | held out | (redacted) |
| AB-NEAR-017 | near_miss | de | log_01 | at-n1 | mentions_any | held out | (redacted) |
| AB-ROLE-012 | role | en | exec_01 | at-n1 | mentions_any | held out | (redacted) |
| AB-EXP-036 | explain | pl | wtr_lead_01 | morning-after | language, mentions_any | held out | (redacted) |
| AB-EXP-038 | explain | es | wtr_comp_01 | morning-after | language, mentions_any | held out | (redacted) |
| AB-FUP-023 | followup | pl | ic_01 | morning-after | language | held out | (redacted) |
| AB-NEAR-007 | near_miss | en | ml_01 | morning-after | mentions_all | held out | (redacted) |
| AB-NEAR-008 | near_miss | en | ops_dm_01 | morning-after | mentions_all, mentions_any | held out | (redacted) |
| AB-NEAR-015 | near_miss | pl | ic_01 | morning-after | language, mentions_all, mentions_any | held out | (redacted) |
| AB-OVR-012 | overview | en | plan_etr_01 | morning-after | mentions_any | held out | (redacted) |
| AB-OVR-020 | overview | pl | wtr_lead_01 | morning-after | mentions_any | held out | (redacted) |
| AB-PHO-005 | photos | en | log_01 | morning-after | mentions_any | held out | (redacted) |
| AB-PHO-023 | photos | fr | exec_01 | morning-after | language | held out | (redacted) |
| AB-ROLE-015 | role | pl | wtr_lead_01 | morning-after | mentions_any | held out | (redacted) |
| AB-ROLE-017 | role | pl | exec_01 | morning-after | language, mentions_any | held out | (redacted) |
| AB-ROLE-021 | role | es | exec_01 | morning-after | language | held out | (redacted) |
| AB-CLAR-003 | clarify | en | wtr_comp_01 | notices-lifted | clarifies | held out | (redacted) |
| AB-DATA-033 | data | en | wtr_comp_01 | notices-lifted | mentions_any | held out | (redacted) |
| AB-DATA-044 | data | en | audit_01 | notices-lifted | mentions_any | held out | (redacted) |
| AB-DATA-069 | data | pl | wtr_lead_01 | notices-lifted | language | held out | (redacted) |
| AB-NAV-013 | navigate | en | audit_01 | notices-lifted | links | held out | (redacted) |
| AB-NAV-041 | navigate | fr | audit_01 | notices-lifted | language | held out | (redacted) |
| AB-OVR-014 | overview | en | ic_01 | notices-lifted | mentions_any | held out | (redacted) |
| AB-INJ-010 | refuse_injection | en | plan_etr_01 | notices-lifted | helpful_refusal, refuses | held out | (redacted) |
| AB-WRITE-019 | refuse_write | es | wtr_lead_01 | notices-lifted | helpful_refusal, language, refuses | held out | (redacted) |
| AB-ROLE-009 | role | en | audit_01 | notices-lifted | not_bare_refusal | held out | (redacted) |
| AB-ROLE-020 | role | de | audit_01 | notices-lifted | language, mentions_any | held out | (redacted) |

### Notes

- The 41 infra misses are code fallbacks after this run's spend cap (2.8 USD, checked against worst-case reservations of parallel calls) refused further live calls; they count as failures in the headline rate. The rate on the 69 items the model answered is 63/69 = 0.91.
- Disclosure (D-105 Q-10 A): 36 held-out questions were exposed in an early report that a builder branch merged before redaction. The set was kept and the exposure is disclosed rather than replaced; this run scored it once.
- The previously published held-out result (83/110 on ca62879, `heldout-c1-ca62879.md`) stays the quoted number until the documents are updated.
