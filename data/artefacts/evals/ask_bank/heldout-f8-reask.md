# Ask bank report: heldout-f8-reask

Commit `fcf1634`, split `heldout`, gateway `replay_then_live`, wave `R35`, started 2026-11-22T12:24:20Z, 126.2 s.

**Pass 29/30 = 0.97**; without the 3 infra misses (harness error, no model answer): 27/27 = 1.00. Spend 1.176 USD (52 live calls, 0.0392 USD/item); latency p50 3.08 s, p95 22.42 s; errors 0.

Grader failures: mentions_any 1.
Answer paths: llm 24, m2 6.
Reasons: None 27, llm_unavailable 3.

### By class

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| clarify | 4 | 4 | 1.00 |
| data | 12 | 13 | 0.92 |
| explain | 3 | 3 | 1.00 |
| followup | 3 | 3 | 1.00 |
| overview | 4 | 4 | 1.00 |
| role | 3 | 3 | 1.00 |

### By persona

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| audit_01 | 1 | 1 | 1.00 |
| exec_01 | 4 | 4 | 1.00 |
| ic_01 | 6 | 6 | 1.00 |
| ml_01 | 1 | 1 | 1.00 |
| ops_dm_01 | 2 | 2 | 1.00 |
| ops_dm_02 | 2 | 2 | 1.00 |
| plan_etr_01 | 1 | 1 | 1.00 |
| wtr_comp_01 | 4 | 5 | 0.80 |
| wtr_lead_01 | 8 | 8 | 1.00 |

### By language

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| en | 18 | 19 | 0.95 |
| es | 2 | 2 | 1.00 |
| fr | 1 | 1 | 1.00 |
| pl | 8 | 8 | 1.00 |

### By moment

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| morning-after | 21 | 21 | 1.00 |
| notices-lifted | 8 | 9 | 0.89 |

### By page

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| after_action | 1 | 1 | 1.00 |
| brief | 4 | 4 | 1.00 |
| decisions | 4 | 4 | 1.00 |
| forecast | 1 | 1 | 1.00 |
| health | 1 | 1 | 1.00 |
| map | 4 | 4 | 1.00 |
| none | 2 | 2 | 1.00 |
| water | 12 | 13 | 0.92 |

### By split

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| heldout | 29 | 30 | 0.97 |

### By tag

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| demo_moment | 3 | 3 | 1.00 |
| link_request | 2 | 2 | 1.00 |
| no_diacritics | 3 | 3 | 1.00 |
| other_language | 3 | 3 | 1.00 |
| starter | 1 | 1 | 1.00 |
| typo | 1 | 1 | 1.00 |
| vague | 7 | 7 | 1.00 |

### Failed items

| Id | Class | Lang | Persona | Moment | Failed | Path/reason | Answer (start) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AB-DATA-033 | data | en | wtr_comp_01 | notices-lifted | mentions_any | held out | (redacted) |
