# Ask bank report: r1-smoke

Commit `f9a48f7`, split `dev` (smoke), gateway `replay_then_live`, wave `R34`, started 2026-11-22T06:50:59Z, 268.1 s.

**Pass 36/40 = 0.90**; without the 7 infra misses (harness error, no model answer): 33/33 = 1.00. Spend 1.185 USD (83 live calls, 0.0296 USD/item); latency p50 0.7 s, p95 22.02 s; errors 0.

Grader failures: language 2, mentions_any 2, mentions_all 1.
Answer paths: guide 16, llm 13, m2 7, not_in_documents 4.
Reasons: None 24, llm_unavailable 7, out_of_scope 6, model_not_in_documents 3.

### By class

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| clarify | 3 | 3 | 1.00 |
| data | 7 | 7 | 1.00 |
| explain | 2 | 3 | 0.67 |
| followup | 4 | 4 | 1.00 |
| navigate | 5 | 5 | 1.00 |
| near_miss | 1 | 3 | 0.33 |
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
| audit_01 | 3 | 4 | 0.75 |
| exec_01 | 1 | 3 | 0.33 |
| ic_01 | 5 | 5 | 1.00 |
| log_01 | 4 | 4 | 1.00 |
| ml_01 | 3 | 3 | 1.00 |
| ops_dm_01 | 4 | 4 | 1.00 |
| ops_dm_02 | 3 | 3 | 1.00 |
| plan_etr_01 | 3 | 3 | 1.00 |
| wtr_comp_01 | 3 | 4 | 0.75 |
| wtr_lead_01 | 4 | 4 | 1.00 |

### By language

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| de | 2 | 2 | 1.00 |
| en | 24 | 25 | 0.96 |
| es | 1 | 1 | 1.00 |
| fr | 1 | 1 | 1.00 |
| pl | 8 | 11 | 0.73 |

### By moment

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| at-n1 | 14 | 14 | 1.00 |
| morning-after | 14 | 14 | 1.00 |
| notices-lifted | 8 | 12 | 0.67 |

### By page

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| after_action | 2 | 4 | 0.50 |
| brief | 0 | 1 | 0.00 |
| crews | 6 | 6 | 1.00 |
| decisions | 6 | 6 | 1.00 |
| forecast | 4 | 4 | 1.00 |
| health | 2 | 2 | 1.00 |
| help | 1 | 1 | 1.00 |
| map | 1 | 1 | 1.00 |
| none | 7 | 7 | 1.00 |
| water | 7 | 8 | 0.88 |

### By split

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| dev | 36 | 40 | 0.90 |

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
| AB-OVR-023 | overview | pl | exec_01 | notices-lifted | language | m2/llm_unavailable | Answer from platform data. The AI is not available right now. [DC-D3-PS23-LAURELSPUR-BWA-LIFT] DC-D3-PS23-LAUR |
| AB-EXP-034 | explain | pl | audit_01 | notices-lifted | mentions_any | not_in_documents/llm_unavailable | Dane platformy, które mogę przeczytać, nie odpowiadają na to wprost. Najbliższe miejsca, gdzie warto zajrzeć,  |
| AB-NEAR-011 | near_miss | en | exec_01 | notices-lifted | mentions_all | m2/llm_unavailable | Answer from platform data. The AI is not available right now. [quote] The procedure says: "While a hurricane w |
| AB-NEAR-016 | near_miss | pl | wtr_comp_01 | notices-lifted | language, mentions_any | m2/llm_unavailable | Answer from platform data. The AI is not available right now. [DC-D2-CREWS-AIK] DC-D2-CREWS-AIK: decided on ti |
