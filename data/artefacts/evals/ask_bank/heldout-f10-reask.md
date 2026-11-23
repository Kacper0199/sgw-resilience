# Ask bank report: heldout-f10-reask

Commit `12ef88b6`, split `heldout`, gateway `replay_then_live`, wave `R35`, started 2026-11-22T14:06:30Z, 100.3 s.

**Pass 23/30 = 0.77**; without the 11 infra misses (harness error, no model answer): 19/19 = 1.00. Spend 0.833 USD (45 live calls, 0.0278 USD/item); latency p50 1.24 s, p95 18.04 s; errors 0.

Grader failures: mentions_any 4, language 2, clarifies 1.
Answer paths: llm 16, m2 11, not_in_documents 3.
Reasons: None 19, llm_unavailable 11.

### By class

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| clarify | 3 | 4 | 0.75 |
| data | 11 | 13 | 0.85 |
| explain | 3 | 3 | 1.00 |
| followup | 3 | 3 | 1.00 |
| overview | 2 | 4 | 0.50 |
| role | 1 | 3 | 0.33 |

### By persona

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| audit_01 | 1 | 1 | 1.00 |
| exec_01 | 3 | 4 | 0.75 |
| ic_01 | 5 | 6 | 0.83 |
| ml_01 | 1 | 1 | 1.00 |
| ops_dm_01 | 2 | 2 | 1.00 |
| ops_dm_02 | 2 | 2 | 1.00 |
| plan_etr_01 | 1 | 1 | 1.00 |
| wtr_comp_01 | 3 | 5 | 0.60 |
| wtr_lead_01 | 5 | 8 | 0.62 |

### By language

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| en | 16 | 19 | 0.84 |
| es | 1 | 2 | 0.50 |
| fr | 1 | 1 | 1.00 |
| pl | 5 | 8 | 0.62 |

### By moment

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| morning-after | 18 | 21 | 0.86 |
| notices-lifted | 5 | 9 | 0.56 |

### By page

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| after_action | 1 | 1 | 1.00 |
| brief | 3 | 4 | 0.75 |
| decisions | 4 | 4 | 1.00 |
| forecast | 1 | 1 | 1.00 |
| health | 1 | 1 | 1.00 |
| map | 4 | 4 | 1.00 |
| none | 1 | 2 | 0.50 |
| water | 8 | 13 | 0.61 |

### By split

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| heldout | 23 | 30 | 0.77 |

### By tag

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| demo_moment | 3 | 3 | 1.00 |
| link_request | 2 | 2 | 1.00 |
| no_diacritics | 2 | 3 | 0.67 |
| other_language | 2 | 3 | 0.67 |
| starter | 1 | 1 | 1.00 |
| typo | 0 | 1 | 0.00 |
| vague | 4 | 7 | 0.57 |

### Failed items

| Id | Class | Lang | Persona | Moment | Failed | Path/reason | Answer (start) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AB-OVR-020 | overview | pl | wtr_lead_01 | morning-after | mentions_any | held out | (redacted) |
| AB-ROLE-015 | role | pl | wtr_lead_01 | morning-after | mentions_any | held out | (redacted) |
| AB-ROLE-021 | role | es | exec_01 | morning-after | language | held out | (redacted) |
| AB-CLAR-003 | clarify | en | wtr_comp_01 | notices-lifted | clarifies | held out | (redacted) |
| AB-DATA-033 | data | en | wtr_comp_01 | notices-lifted | mentions_any | held out | (redacted) |
| AB-DATA-069 | data | pl | wtr_lead_01 | notices-lifted | language | held out | (redacted) |
| AB-OVR-014 | overview | en | ic_01 | notices-lifted | mentions_any | held out | (redacted) |
