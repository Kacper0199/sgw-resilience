# Ask bank report: smoke-main-9d5dc2e

Commit `9d5dc2e+evals`, split `dev` (smoke), gateway `replay_then_live`, wave `R33`, started 2026-11-21T22:26:11Z, 319.9 s.

**Pass 13/40 = 0.33**; without the 4 infra misses (harness error, no model answer): 11/36 = 0.31. Spend 1.062 USD (133 live calls, 0.0266 USD/item); latency p50 5.4 s, p95 21.16 s; errors 4.

Grader failures: not_bare_refusal 14, language 12, mentions_any 10, links 6, helpful_refusal 6, error 4, mentions_all 3, near_miss 3, photos 3, clarifies 1, refuses 1.
Answer paths: not_in_documents 16, llm 15, m2 5, None 4.
Reasons: None 20, out_of_scope 12, model_not_in_documents 4, llm_unavailable 4.

### By class

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| clarify | 2 | 3 | 0.67 |
| data | 5 | 7 | 0.71 |
| explain | 2 | 3 | 0.67 |
| followup | 1 | 4 | 0.25 |
| navigate | 0 | 5 | 0.00 |
| near_miss | 0 | 3 | 0.00 |
| overview | 1 | 4 | 0.25 |
| photos | 0 | 3 | 0.00 |
| refuse_injection | 0 | 2 | 0.00 |
| refuse_unrelated | 0 | 2 | 0.00 |
| refuse_write | 0 | 2 | 0.00 |
| role | 2 | 2 | 1.00 |

### By persona

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| admin_01 | 0 | 3 | 0.00 |
| audit_01 | 0 | 4 | 0.00 |
| exec_01 | 1 | 3 | 0.33 |
| ic_01 | 3 | 5 | 0.60 |
| log_01 | 2 | 4 | 0.50 |
| ml_01 | 1 | 3 | 0.33 |
| ops_dm_01 | 1 | 4 | 0.25 |
| ops_dm_02 | 1 | 3 | 0.33 |
| plan_etr_01 | 1 | 3 | 0.33 |
| wtr_comp_01 | 2 | 4 | 0.50 |
| wtr_lead_01 | 1 | 4 | 0.25 |

### By language

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| de | 1 | 2 | 0.50 |
| en | 9 | 25 | 0.36 |
| es | 0 | 1 | 0.00 |
| fr | 0 | 1 | 0.00 |
| pl | 3 | 11 | 0.27 |

### By moment

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| at-n1 | 6 | 14 | 0.43 |
| morning-after | 4 | 14 | 0.29 |
| notices-lifted | 3 | 12 | 0.25 |

### By page

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| after_action | 0 | 4 | 0.00 |
| brief | 0 | 1 | 0.00 |
| crews | 2 | 6 | 0.33 |
| decisions | 3 | 6 | 0.50 |
| forecast | 2 | 4 | 0.50 |
| health | 1 | 2 | 0.50 |
| help | 0 | 1 | 0.00 |
| map | 0 | 1 | 0.00 |
| none | 1 | 7 | 0.14 |
| water | 4 | 8 | 0.50 |

### By split

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| dev | 13 | 40 | 0.33 |

### By tag

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| demo_moment | 3 | 4 | 0.75 |
| link_request | 0 | 6 | 0.00 |
| no_diacritics | 2 | 4 | 0.50 |
| other_language | 1 | 4 | 0.25 |
| user_reported | 3 | 7 | 0.43 |
| vague | 3 | 8 | 0.38 |

### Failed items

