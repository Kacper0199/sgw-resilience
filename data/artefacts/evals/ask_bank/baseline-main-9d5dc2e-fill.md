# Ask bank report: baseline-main-9d5dc2e-fill

Commit `9d5dc2e+evals`, split `all`, gateway `replay_then_live`, wave `R33`, started 2026-11-21T22:22:58Z, 113.0 s.

**Pass 3/19 = 0.16**; without the 14 infra misses (harness error, no model answer): 2/5 = 0.40. Spend 0.448 USD (29 live calls, 0.0236 USD/item); latency p50 5.38 s, p95 25.38 s; errors 9.

Grader failures: language 14, not_bare_refusal 11, error 9, mentions_any 8, links 3, photos 2, helpful_refusal 2, refuses 2, near_miss 1.
Answer paths: None 9, m2 4, not_in_documents 3, llm 3.
Reasons: None 12, llm_unavailable 5, model_not_in_documents 2.

### By class

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| data | 0 | 2 | 0.00 |
| explain | 0 | 2 | 0.00 |
| followup | 0 | 1 | 0.00 |
| navigate | 0 | 3 | 0.00 |
| near_miss | 0 | 1 | 0.00 |
| overview | 2 | 3 | 0.67 |
| photos | 0 | 2 | 0.00 |
| refuse_unrelated | 0 | 1 | 0.00 |
| refuse_write | 0 | 1 | 0.00 |
| role | 1 | 3 | 0.33 |

### By persona

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| audit_01 | 0 | 9 | 0.00 |
| exec_01 | 2 | 2 | 1.00 |
| ic_01 | 0 | 1 | 0.00 |
| ml_01 | 0 | 1 | 0.00 |
| ops_dm_01 | 0 | 1 | 0.00 |
| ops_dm_02 | 1 | 1 | 1.00 |
| wtr_comp_01 | 0 | 3 | 0.00 |
| wtr_lead_01 | 0 | 1 | 0.00 |

### By language

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| de | 0 | 1 | 0.00 |
| en | 2 | 9 | 0.22 |
| es | 1 | 3 | 0.33 |
| fr | 0 | 2 | 0.00 |
| pl | 0 | 4 | 0.00 |

### By moment

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| morning-after | 1 | 2 | 0.50 |
| notices-lifted | 2 | 17 | 0.12 |

### By page

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| after_action | 0 | 7 | 0.00 |
| brief | 2 | 2 | 1.00 |
| crews | 0 | 2 | 0.00 |
| health | 0 | 1 | 0.00 |
| none | 1 | 3 | 0.33 |
| water | 0 | 4 | 0.00 |

### By split

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| dev | 2 | 11 | 0.18 |
| heldout | 1 | 8 | 0.12 |

### By tag

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| link_request | 0 | 3 | 0.00 |
| no_diacritics | 0 | 1 | 0.00 |
| other_language | 1 | 6 | 0.17 |
| vague | 2 | 3 | 0.67 |

### Failed items

| Id | Class | Lang | Persona | Moment | Failed | Path/reason | Answer (start) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AB-ROLE-019 | role | pl | ml_01 | morning-after | language, mentions_any, not_bare_refusal | not_in_documents/model_not_in_documents | This is not in the documents. |
| AB-EXP-009 | explain | en | audit_01 | notices-lifted | error, language, mentions_any, not_bare_refusal | None/None | RuntimeError: thread: HTTP 403 |
| AB-EXP-034 | explain | pl | audit_01 | notices-lifted | error, language, mentions_any, not_bare_refusal | None/None | RuntimeError: thread: HTTP 403 |
| AB-FUP-026 | followup | es | wtr_comp_01 | notices-lifted | language | llm/None | Copperleaf's outage status, restoration times and outage surge signal are not in the documents. On water, the  |
| AB-NAV-033 | navigate | pl | audit_01 | notices-lifted | error, language, links, not_bare_refusal | None/None | RuntimeError: thread: HTTP 403 |
| AB-NEAR-016 | near_miss | pl | wtr_comp_01 | notices-lifted | language, mentions_any, near_miss, not_bare_refusal | not_in_documents/model_not_in_documents | This is not in the documents. |
| AB-OVR-027 | overview | fr | ops_dm_01 | notices-lifted | language | m2/llm_unavailable | Answer from platform data. The AI is not available right now. [DC-D3-PS23-LAURELSPUR-BWA-LIFT] DC-D3-PS23-LAUR |
| AB-PHO-013 | photos | en | ic_01 | notices-lifted | mentions_any, not_bare_refusal, photos | not_in_documents/llm_unavailable | This is not in the documents. |
| AB-PHO-014 | photos | en | audit_01 | notices-lifted | error, language, not_bare_refusal, photos | None/None | RuntimeError: thread: HTTP 403 |
| AB-DATA-033 | data | en | wtr_comp_01 | notices-lifted | mentions_any | held out | (redacted) |
| AB-DATA-044 | data | en | audit_01 | notices-lifted | error, language, mentions_any, not_bare_refusal | held out | (redacted) |
| AB-NAV-013 | navigate | en | audit_01 | notices-lifted | error, language, links, not_bare_refusal | held out | (redacted) |
| AB-NAV-041 | navigate | fr | audit_01 | notices-lifted | error, language, links, not_bare_refusal | held out | (redacted) |
| AB-UNREL-007 | refuse_unrelated | en | audit_01 | notices-lifted | error, helpful_refusal, language, refuses | held out | (redacted) |
| AB-WRITE-019 | refuse_write | es | wtr_lead_01 | notices-lifted | helpful_refusal, language, refuses | held out | (redacted) |
| AB-ROLE-020 | role | de | audit_01 | notices-lifted | error, language, mentions_any, not_bare_refusal | held out | (redacted) |
