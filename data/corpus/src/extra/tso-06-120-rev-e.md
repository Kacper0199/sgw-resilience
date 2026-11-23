---
doc_id: "TSO 06.120"
title: "Substation Flood Protection and Pre-Storm Securing"
family: sop
layout: controlled
owner_function: operations
sme: "Ingle, Prentice W."
revision: "E"
effective: 2024-05-06
supersedes: "TSO 06.120 Rev D (eff. 2022-06-06)"
next_review: 2025-04-30
approvals:
  - {function: transmission, position: "Manager, Transmission Operations", name: "Pettigrew, Anselm K.", date: 2024-04-29}
  - {function: command, position: "Vice President, Emergency Management", name: "Wingard, Lorraine T.", date: 2024-04-30}
classification: "SGW Restricted - Operations"
trust: verified_internal
status: in_force
decisions: [D1, D3]
states: [SC, GA]
changes:
  - {rev: "E", date: 2024-05-06, section: "Att. A", change: "SUB-AIK-GADSBYNECK flood barrier height raised to 3.5 ft after 2023 survey."}
  - {rev: "E", date: 2024-05-06, section: "6.3", change: "Camera and intrusion alarm check added to the H-48 securing list."}
  - {rev: "E", date: 2024-05-06, section: "Att. B", change: "Security patrol contact moved to Corporate Security dispatch."}
---
# 1.0 PURPOSE

Sets the pre-storm flood protection and physical securing of SGW substations, and the flood elevations that
decide when a substation is de-energized.

# 2.0 SCOPE

Transmission and distribution substations listed in Attachment A. Distribution of this document is limited
to Transmission Operations, Substation Operations, Corporate Security and the EOC Command Staff.

# 3.0 RESPONSIBILITIES

3.1 The Substation Operations Supervisor for each area carries out sections 6.1 to 6.4.

3.2 The Manager, Transmission Operations decides on pre-emptive de-energizing of a flood-threatened station.

3.3 Corporate Security keeps camera, alarm and patrol coverage and responds to intrusion alarms.

3.4 The Duty Manager arranges alternate feeds for feeders served from a station that will be de-energized.

# 4.0 DEFINITIONS

Critical flood elevation (CFE): the water level, in feet NAVD88, at which water reaches the lowest
energized equipment or control house floor.
Action elevation: CFE less 1.0 ft. Reaching it starts the de-energizing decision.

# 5.0 PRECAUTIONS AND LIMITS

5.1 Do not enter a substation yard with standing water over 6 in without the Substation Operations
Supervisor's approval.

5.2 Do not leave a station energized when the forecast or observed water level is at or above the CFE.

5.3 Gates removed for barrier installation shall be replaced by a temporary locked panel before the crew
leaves.

5.4 Keys and badge overrides are signed out from Corporate Security only.

CAUTION: flood water inside a control house can disable battery chargers. Check DC voltage before and after
any flooding.

# 6.0 PROCEDURE

## 6.1 H-96 to H-72

6.1.1 Check the river and surge forecasts for each Attachment A station.

6.1.2 Confirm portable barrier sets and pumps are at the stations marked "Barrier" in Attachment A.

6.1.3 Fuel control-house generators to full.

## 6.2 H-72 to H-48

6.2.1 Install flood barriers where the forecast water level is within 2 ft of the barrier base.

6.2.2 Raise portable relay test sets, spares and records above the CFE or remove them.

6.2.3 Seal cable trench entries into the control house with expanding foam plugs.

## 6.3 H-48 to H-24: Securing

6.3.1 Walk the fence line. Repair gaps and secure loose material that could become windborne.

6.3.2 Check each perimeter camera view from the Corporate Security console and test the intrusion alarm on
the control house door.

6.3.3 Lock all gates with the high-security padlocks; record the lock serials on the securing sheet.

6.3.4 Confirm battery bank voltage and charger alarms are reporting to SCADA.

6.3.5 Report completion to the TOP shift supervisor.

## 6.4 During the Event

6.4.1 Monitor river gauges and the station water sensors every hour.

6.4.2 At the action elevation, the Manager, Transmission Operations decides on de-energizing.

6.4.3 De-energize under a switching order per TSO 06.110. Tell the Duty Manager which feeders are affected.

6.4.4 After water recedes, inspect and dry equipment before re-energizing. Do not re-energize equipment that
was submerged without a test by Substation Maintenance.

6.4.5 Where the station cannot return within 48 h, consider a mobile substation per DOM 14.170.

# 7.0 RECORDS

Securing sheets, lock serial logs, switching orders. Retain 5 years. Securing sheets are Restricted.

# 8.0 REFERENCES

TSO 06.110. DOM 14.170. GEP 2H.01. GEP 2F.01. NERC CIP-014 (physical security, where applicable).

<<PAGEBREAK>>
# ATTACHMENT A - Station Flood Elevations and Security Features

| Station | CFE (ft NAVD88) | Action elevation (ft) | Flood protection | Perimeter | Cameras | Intrusion alarm | Patrol during activation |
|---|---|---|---|---|---|---|---|
| SUB-AIK-BRAMBLEGATE 115-23 kV | 312.4 | 311.4 | None needed | 8 ft chain link, 3-strand barbed | 4 fixed, 1 PTZ | Control house door, gate | Every 6 h |
| SUB-AIK-GADSBYNECK 115-23 kV | 141.8 | 140.8 | Barrier 3.5 ft, 2 pumps | 10 ft anti-climb mesh | 6 fixed | Door, gate, fence sensor | Every 4 h |
| SUB-RCH-DORNICKLANDING 115-12 kV | 128.6 | 127.6 | Barrier 2.5 ft, 1 pump | 8 ft chain link | 3 fixed | Control house door | Every 6 h |
| SUB-CHS-HOLLISTERHAMMOCK 115-23 kV | 9.7 | 8.7 | Raised pads; barrier 3 ft | 10 ft anti-climb mesh | 6 fixed, 2 PTZ | Door, gate, fence sensor | Every 2 h |

# ATTACHMENT B - Contacts

| Position | Primary | After hours |
|---|---|---|
| TOP shift supervisor | Transmission control room | TCC shift supervisor, ext. 3305 |
| Corporate Security dispatch | Security operations center | Same, staffed 24 h, ext. 3711 |
| Substation Operations Supervisor | Area office | Substation on-call list in DocCtl |
