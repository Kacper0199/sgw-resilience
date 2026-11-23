# Ask bank report: c1-smoke-2

Commit `aa628e2`, split `dev` (smoke), gateway `replay_then_live`, wave `R33`, started 2026-11-21T22:39:41Z, 120.7 s.

**Pass 32/40 = 0.80**; without the 0 infra misses (harness error, no model answer): 32/40 = 0.80. Spend 0.219 USD (29 live calls, 0.0055 USD/item); latency p50 2.08 s, p95 8.05 s; errors 0.

Grader failures: mentions_any 6, clarifies 1, not_bare_refusal 1.
Answer paths: llm 18, guide 16, not_in_documents 5, m2 1.
Reasons: None 27, out_of_scope 7, model_not_in_documents 5, checks_failed 1.

### By class

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| clarify | 2 | 3 | 0.67 |
| data | 4 | 7 | 0.57 |
| explain | 3 | 3 | 1.00 |
| followup | 4 | 4 | 1.00 |
| navigate | 5 | 5 | 1.00 |
| near_miss | 0 | 3 | 0.00 |
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
| ic_01 | 3 | 5 | 0.60 |
| log_01 | 3 | 4 | 0.75 |
| ml_01 | 3 | 3 | 1.00 |
| ops_dm_01 | 3 | 4 | 0.75 |
| ops_dm_02 | 3 | 3 | 1.00 |
| plan_etr_01 | 3 | 3 | 1.00 |
| wtr_comp_01 | 3 | 4 | 0.75 |
| wtr_lead_01 | 2 | 4 | 0.50 |

### By language

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| de | 2 | 2 | 1.00 |
| en | 21 | 25 | 0.84 |
| es | 1 | 1 | 1.00 |
| fr | 1 | 1 | 1.00 |
| pl | 7 | 11 | 0.64 |

### By moment

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| at-n1 | 10 | 14 | 0.71 |
| morning-after | 12 | 14 | 0.86 |
| notices-lifted | 10 | 12 | 0.83 |

### By page

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| after_action | 3 | 4 | 0.75 |
| brief | 1 | 1 | 1.00 |
| crews | 5 | 6 | 0.83 |
| decisions | 6 | 6 | 1.00 |
| forecast | 4 | 4 | 1.00 |
| health | 2 | 2 | 1.00 |
| help | 1 | 1 | 1.00 |
| map | 0 | 1 | 0.00 |
| none | 6 | 7 | 0.86 |
| water | 4 | 8 | 0.50 |

### By split

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| dev | 32 | 40 | 0.80 |

### By tag

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| demo_moment | 3 | 4 | 0.75 |
| link_request | 6 | 6 | 1.00 |
| no_diacritics | 3 | 4 | 0.75 |
| other_language | 4 | 4 | 1.00 |
| user_reported | 4 | 7 | 0.57 |
| vague | 6 | 8 | 0.75 |

### Failed items

| Id | Class | Lang | Persona | Moment | Failed | Path/reason | Answer (start) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AB-DATA-067 | data | pl | ic_01 | at-n1 | mentions_any | llm/None | Najważniejsza jest decyzja DC-D3-PS17-POWER, bo tylko ona ma werdykt "decide before the next advisory". Jej te |
| AB-DATA-010 | data | en | log_01 | at-n1 | mentions_any | llm/None | This is not in the documents for portable generators near Aiken: the evidence has no portable generator record |
| AB-CLAR-005 | clarify | en | ops_dm_01 | at-n1 | clarifies | llm/None | The question names no feeder, so I can't say whether a particular feeder is out. Across all feeders, the open  |
| AB-NEAR-014 | near_miss | pl | wtr_lead_01 | at-n1 | mentions_any | not_in_documents/model_not_in_documents | Dane platformy, które mogę przeczytać, nie odpowiadają na to wprost. Najbliższe miejsca, gdzie warto zajrzeć,  |
| AB-DATA-026 | data | en | wtr_lead_01 | morning-after | mentions_any | not_in_documents/model_not_in_documents | The platform data I checked (decision cases, pump stations, zones, tanks and the decision queue) does not show |
| AB-OVR-018 | overview | pl | ic_01 | morning-after | mentions_any | llm/None | Burza trwa, a sytuacja jest poważna: na wielu odcinkach AIK jest 37 otwartych awarii i 41,127 odbiorców bez pr |
| AB-NEAR-011 | near_miss | en | exec_01 | notices-lifted | not_bare_refusal | guide/out_of_scope | Ask only covers the Hurricane Helene storm response, so it has no earthquake review and nothing from last year |
| AB-NEAR-016 | near_miss | pl | wtr_comp_01 | notices-lifted | mentions_any | not_in_documents/model_not_in_documents | Dane platformy nie pokazują komunikatu o gotowaniu wody dla Millpond. Sprawdzono stacje pomp, strefy, zbiornik |
