# Ask bank report: r1-smoke-rerun

Commit `4dd225a`, split `dev`, gateway `replay_then_live`, wave `R34`, started 2026-11-22T07:26:56Z, 72.5 s.

**Pass 6/7 = 0.86**; without the 1 infra misses (harness error, no model answer): 5/6 = 0.83. Spend 0.967 USD (37 live calls, 0.1381 USD/item); latency p50 17.7 s, p95 37.99 s; errors 0.

Grader failures: mentions_any 1.
Answer paths: llm 4, not_in_documents 2, m2 1.
Reasons: None 4, model_not_in_documents 2, llm_unavailable 1.

### By class

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| data | 1 | 1 | 1.00 |
| explain | 1 | 1 | 1.00 |
| followup | 1 | 1 | 1.00 |
| near_miss | 2 | 2 | 1.00 |
| overview | 0 | 1 | 0.00 |
| role | 1 | 1 | 1.00 |

### By persona

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| audit_01 | 1 | 1 | 1.00 |
| exec_01 | 1 | 2 | 0.50 |
| plan_etr_01 | 1 | 1 | 1.00 |
| wtr_comp_01 | 3 | 3 | 1.00 |

### By language

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| en | 4 | 4 | 1.00 |
| pl | 2 | 3 | 0.67 |

### By moment

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| notices-lifted | 6 | 7 | 0.86 |

### By page

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| after_action | 2 | 2 | 1.00 |
| brief | 0 | 1 | 0.00 |
| forecast | 1 | 1 | 1.00 |
| water | 3 | 3 | 1.00 |

### By split

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| dev | 6 | 7 | 0.86 |

### By tag

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| demo_moment | 1 | 1 | 1.00 |
| no_diacritics | 0 | 1 | 0.00 |
| vague | 0 | 1 | 0.00 |

### Failed items

| Id | Class | Lang | Persona | Moment | Failed | Path/reason | Answer (start) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AB-OVR-023 | overview | pl | exec_01 | notices-lifted | mentions_any | llm/None | Prąd: w hrabstwach objętych burzą bez zasilania jest 168,598 klientów, trend spada. Woda: ciśnienie w stacjach |
