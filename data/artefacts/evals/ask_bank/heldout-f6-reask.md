# Ask bank report: heldout-f6-reask

Commit `0e065ca`, split `heldout`, gateway `replay_then_live`, wave `R34`, started 2026-11-22T09:46:34Z, 104.9 s.

**Pass 22/23 = 0.96**; without the 0 infra misses (harness error, no model answer): 22/23 = 0.96. Spend 0.684 USD (35 live calls, 0.0297 USD/item); latency p50 2.71 s, p95 19.22 s; errors 0.

Grader failures: mentions_any 1.
Answer paths: llm 11, guide 10, not_in_documents 2.
Reasons: None 16, out_of_scope 5, model_not_in_documents 2.

### By class

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| clarify | 1 | 1 | 1.00 |
| data | 2 | 2 | 1.00 |
| explain | 2 | 2 | 1.00 |
| followup | 1 | 1 | 1.00 |
| navigate | 1 | 1 | 1.00 |
| near_miss | 1 | 1 | 1.00 |
| overview | 4 | 5 | 0.80 |
| photos | 3 | 3 | 1.00 |
| refuse_injection | 2 | 2 | 1.00 |
| refuse_unrelated | 2 | 2 | 1.00 |
| refuse_write | 1 | 1 | 1.00 |
| role | 2 | 2 | 1.00 |

### By persona

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| admin_01 | 2 | 2 | 1.00 |
| audit_01 | 1 | 1 | 1.00 |
| exec_01 | 3 | 3 | 1.00 |
| ic_01 | 3 | 4 | 0.75 |
| log_01 | 3 | 3 | 1.00 |
| ops_dm_01 | 3 | 3 | 1.00 |
| plan_etr_01 | 1 | 1 | 1.00 |
| wtr_comp_01 | 1 | 1 | 1.00 |
| wtr_lead_01 | 5 | 5 | 1.00 |

### By language

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| en | 3 | 4 | 0.75 |
| pl | 19 | 19 | 1.00 |

### By moment

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| at-n1 | 5 | 5 | 1.00 |
| morning-after | 13 | 13 | 1.00 |
| notices-lifted | 4 | 5 | 0.80 |

### By page

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| brief | 3 | 3 | 1.00 |
| crews | 4 | 4 | 1.00 |
| decisions | 1 | 1 | 1.00 |
| forecast | 1 | 1 | 1.00 |
| map | 1 | 1 | 1.00 |
| none | 7 | 8 | 0.88 |
| water | 5 | 5 | 1.00 |

### By split

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| heldout | 22 | 23 | 0.96 |

### By tag

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| demo_moment | 1 | 1 | 1.00 |
| link_request | 2 | 2 | 1.00 |
| no_diacritics | 5 | 5 | 1.00 |
| typo | 0 | 1 | 0.00 |
| vague | 4 | 5 | 0.80 |

### Failed items

| Id | Class | Lang | Persona | Moment | Failed | Path/reason | Answer (start) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AB-OVR-014 | overview | en | ic_01 | notices-lifted | mentions_any | held out | (redacted) |
