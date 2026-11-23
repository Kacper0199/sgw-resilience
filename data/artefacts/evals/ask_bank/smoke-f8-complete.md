# Ask bank report: smoke-f8-complete

Commit `f9a48f7`, split `dev` (smoke), gateway `replay_then_live`, wave `R34`, started 2026-11-22T06:50:59Z, 268.1 s.

**Pass 39/40 = 0.97**; without the 4 infra misses (harness error, no model answer): 35/36 = 0.97. Spend 0.858 USD (60 live calls, 0.0214 USD/item); latency p50 1.25 s, p95 21.97 s; errors 0.

Grader failures: mentions_any 1.
Answer paths: guide 17, llm 13, not_in_documents 5, m2 5.
Reasons: None 25, out_of_scope 6, model_not_in_documents 5, llm_unavailable 4.

### By class

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| clarify | 3 | 3 | 1.00 |
| data | 7 | 7 | 1.00 |
| explain | 3 | 3 | 1.00 |
| followup | 3 | 4 | 0.75 |
| navigate | 5 | 5 | 1.00 |
| near_miss | 3 | 3 | 1.00 |
| overview | 4 | 4 | 1.00 |
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
| exec_01 | 3 | 3 | 1.00 |
| ic_01 | 5 | 5 | 1.00 |
| log_01 | 4 | 4 | 1.00 |
| ml_01 | 2 | 3 | 0.67 |
| ops_dm_01 | 4 | 4 | 1.00 |
| ops_dm_02 | 3 | 3 | 1.00 |
| plan_etr_01 | 3 | 3 | 1.00 |
| wtr_comp_01 | 4 | 4 | 1.00 |
| wtr_lead_01 | 4 | 4 | 1.00 |

### By language

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| de | 2 | 2 | 1.00 |
| en | 24 | 25 | 0.96 |
| es | 1 | 1 | 1.00 |
| fr | 1 | 1 | 1.00 |
| pl | 11 | 11 | 1.00 |

### By moment

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| at-n1 | 14 | 14 | 1.00 |
| morning-after | 13 | 14 | 0.93 |
| notices-lifted | 12 | 12 | 1.00 |

### By page

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| after_action | 4 | 4 | 1.00 |
| brief | 1 | 1 | 1.00 |
| crews | 6 | 6 | 1.00 |
| decisions | 6 | 6 | 1.00 |
| forecast | 4 | 4 | 1.00 |
| health | 1 | 2 | 0.50 |
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
| no_diacritics | 4 | 4 | 1.00 |
| other_language | 4 | 4 | 1.00 |
| user_reported | 7 | 7 | 1.00 |
| vague | 8 | 8 | 1.00 |

### Failed items

| Id | Class | Lang | Persona | Moment | Failed | Path/reason | Answer (start) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AB-FUP-015 | followup | en | ml_01 | morning-after | mentions_any | llm/None | The Network map feed (gis-trace) is flagged stale: its age is 1,590 min against a freshness limit of 1,440 min |
