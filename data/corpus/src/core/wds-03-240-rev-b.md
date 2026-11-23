---
doc_id: "WDS 03.240"
title: "Tank Drawdown and Zone Isolation"
family: sop
layout: controlled
owner_function: water_operations
sme: "Strom, Booker J."
revision: "B"
effective: 2024-08-19
supersedes: "WDS 03.240 Rev A (eff. 2021-09-13)"
next_review: 2025-07-31
approvals:
  - {function: water_operations, position: "Water Incident Lead; Manager, Water Distribution", name: "Sistrunk, Odell M.", date: 2024-08-08}
  - {function: compliance, position: "Water Compliance Officer", name: "Quattlebaum, Rhea D.", date: 2024-08-12}
classification: "SGW Internal - Controlled"
trust: verified_internal
status: in_force
decisions: [D3]
states: [SC, GA]
changes:
  - {rev: "B", date: 2024-08-19, section: "6.1", change: "Drawdown tracking interval reduced from 30 min to 15 min."}
  - {rev: "B", date: 2024-08-19, section: "6.3", change: "Hospital tanker planning time of 120 min added."}
  - {rev: "B", date: 2024-08-19, section: "6.4", change: "Isolation valve orders recorded on F-WDS-212."}
---
# 1.0 PURPOSE

This procedure covers serving a pressure zone from its elevated tank after its booster station loses power, and isolating part of a zone.

# 2.0 SCOPE

Zones with an elevated tank and a single booster. Ground storage and clearwells are covered by plant procedures.

# 3.0 RESPONSIBILITIES

Water Incident Lead: orders isolation valve operations and tanker requests.

Water SCADA Operator: tracks tank level and forecasts the time to the residual-pressure limit.

Water Distribution Crew Leader: operates valves and records each operation.

Logistics Section Chief: sources and dispatches potable-water tankers.

# 4.0 DEFINITIONS AND ABBREVIATIONS

Residual-pressure limit: the tank level at which the zone critical point reaches the state floor in WDS 03.105. Values are in Attachment A.

Time to limit: (current level minus limit level) divided by the drawdown rate.

# 5.0 PRECAUTIONS AND LIMITS

5.1 Isolation valves are closed only on the Water Incident Lead's order. The order is recorded on F-WDS-212.

5.2 Close large valves (16 in and above) at no more than 10 turns per minute to limit surge.

5.3 Never isolate a zone segment that contains a hospital or dialysis centre without an alternate supply in place.

# 6.0 PROCEDURE

## 6.1 Drawdown Tracking

6.1.1 When a booster station loses power, serve the zone from its elevated tank until the level reaches the residual-pressure limit.

6.1.2 Track the drawdown every 15 min. Report level, rate and time to limit to the Water Incident Lead.

6.1.3 If the rate exceeds the Attachment A planning rate by 25 percent, look for a main break.

6.1.4 Ask Communications for a voluntary conservation message for the zone (PCN 02.050).

## 6.2 Isolation

6.2.1 Propose the segment to isolate, with valve numbers, to the Water Incident Lead.

6.2.2 On the order, record the order time and the ordering position on F-WDS-212.

6.2.3 Operate valves in the listed sequence. Record turns and time per valve.

6.2.4 Report "segment isolated" and the customer count affected.

## 6.3 Hospital Supply

6.3.1 A potable-water tanker to a hospital needs 120 min from request to connection.

6.3.2 Request the tanker when time to limit is less than 120 min plus 30 min margin.

6.3.3 For Tallow Branch hospital (HSP-AIK-TALLOWBRANCH), connect at the fire-department connection on the east dock.

6.3.4 Sample the tanker for free chlorine before connection; minimum 0.2 mg/L.

## 6.4 Restoration

6.4.1 Open valves only on the Water Incident Lead's order, recorded on F-WDS-212.

6.4.2 Refill the tank before returning the zone to normal pressure settings.

6.4.3 Flush per WDS 03.420 where pressure fell below the floor.

# 7.0 RECORDS

F-WDS-212 Valve Operation Record; SCADA tank trend. Retain 5 years.

# 8.0 REFERENCES

WDS 03.105; WDS 03.318; WDS 03.205; WDS 03.420; PCN 02.050; DOM 14.140

<<PAGEBREAK>>
# ATTACHMENT A TANK PLANNING DATA

| Tank | Zone | Overflow level (ft) | Residual-pressure limit (ft) | Planning drawdown (ft/h) |
|---|---|---|---|---|
| TNK-PS17-CEDARFALL | WZ-PS17-CEDARFALL | 38.0 | 14.5 | 3.1 |
| TNK-PS23-LAURELSPUR | WZ-PS23-LAURELSPUR | 32.0 | 12.0 | 2.4 |
| TNK-PS38-COPPERLEAF | WZ-PS38-COPPERLEAF | 35.0 | 11.5 | 2.7 |
| TNK-PS52-DEERWATER | WZ-PS52-DEERWATER | 30.0 | 10.0 | 1.9 |

Planning rates are average-day demand. Use 1.4 times the rate on a hot day.

# ATTACHMENT B TANKER SOURCES AND CONTACTS

| Source | Capacity (gal) | Base | Day | After hours |
|---|---|---|---|---|
| SGW potable tanker PWT-AIK-CANEBRAKE | 5,500 | DEP-AIK-GRANITEVILLE | Logistics desk 803-641-3315 | EOC Logistics desk 803-641-3300 |
| SGW potable tanker PWT-RCH-SPIRITCREEK | 4,000 | Richmond water yard | Logistics desk 803-641-3315 | EOC Logistics desk 803-641-3300 |
| Water Incident Lead | | | 803-641-2270 | Water Control Room 803-641-2299 |

Tankers are kept filled, chlorinated and sealed from 1 June to 30 November. Logistics confirms the seal number at release.
