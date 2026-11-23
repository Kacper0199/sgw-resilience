# Ask bank report: heldout-f6-complete

Commit `f9a48f7`, split `heldout`, gateway `replay_then_live`, wave `R34`, started 2026-11-22T06:57:20Z, 831.3 s.

**Pass 109/110 = 0.99**; without the 0 infra misses (harness error, no model answer): 109/110 = 0.99. Spend 3.717 USD (278 live calls, 0.0338 USD/item); latency p50 2.7 s, p95 27.19 s; errors 0.

Grader failures: mentions_any 1.
Answer paths: llm 46, guide 46, not_in_documents 11, m2 7.
Reasons: None 81, out_of_scope 18, model_not_in_documents 11.

### By class

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| clarify | 6 | 6 | 1.00 |
| data | 27 | 27 | 1.00 |
| explain | 14 | 14 | 1.00 |
| followup | 6 | 6 | 1.00 |
| navigate | 8 | 8 | 1.00 |
| near_miss | 6 | 6 | 1.00 |
| overview | 4 | 5 | 0.80 |
| photos | 10 | 10 | 1.00 |
| refuse_injection | 7 | 7 | 1.00 |
| refuse_unrelated | 5 | 5 | 1.00 |
| refuse_write | 6 | 6 | 1.00 |
| role | 10 | 10 | 1.00 |

### By persona

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| admin_01 | 5 | 5 | 1.00 |
| audit_01 | 11 | 11 | 1.00 |
| exec_01 | 17 | 17 | 1.00 |
| ic_01 | 16 | 17 | 0.94 |
| log_01 | 9 | 9 | 1.00 |
| ml_01 | 9 | 9 | 1.00 |
| ops_dm_01 | 14 | 14 | 1.00 |
| ops_dm_02 | 6 | 6 | 1.00 |
| plan_etr_01 | 3 | 3 | 1.00 |
| wtr_comp_01 | 6 | 6 | 1.00 |
| wtr_lead_01 | 13 | 13 | 1.00 |

### By language

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| de | 4 | 4 | 1.00 |
| en | 72 | 73 | 0.99 |
| es | 4 | 4 | 1.00 |
| fr | 4 | 4 | 1.00 |
| pl | 25 | 25 | 1.00 |

### By moment

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| at-n1 | 46 | 46 | 1.00 |
| morning-after | 40 | 40 | 1.00 |
| notices-lifted | 23 | 24 | 0.96 |

### By page

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| admin | 5 | 5 | 1.00 |
| after_action | 7 | 7 | 1.00 |
| ask | 1 | 1 | 1.00 |
| brief | 9 | 9 | 1.00 |
| crews | 16 | 16 | 1.00 |
| decisions | 12 | 12 | 1.00 |
| forecast | 4 | 4 | 1.00 |
| health | 7 | 7 | 1.00 |
| help | 1 | 1 | 1.00 |
| map | 8 | 8 | 1.00 |
| none | 18 | 19 | 0.95 |
| water | 21 | 21 | 1.00 |

### By split

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| heldout | 109 | 110 | 0.99 |

### By tag

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| demo_moment | 3 | 3 | 1.00 |
| link_request | 10 | 10 | 1.00 |
| no_diacritics | 6 | 6 | 1.00 |
| other_language | 12 | 12 | 1.00 |
| role_limit | 3 | 3 | 1.00 |
| starter | 2 | 2 | 1.00 |
| typo | 3 | 4 | 0.75 |
| user_reported | 3 | 3 | 1.00 |
| vague | 9 | 10 | 0.90 |

### Failed items

| Id | Class | Lang | Persona | Moment | Failed | Path/reason | Answer (start) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AB-OVR-014 | overview | en | ic_01 | notices-lifted | mentions_any | held out | (redacted) |