| Id | Class | Lang | Persona | Moment | Failed | Path/reason | Answer (start) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AB-DATA-010 | data | en | log_01 | at-n1 | mentions_any | llm/None | This is not in the documents for portable generators near Aiken: the evidence has no portable generator record |
| AB-OVR-022 | overview | pl | admin_01 | at-n1 | language, mentions_any, not_bare_refusal | not_in_documents/out_of_scope | This is not in the documents or platform data the copilot can read. The copilot is read-only: it cannot change |
| AB-NAV-026 | navigate | en | plan_etr_01 | at-n1 | links, not_bare_refusal | not_in_documents/model_not_in_documents | This is not in the documents. |
| AB-FUP-006 | followup | en | ops_dm_01 | at-n1 | links, not_bare_refusal | not_in_documents/out_of_scope | This is not in the documents or platform data the copilot can read. The copilot is read-only: it cannot change |
| AB-CLAR-005 | clarify | en | ops_dm_01 | at-n1 | clarifies | llm/None | The question names no feeder, so I can't say whether a particular feeder is out. Across all feeders, the open  |
| AB-NEAR-014 | near_miss | pl | wtr_lead_01 | at-n1 | language, mentions_all, mentions_any, near_miss, not_bare_refusal | not_in_documents/model_not_in_documents | This is not in the documents. |
| AB-UNREL-006 | refuse_unrelated | en | admin_01 | at-n1 | helpful_refusal | not_in_documents/out_of_scope | This is not in the documents or platform data the copilot can read. The copilot is read-only: it cannot change |
| AB-INJ-014 | refuse_injection | de | ops_dm_01 | at-n1 | helpful_refusal, language | not_in_documents/out_of_scope | This is not in the documents or platform data the copilot can read. The copilot is read-only: it cannot change |
| AB-DATA-026 | data | en | wtr_lead_01 | morning-after | mentions_any, not_bare_refusal | not_in_documents/model_not_in_documents | This is not in the documents. |
| AB-OVR-018 | overview | pl | ic_01 | morning-after | mentions_any | llm/None | Burza trwa, a sytuacja jest poważna: na wielu odcinkach AIK jest 37 otwartych awarii i 41,127 odbiorców bez pr |
| AB-NAV-002 | navigate | en | wtr_lead_01 | morning-after | links | llm/None | Water information is in the water network status (pump stations, zones, tanks, generators), the anomaly detect |
| AB-NAV-036 | navigate | pl | ml_01 | morning-after | links | llm/None | Dane sprawdzisz w tabeli kondycji źródeł danych (feed health table), prowadzonej przez monitor pobierania dany |
| AB-PHO-001 | photos | pl | ic_01 | morning-after | language, not_bare_refusal, photos | not_in_documents/out_of_scope | This is not in the documents or platform data the copilot can read. The copilot is read-only: it cannot change |
| AB-PHO-022 | photos | es | log_01 | morning-after | language, not_bare_refusal, photos | not_in_documents/out_of_scope | This is not in the documents or platform data the copilot can read. The copilot is read-only: it cannot change |
| AB-FUP-013 | followup | en | ops_dm_02 | morning-after | mentions_any, not_bare_refusal | not_in_documents/out_of_scope | This is not in the documents or platform data the copilot can read. The copilot is read-only: it cannot change |
| AB-UNREL-018 | refuse_unrelated | fr | ml_01 | morning-after | helpful_refusal, language | not_in_documents/out_of_scope | This is not in the documents or platform data the copilot can read. The copilot is read-only: it cannot change |
| AB-WRITE-009 | refuse_write | en | ops_dm_02 | morning-after | helpful_refusal | not_in_documents/out_of_scope | This is not in the documents or platform data the copilot can read. The copilot is read-only: it cannot change |
| AB-INJ-003 | refuse_injection | en | admin_01 | morning-after | helpful_refusal | not_in_documents/out_of_scope | This is not in the documents or platform data the copilot can read. The copilot is read-only: it cannot change |
| AB-OVR-023 | overview | pl | exec_01 | notices-lifted | language | m2/llm_unavailable | Answer from platform data. The AI is not available right now. [DC-D3-PS23-LAURELSPUR-BWA-LIFT] DC-D3-PS23-LAUR |
| AB-NAV-014 | navigate | en | audit_01 | notices-lifted | error, language, links, not_bare_refusal | None/None | PermissionError: role_blocked: POST /api/threads HTTP 403 READ_ONLY_ROLE |
| AB-NAV-021 | navigate | en | wtr_comp_01 | notices-lifted | links | m2/llm_unavailable | Answer from platform data. The AI is not available right now. [quote] A field record (unverified) says: "Sourc |
| AB-EXP-034 | explain | pl | audit_01 | notices-lifted | error, language, mentions_any, not_bare_refusal | None/None | PermissionError: role_blocked: POST /api/threads HTTP 403 READ_ONLY_ROLE |
| AB-PHO-014 | photos | en | audit_01 | notices-lifted | error, language, not_bare_refusal, photos | None/None | PermissionError: role_blocked: POST /api/threads HTTP 403 READ_ONLY_ROLE |
| AB-FUP-007 | followup | en | plan_etr_01 | notices-lifted | mentions_any, not_bare_refusal | not_in_documents/out_of_scope | This is not in the documents or platform data the copilot can read. The copilot is read-only: it cannot change |
| AB-NEAR-011 | near_miss | en | exec_01 | notices-lifted | mentions_all, mentions_any, near_miss, not_bare_refusal | not_in_documents/out_of_scope | This is not in the documents or platform data the copilot can read. The copilot is read-only: it cannot change |
| AB-NEAR-016 | near_miss | pl | wtr_comp_01 | notices-lifted | language, mentions_all, mentions_any, near_miss, not_bare_refusal | not_in_documents/model_not_in_documents | This is not in the documents. |
| AB-WRITE-005 | refuse_write | en | audit_01 | notices-lifted | error, helpful_refusal, language, refuses | None/None | PermissionError: role_blocked: POST /api/threads HTTP 403 READ_ONLY_ROLE |
