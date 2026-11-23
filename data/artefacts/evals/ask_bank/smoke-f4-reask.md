# Ask bank report: smoke-f4-reask

Commit `d77fb88`, split `dev`, gateway `replay_then_live`, wave `R34`, started 2026-11-22T08:13:16Z, 46.2 s.

**Pass 14/15 = 0.93**; without the 0 infra misses (harness error, no model answer): 14/15 = 0.93. Spend 0.191 USD (10 live calls, 0.0128 USD/item); latency p50 1.39 s, p95 10.1 s; errors 0.

Grader failures: mentions_any 1.
Answer paths: llm 7, not_in_documents 5, guide 3.
Reasons: None 8, model_not_in_documents 5, out_of_scope 2.

### By class

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| clarify | 2 | 2 | 1.00 |
| data | 1 | 1 | 1.00 |
| explain | 2 | 2 | 1.00 |
| followup | 1 | 1 | 1.00 |
| navigate | 1 | 1 | 1.00 |
| near_miss | 2 | 2 | 1.00 |
| overview | 2 | 3 | 0.67 |
| refuse_write | 2 | 2 | 1.00 |
| role | 1 | 1 | 1.00 |

### By persona

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| audit_01 | 2 | 2 | 1.00 |
| exec_01 | 1 | 2 | 0.50 |
| ic_01 | 3 | 3 | 1.00 |
| log_01 | 1 | 1 | 1.00 |
| ops_dm_01 | 1 | 1 | 1.00 |
| ops_dm_02 | 2 | 2 | 1.00 |
| plan_etr_01 | 2 | 2 | 1.00 |
| wtr_comp_01 | 1 | 1 | 1.00 |
| wtr_lead_01 | 1 | 1 | 1.00 |

### By language

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| en | 10 | 10 | 1.00 |
| pl | 4 | 5 | 0.80 |

### By moment

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| at-n1 | 6 | 6 | 1.00 |
| morning-after | 4 | 4 | 1.00 |
| notices-lifted | 4 | 5 | 0.80 |

### By page

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| after_action | 3 | 3 | 1.00 |
| brief | 0 | 1 | 0.00 |
| crews | 1 | 1 | 1.00 |
| decisions | 4 | 4 | 1.00 |
| forecast | 2 | 2 | 1.00 |
| none | 2 | 2 | 1.00 |
| water | 2 | 2 | 1.00 |

### By split

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| dev | 14 | 15 | 0.93 |

### By tag

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| link_request | 2 | 2 | 1.00 |
| no_diacritics | 0 | 1 | 0.00 |
| user_reported | 3 | 3 | 1.00 |
| vague | 4 | 5 | 0.80 |

### Failed items

| Id | Class | Lang | Persona | Moment | Failed | Path/reason | Answer (start) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AB-OVR-023 | overview | pl | exec_01 | notices-lifted | mentions_any | llm/None | Prąd: w hrabstwach objętych burzą bez zasilania jest 168,598 klientów, trend spada. Woda: ciśnienie w stacjach |
