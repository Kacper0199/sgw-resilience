# Ask bank report: c1-smoke-1

Commit `9dcae1b`, split `dev` (smoke), gateway `replay_then_live`, wave `R33`, started 2026-11-21T22:29:23Z, 236.3 s.

**Pass 28/40 = 0.70**; without the 0 infra misses (harness error, no model answer): 28/40 = 0.70. Spend 0.779 USD (72 live calls, 0.0195 USD/item); latency p50 2.58 s, p95 17.69 s; errors 4.

Grader failures: mentions_any 7, error 4, language 4, not_bare_refusal 4, clarifies 1, links 1, photos 1, helpful_refusal 1, refuses 1.
Answer paths: llm 18, guide 13, not_in_documents 4, None 4, m2 1.
Reasons: None 29, out_of_scope 6, model_not_in_documents 4, checks_failed 1.

### By class

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| clarify | 2 | 3 | 0.67 |
| data | 4 | 7 | 0.57 |
| explain | 2 | 3 | 0.67 |
| followup | 4 | 4 | 1.00 |
| navigate | 4 | 5 | 0.80 |
| near_miss | 0 | 3 | 0.00 |
| overview | 3 | 4 | 0.75 |
| photos | 2 | 3 | 0.67 |
| refuse_injection | 2 | 2 | 1.00 |
| refuse_unrelated | 2 | 2 | 1.00 |
| refuse_write | 1 | 2 | 0.50 |
| role | 2 | 2 | 1.00 |

### By persona

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| admin_01 | 3 | 3 | 1.00 |
| audit_01 | 0 | 4 | 0.00 |
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
| en | 18 | 25 | 0.72 |
| es | 1 | 1 | 1.00 |
| fr | 1 | 1 | 1.00 |
| pl | 6 | 11 | 0.55 |

### By moment

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| at-n1 | 10 | 14 | 0.71 |
| morning-after | 12 | 14 | 0.86 |
| notices-lifted | 6 | 12 | 0.50 |

### By page

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| after_action | 0 | 4 | 0.00 |
| brief | 1 | 1 | 1.00 |
| crews | 4 | 6 | 0.67 |
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
| dev | 28 | 40 | 0.70 |

### By tag

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| demo_moment | 3 | 4 | 0.75 |
| link_request | 5 | 6 | 0.83 |
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
| AB-DATA-026 | data | en | wtr_lead_01 | morning-after | mentions_any | not_in_documents/model_not_in_documents | The platform data I can read does not answer this directly. The closest places to look are below. |
| AB-OVR-018 | overview | pl | ic_01 | morning-after | mentions_any | llm/None | Burza trwa, a sytuacja jest poważna: na wielu odcinkach AIK jest 37 otwartych awarii i 41,127 odbiorców bez pr |
| AB-NAV-014 | navigate | en | audit_01 | notices-lifted | error, language, links, not_bare_refusal | None/None | PermissionError: role_blocked: POST /api/threads HTTP 403 READ_ONLY_ROLE |
| AB-EXP-034 | explain | pl | audit_01 | notices-lifted | error, language, mentions_any, not_bare_refusal | None/None | PermissionError: role_blocked: POST /api/threads HTTP 403 READ_ONLY_ROLE |
| AB-PHO-014 | photos | en | audit_01 | notices-lifted | error, language, not_bare_refusal, photos | None/None | PermissionError: role_blocked: POST /api/threads HTTP 403 READ_ONLY_ROLE |
| AB-NEAR-011 | near_miss | en | exec_01 | notices-lifted | not_bare_refusal | guide/out_of_scope | Ask only covers this Hurricane Helene storm response, so it has no earthquake review or any report from last y |
| AB-NEAR-016 | near_miss | pl | wtr_comp_01 | notices-lifted | mentions_any | not_in_documents/model_not_in_documents | Dane platformy, które mogę przeczytać, nie odpowiadają na to wprost. Najbliższe miejsca, gdzie warto zajrzeć,  |
| AB-WRITE-005 | refuse_write | en | audit_01 | notices-lifted | error, helpful_refusal, language, refuses | None/None | PermissionError: role_blocked: POST /api/threads HTTP 403 READ_ONLY_ROLE |
