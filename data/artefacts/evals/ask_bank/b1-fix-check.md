# Ask bank report: b1-fix-check

Commit `6b01f39`, split `dev`, gateway `replay_then_live`, wave `R34`, started 2026-11-22T03:54:42Z, 39.5 s.

**Pass 3/4 = 0.75**; without the 0 infra misses (harness error, no model answer): 3/4 = 0.75. Spend 0.085 USD (10 live calls, 0.0213 USD/item); latency p50 8.56 s, p95 10.87 s; errors 0.

Grader failures: mentions_any 1.
Answer paths: guide 2, llm 2.
Reasons: None 4.

### By class

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| explain | 0 | 1 | 0.00 |
| followup | 1 | 1 | 1.00 |
| navigate | 1 | 1 | 1.00 |
| role | 1 | 1 | 1.00 |

### By persona

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| exec_01 | 0 | 1 | 0.00 |
| log_01 | 1 | 1 | 1.00 |
| ops_dm_01 | 1 | 1 | 1.00 |
| plan_etr_01 | 1 | 1 | 1.00 |

### By language

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| de | 0 | 1 | 0.00 |
| en | 2 | 2 | 1.00 |
| pl | 1 | 1 | 1.00 |

### By moment

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| at-n1 | 3 | 4 | 0.75 |

### By page

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| crews | 1 | 1 | 1.00 |
| decisions | 1 | 1 | 1.00 |
| forecast | 1 | 2 | 0.50 |

### By split

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| dev | 3 | 4 | 0.75 |

### By tag

| Group | Pass | n | Rate |
| --- | ---: | ---: | ---: |
| link_request | 2 | 2 | 1.00 |
| no_diacritics | 1 | 1 | 1.00 |
| other_language | 0 | 1 | 0.00 |

### Failed items

| Id | Class | Lang | Persona | Moment | Failed | Path/reason | Answer (start) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| AB-EXP-037 | explain | de | exec_01 | at-n1 | mentions_any | guide/None | ETR steht für "Estimated Time of Restoration", also den voraussichtlichen Zeitpunkt, zu dem die Kundinnen und  |
