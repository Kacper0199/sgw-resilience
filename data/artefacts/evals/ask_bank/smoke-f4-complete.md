# Ask bank report: smoke-f4-complete

Commit `f9a48f7`, split `dev` (smoke), gateway `replay_then_live`, wave `R34`, started 2026-11-22T06:50:59Z, 268.1 s.

**Pass 39/40 = 0.97**; without the 0 infra misses (harness error, no model answer): 39/40 = 0.97. Spend 1.202 USD (77 live calls, 0.0301 USD/item); latency p50 0.98 s, p95 24.23 s; errors 0.

Grader failures: mentions_any 1.
Answer paths: llm 18, guide 16, not_in_documents 5, m2 1.
Reasons: None 29, out_of_scope 6, model_not_in_documents 5.

### By class

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| clarify | 3 | 3 | 1.00 |
| data | 7 | 7 | 1.00 |
| explain | 3 | 3 | 1.00 |
| followup | 4 | 4 | 1.00 |
| navigate | 5 | 5 | 1.00 |
| near_miss | 3 | 3 | 1.00 |
| overview | 3 | 4 | 0.75 |
| photos | 3 | 3 | 1.00 |
| refuse_injection | 2 | 2 | 1.00 |
| refuse_unrelated | 2 | 2 | 1.00 |
| refuse_write | 2 | 2 | 1.00 |
| role | 2 | 2 | 1.00 |

### By persona

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| admin_01 | 3 | 3 | 1.00 |
| audit_01 | 4 | 4 | 1.00 |
| exec_01 | 2 | 3 | 0.67 |
| ic_01 | 5 | 5 | 1.00 |
| log_01 | 4 | 4 | 1.00 |
| ml_01 | 3 | 3 | 1.00 |
| ops_dm_01 | 4 | 4 | 1.00 |
| ops_dm_02 | 3 | 3 | 1.00 |
| plan_etr_01 | 3 | 3 | 1.00 |
| wtr_comp_01 | 4 | 4 | 1.00 |
| wtr_lead_01 | 4 | 4 | 1.00 |

### By language

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| de | 2 | 2 | 1.00 |
| en | 25 | 25 | 1.00 |
| es | 1 | 1 | 1.00 |
| fr | 1 | 1 | 1.00 |
| pl | 10 | 11 | 0.91 |

### By moment

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| at-n1 | 14 | 14 | 1.00 |
| morning-after | 14 | 14 | 1.00 |
| notices-lifted | 11 | 12 | 0.92 |

### By page

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| after_action | 4 | 4 | 1.00 |
| brief | 0 | 1 | 0.00 |
| crews | 6 | 6 | 1.00 |
| decisions | 6 | 6 | 1.00 |
| forecast | 4 | 4 | 1.00 |
| health | 2 | 2 | 1.00 |
| help | 1 | 1 | 1.00 |
| map | 1 | 1 | 1.00 |
| none | 7 | 7 | 1.00 |
| water | 8 | 8 | 1.00 |

### By split

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| dev | 39 | 40 | 0.97 |

### By tag

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| demo_moment | 4 | 4 | 1.00 |
| link_request | 6 | 6 | 1.00 |
| no_diacritics | 3 | 4 | 0.75 |
| other_language | 4 | 4 | 1.00 |
| user_reported | 7 | 7 | 1.00 |
| vague | 7 | 8 | 0.88 |

### Failed items

| Id | Class | Lang | Persona | Moment | Failed | Path/reason | Answer (start) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AB-OVR-023 | overview | pl | exec_01 | notices-lifted | mentions_any | llm/None | Prąd: w hrabstwach objętych burzą bez zasilania jest 168,598 klientów, trend spada. Woda: ciśnienie w stacjach |
