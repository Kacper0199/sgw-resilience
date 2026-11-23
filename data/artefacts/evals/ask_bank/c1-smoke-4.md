# Ask bank report: c1-smoke-4

Commit `a1e03c9`, split `dev` (smoke), gateway `replay_then_live`, wave `R33-C1`, started 2026-11-21T23:49:24Z, 123.5 s.

**Pass 36/40 = 0.90**; without the 0 infra misses (harness error, no model answer): 36/40 = 0.90. Spend 0.343 USD (27 live calls, 0.0086 USD/item); latency p50 2.39 s, p95 7.52 s; errors 0.

Grader failures: mentions_any 3, not_bare_refusal 1.
Answer paths: llm 18, guide 16, not_in_documents 5, m2 1.
Reasons: None 28, out_of_scope 7, model_not_in_documents 5.

### By class

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| clarify | 3 | 3 | 1.00 |
| data | 6 | 7 | 0.86 |
| explain | 3 | 3 | 1.00 |
| followup | 3 | 4 | 0.75 |
| navigate | 5 | 5 | 1.00 |
| near_miss | 3 | 3 | 1.00 |
| overview | 2 | 4 | 0.50 |
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
| ic_01 | 4 | 5 | 0.80 |
| log_01 | 3 | 4 | 0.75 |
| ml_01 | 3 | 3 | 1.00 |
| ops_dm_01 | 3 | 4 | 0.75 |
| ops_dm_02 | 3 | 3 | 1.00 |
| plan_etr_01 | 3 | 3 | 1.00 |
| wtr_comp_01 | 4 | 4 | 1.00 |
| wtr_lead_01 | 4 | 4 | 1.00 |

### By language

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| de | 2 | 2 | 1.00 |
| en | 23 | 25 | 0.92 |
| es | 1 | 1 | 1.00 |
| fr | 1 | 1 | 1.00 |
| pl | 9 | 11 | 0.82 |

### By moment

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| at-n1 | 12 | 14 | 0.86 |
| morning-after | 13 | 14 | 0.93 |
| notices-lifted | 11 | 12 | 0.92 |

### By page

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| after_action | 4 | 4 | 1.00 |
| brief | 0 | 1 | 0.00 |
| crews | 5 | 6 | 0.83 |
| decisions | 5 | 6 | 0.83 |
| forecast | 4 | 4 | 1.00 |
| health | 2 | 2 | 1.00 |
| help | 1 | 1 | 1.00 |
| map | 1 | 1 | 1.00 |
| none | 6 | 7 | 0.86 |
| water | 8 | 8 | 1.00 |

### By split

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| dev | 36 | 40 | 0.90 |

### By tag

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| demo_moment | 4 | 4 | 1.00 |
| link_request | 5 | 6 | 0.83 |
| no_diacritics | 3 | 4 | 0.75 |
| other_language | 4 | 4 | 1.00 |
| user_reported | 5 | 7 | 0.71 |
| vague | 6 | 8 | 0.75 |

### Failed items

| Id | Class | Lang | Persona | Moment | Failed | Path/reason | Answer (start) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AB-DATA-010 | data | en | log_01 | at-n1 | mentions_any | llm/None | This is not in the documents for portable generators near Aiken: the evidence has no portable generator record |
| AB-FUP-006 | followup | en | ops_dm_01 | at-n1 | not_bare_refusal | guide/out_of_scope | Ask only reads the platform, so it can't open, approve, sign or reject a decision for you. The Decisions page  |
| AB-OVR-018 | overview | pl | ic_01 | morning-after | mentions_any | llm/None | Jest faza burzy: otwartych awarii jest 37, a bez prądu zostaje 41,127 odbiorców. Obiekty krytyczne dotknięte a |
| AB-OVR-023 | overview | pl | exec_01 | notices-lifted | mentions_any | llm/None | Obecnie otwartych awarii na zasilaniu jest 0, a bez prądu zostaje 0 klientów. Detektor pokazuje 85 z 123 hrabs |
