# Ask bank report: smoke-f10-reask

Commit `12ef88b6`, split `dev`, gateway `replay_then_live`, wave `R35`, started 2026-11-22T14:08:10Z, 53.4 s.

**Pass 10/12 = 0.83**; without the 7 infra misses (harness error, no model answer): 4/5 = 0.80. Spend 0.287 USD (15 live calls, 0.0239 USD/item); latency p50 1.78 s, p95 15.12 s; errors 0.

Grader failures: mentions_any 2.
Answer paths: m2 8, llm 3, guide 1.
Reasons: llm_unavailable 7, None 5.

### By class

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| data | 4 | 4 | 1.00 |
| followup | 1 | 2 | 0.50 |
| navigate | 1 | 1 | 1.00 |
| near_miss | 0 | 1 | 0.00 |
| overview | 3 | 3 | 1.00 |
| role | 1 | 1 | 1.00 |

### By persona

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| audit_01 | 1 | 1 | 1.00 |
| exec_01 | 1 | 1 | 1.00 |
| ic_01 | 2 | 2 | 1.00 |
| ml_01 | 0 | 1 | 0.00 |
| ops_dm_01 | 1 | 1 | 1.00 |
| plan_etr_01 | 1 | 1 | 1.00 |
| wtr_comp_01 | 2 | 3 | 0.67 |
| wtr_lead_01 | 2 | 2 | 1.00 |

### By language

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| en | 8 | 9 | 0.89 |
| pl | 2 | 3 | 0.67 |

### By moment

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| morning-after | 4 | 5 | 0.80 |
| notices-lifted | 6 | 7 | 0.86 |

### By page

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| after_action | 1 | 1 | 1.00 |
| brief | 1 | 1 | 1.00 |
| decisions | 1 | 1 | 1.00 |
| forecast | 1 | 1 | 1.00 |
| health | 0 | 1 | 0.00 |
| none | 2 | 2 | 1.00 |
| water | 4 | 5 | 0.80 |

### By split

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| dev | 10 | 12 | 0.83 |

### By tag

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| demo_moment | 4 | 4 | 1.00 |
| link_request | 1 | 1 | 1.00 |
| no_diacritics | 1 | 1 | 1.00 |
| user_reported | 2 | 2 | 1.00 |
| vague | 3 | 3 | 1.00 |

### Failed items

| Id | Class | Lang | Persona | Moment | Failed | Path/reason | Answer (start) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AB-FUP-015 | followup | en | ml_01 | morning-after | mentions_any | llm/None | The Network map feed (gis-trace) is flagged stale: its age is 1,590 min against a freshness limit of 1,440 min |
| AB-NEAR-016 | near_miss | pl | wtr_comp_01 | notices-lifted | mentions_any | m2/llm_unavailable | Odpowiedź z danych platformy. AI jest teraz niedostępne. [DC-D2-CREWS-AIK] DC-D2-CREWS-AIK: podjęta w terminie |
