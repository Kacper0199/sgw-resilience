---
doc_id: "GEP 2X.01"
title: "Extreme Heat Annex"
family: annex
layout: controlled
owner_function: command
sme: "Bazemore, Tamsin L."
revision: "B"
effective: 2024-05-28
supersedes: "GEP 2X.01 Rev A (eff. 2023-06-05)"
next_review: 2025-04-30
approvals:
  - {function: command, position: "Vice President, Emergency Management", name: "Wingard, Lorraine T.", date: 2024-05-20}
  - {function: water_operations, position: "Manager, Water Distribution", name: "Sistrunk, Odell M.", date: 2024-05-17}
  - {function: operations, position: "Director, Distribution Operations", name: "Thibodeaux, Marcus R.", date: 2024-05-17}
classification: "SGW Internal - Controlled"
trust: verified_internal
status: in_force
decisions: [D1, D3]
states: [SC, GA]
changes:
  - {rev: "B", date: 2024-05-28, section: "5.2", change: "Crew work-rest cycle at heat index 108 F and above changed to 30 min work, 30 min rest."}
  - {rev: "B", date: 2024-05-28, section: "6.0", change: "Water demand triggers added for elevated tanks below 55 percent at 0500."}
  - {rev: "B", date: 2024-05-28, section: "Att. 1", change: "Cooling center contacts moved to county liaison packet (PCN 03.010)."}
---
# 1.0 PURPOSE

This annex adds heat-specific actions to the base ERP. Activation, Event Types and Activation Levels follow
GEP 00.010.

# 2.0 SCOPE

Applies when the National Weather Service (NWS) issues a Heat Advisory or an Excessive Heat Warning for any
county in the service area, or when SGW forecasts system peak load above 97 percent of the seasonal peak.

# 3.0 HAZARD SUMMARY

Extreme heat raises electric load, loads distribution transformers beyond nameplate for many hours, and
lowers crew endurance. Water demand rises in the late afternoon and tank recovery overnight is slower. Heat
events often end with afternoon thunderstorms that cause outages on already loaded feeders; outages that
follow are restored with cold load pickup limits in DOM 14.130.

# 4.0 TRIGGERS AND ACTIVATION

| Condition | Default Activation Level | Lead position |
|---|---|---|
| NWS Heat Advisory, one or more counties | 4 Monitoring | Duty Manager |
| NWS Excessive Heat Warning, or heat index 110 F forecast for 2 days | 3 Partial Activation | Incident Commander |
| Excessive Heat Warning plus Transmission Operator energy emergency alert | 2 Elevated Activation | Incident Commander |

The Event Type is set only if outages develop. A heat event with few outages stays Event Type 4 even at
Activation Level 3.

# 5.0 ACTIONS BY PHASE

## 5.1 Phase Table

| Day | Section | Position | Task | Output |
|---|---|---|---|---|
| D-3 | Command | Incident Commander | Hold weather call; set Activation Level | F-GEP-012 entry |
| D-3 | Operations | Duty Manager | List feeders above 90 percent of rating at last peak | Feeder watch list |
| D-2 | Logistics | Logistics Section Chief | Order ice, water and electrolyte drinks for crews and yards | ICS 213RR |
| D-2 | Water | Water Incident Lead | Confirm standby generators tested in the last 31 days (WDS 03.350) | Generator readiness list |
| D-1 | Operations | Manager, Transmission Operations | Confirm load-shed blocks and exclusions per TSO 11.002 | Load-shed roster |
| D-1 | Planning | Planning Section Chief | Stage transformer stock per DOM 14.160 section 5 | Stores order |
| D0 | Operations | Duty Manager | Apply crew work-rest cycle (5.2) | Tailboard records |
| D0 | Water | Water Incident Lead | Track tank levels at 0500 and 1700 | Tank log |
| D+1 | Command | Incident Commander | Step down per GEP 07.010 | F-GEP-012 entry |

## 5.2 Crew Heat Stress

5.2.1 Supervisors shall hold a heat tailboard at the start of each shift when the heat index is forecast at
95 F or above.

5.2.2 Crews shall follow the work-rest cycle below. The heat index is taken from the NWS hourly forecast for
the work location.

| Heat index (F) | Work (min) | Rest in shade or cab (min) | Water per worker |
|---|---|---|---|
| 95 to 102 | 50 | 10 | 1 cup every 20 min |
| 103 to 107 | 45 | 15 | 1 cup every 15 min |
| 108 and above | 30 | 30 | 1 cup every 15 min |

5.2.3 Mutual-aid crews new to the region work a reduced first day: no more than 10 h.

5.2.4 Any worker with heat illness signs stops work. Call 911 for confusion or loss of consciousness.

CAUTION: arc-rated clothing remains required. Heat does not justify removing it.

# 6.0 WATER SYSTEM ACTIONS

6.1 When an elevated tank is below 55 percent at 0500, the Water Incident Lead shall request a voluntary
conservation message through Corporate Communications (PCN 02.050).

6.2 Booster stations with portable generator connections, PS-17 Pellicott Road included, shall have the
portable unit assignment confirmed per WDS 03.318 before D0.

6.3 Generator run-time and refuel follow WDS 03.322. Generator output falls in high ambient temperature;
check derating tables before connecting a unit near its rating.

6.4 Pressure below the state minimum is handled per WDS 03.105.

# 7.0 ELECTRIC SYSTEM ACTIONS

7.1 The Duty Manager should defer planned outages on feeders on the watch list.

7.2 Overloaded transformer failures are replaced per DOM 14.160 with the next larger standard size where the
load history supports it.

7.3 Critical facilities on the watch list are identified from the registry in DOM 14.140.

# 8.0 REFERENCES

GEP 00.010. GEP 07.010. DOM 14.130. DOM 14.140. DOM 14.160. TSO 11.002. WDS 03.105. WDS 03.318. WDS 03.322.
WDS 03.350. PCN 02.050. PCN 03.010. 29 CFR 1910.269 (general training and medical provisions).

<<PAGEBREAK>>
# ATTACHMENT 1 - Reserved

Cooling center contacts are issued in the county liaison packet (PCN 03.010).
