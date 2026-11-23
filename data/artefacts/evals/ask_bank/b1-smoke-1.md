# Ask bank report: b1-smoke-1

Commit `4df5820`, split `dev` (smoke), gateway `replay_then_live`, wave `R34`, started 2026-11-22T03:28:11Z, 334.6 s.

**Pass 33/40 = 0.82**; without the 9 infra misses (harness error, no model answer): 28/31 = 0.90. Spend 1.121 USD (107 live calls, 0.0280 USD/item); latency p50 3.72 s, p95 21.56 s; errors 0.

Grader failures: mentions_any 3, language 3, mentions_all 2, links 1.
Answer paths: guide 16, llm 12, m2 8, not_in_documents 4.
Reasons: None 23, llm_unavailable 9, out_of_scope 6, model_not_in_documents 2.

### By class

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| clarify | 3 | 3 | 1.00 |
| data | 7 | 7 | 1.00 |
| explain | 1 | 3 | 0.33 |
| followup | 4 | 4 | 1.00 |
| navigate | 4 | 5 | 0.80 |
| near_miss | 1 | 3 | 0.33 |
| overview | 3 | 4 | 0.75 |
| photos | 3 | 3 | 1.00 |
| refuse_injection | 2 | 2 | 1.00 |
| refuse_unrelated | 2 | 2 | 1.00 |
| refuse_write | 2 | 2 | 1.00 |
| role | 1 | 2 | 0.50 |

### By persona

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| admin_01 | 3 | 3 | 1.00 |
| audit_01 | 3 | 4 | 0.75 |
| exec_01 | 0 | 3 | 0.00 |
| ic_01 | 5 | 5 | 1.00 |
| log_01 | 3 | 4 | 0.75 |
| ml_01 | 3 | 3 | 1.00 |
| ops_dm_01 | 4 | 4 | 1.00 |
| ops_dm_02 | 3 | 3 | 1.00 |
| plan_etr_01 | 2 | 3 | 0.67 |
| wtr_comp_01 | 3 | 4 | 0.75 |
| wtr_lead_01 | 4 | 4 | 1.00 |

### By language

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| de | 1 | 2 | 0.50 |
| en | 23 | 25 | 0.92 |
| es | 1 | 1 | 1.00 |
| fr | 1 | 1 | 1.00 |
| pl | 7 | 11 | 0.64 |

### By moment

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| at-n1 | 11 | 14 | 0.79 |
| morning-after | 14 | 14 | 1.00 |
| notices-lifted | 8 | 12 | 0.67 |

### By page

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| after_action | 2 | 4 | 0.50 |
| brief | 0 | 1 | 0.00 |
| crews | 5 | 6 | 0.83 |
| decisions | 6 | 6 | 1.00 |
| forecast | 2 | 4 | 0.50 |
| health | 2 | 2 | 1.00 |
| help | 1 | 1 | 1.00 |
| map | 1 | 1 | 1.00 |
| none | 7 | 7 | 1.00 |
| water | 7 | 8 | 0.88 |

### By split

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| dev | 33 | 40 | 0.82 |

### By tag

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| demo_moment | 4 | 4 | 1.00 |
| link_request | 5 | 6 | 0.83 |
| no_diacritics | 2 | 4 | 0.50 |
| other_language | 3 | 4 | 0.75 |
| user_reported | 7 | 7 | 1.00 |
| vague | 7 | 8 | 0.88 |

### Failed items

| Id | Class | Lang | Persona | Moment | Failed | Path/reason | Answer (start) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AB-NAV-026 | navigate | en | plan_etr_01 | at-n1 | links | llm/None | The forecast tools offer these precomputed what-if scenarios: pump_station_outage, feeder_restore_order, crew_ |
| AB-EXP-037 | explain | de | exec_01 | at-n1 | mentions_any | not_in_documents/model_not_in_documents | ETR bedeutet vermutlich „Estimated Time of Restoration“, also die geschätzte Zeit, bis der Strom wieder da ist |
| AB-ROLE-018 | role | pl | log_01 | at-n1 | language | llm/None | Logistics podpisuje sam siedem decyzji: DC-D3-PS17-FUEL (na ścieżce krytycznej, termin Sep 28, 10:59 ET), DC-D |
| AB-OVR-023 | overview | pl | exec_01 | notices-lifted | language | m2/llm_unavailable | Answer from platform data. The AI is not available right now. [DC-D3-PS23-LAURELSPUR-BWA-LIFT] DC-D3-PS23-LAUR |
| AB-EXP-034 | explain | pl | audit_01 | notices-lifted | mentions_any | not_in_documents/llm_unavailable | Dane platformy, które mogę przeczytać, nie odpowiadają na to wprost. Najbliższe miejsca, gdzie warto zajrzeć,  |
| AB-NEAR-011 | near_miss | en | exec_01 | notices-lifted | mentions_all | m2/llm_unavailable | Answer from platform data. The AI is not available right now. [quote] The procedure says: "While a hurricane w |
| AB-NEAR-016 | near_miss | pl | wtr_comp_01 | notices-lifted | language, mentions_all, mentions_any | m2/llm_unavailable | Answer from platform data. The AI is not available right now. [DC-D2-CREWS-AIK] DC-D2-CREWS-AIK: decided on ti |
