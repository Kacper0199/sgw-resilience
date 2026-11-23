---
doc_id: "DOM 14.190"
title: "Outage Management System Degraded Operations"
family: sop
layout: controlled
owner_function: operations
sme: "Varnadoe, Celeste M."
revision: "B"
effective: 2024-07-15
supersedes: "DOM 14.190 Rev A (eff. 2023-02-27)"
next_review: 2025-06-30
approvals:
  - {function: operations, position: "Director, Distribution Operations", name: "Thibodeaux, Marcus R.", date: 2024-07-08}
  - {function: planning, position: "Manager, Storm Planning", name: "Okonkwo, Adaeze N.", date: 2024-07-09}
classification: "SGW Internal - Controlled"
trust: verified_internal
status: in_force
decisions: [D4]
states: [SC, GA]
changes:
  - {rev: "B", date: 2024-07-15, section: "5.0", change: "Degraded Mode 2 added for loss of AMI last-gasp messages with OMS still available."}
  - {rev: "B", date: 2024-07-15, section: "6.4", change: "Back-entry of paper tickets required within 12 h of OMS recovery."}
---
# 1.0 PURPOSE

Sets how the storm room keeps working when the Outage Management System (OMS), or one of its feeds, is slow
or unavailable.

# 2.0 SCOPE

District storm rooms, DCC storm desks, the OMS desk and the Planning Section outage counts. IT recovery of
OMS itself follows the IT incident process.

# 3.0 RESPONSIBILITIES

3.1 The OMS desk lead declares the degraded mode and tells the Duty Manager.

3.2 The Duty Manager decides on the move to paper tickets and informs the EOC.

3.3 The Planning Section keeps outage counts by district from the fallback sources in section 6.3.

3.4 IT Service Desk (Operations Technology) restores OMS and reports progress every 30 min.

# 4.0 DEFINITIONS

AMI last-gasp: the outage message a meter sends when it loses power.
Paper ticket: the printed trouble ticket on the storm room pad, numbered in sequence per district.
Back-entry: keying paper tickets into OMS after recovery.

# 5.0 DEGRADED MODES

| Mode | Condition | Action |
|---|---|---|
| 1 Slow | OMS screen response over 30 s, or prediction engine more than 15 min behind | Continue in OMS; stop non-storm queries; OMS desk monitors |
| 2 Partial feed loss | AMI last-gasp or IVR feed lost; OMS available | Enter calls manually; SCADA breaker status checked every 15 min |
| 3 OMS unavailable | No OMS access for 20 min or more, or IT declares an outage | Paper tickets per 6.2 |
| 4 OMS and SCADA unavailable | No OMS and no SCADA status | Paper tickets; crews report device status by radio every 30 min |

# 6.0 PROCEDURE

## 6.1 Declare

6.1.1 The OMS desk lead declares the mode with the time (EDT) on the storm room board.

6.1.2 The Duty Manager tells the EOC on the command bridge.

6.1.3 Corporate Communications is told when outage map updates will stop (PCN 02.050).

## 6.2 Paper Tickets (Modes 3 and 4)

6.2.1 Open a new paper ticket pad for each district. Start at the next number after the last OMS ticket.

6.2.2 Record on each ticket: time, source, feeder, device or pole, damage seen, crew assigned.

6.2.3 Mark downed-wire calls in red. Wire guard dispatch continues per DOM 14.120.

6.2.4 Keep a switching log on paper. Switching orders are written out and repeated back per TSO 06.110.

6.2.5 Critical facility flags are read from the printed registry extract (DOM 14.140 section 6.3).

NOTE: the printed registry extract is kept in the storm room binder and replaced each March.

## 6.3 Outage Counts without OMS

6.3.1 Count customers out by feeder from SCADA breaker and recloser status, using the feeder customer table
printed weekly from GIS.

6.3.2 Add laterals and transformers reported out by crews.

6.3.3 The Planning Section reports the count to the EOC every 2 h, marked "manual count".

6.3.4 The ETR Specialist uses the manual count for the global ETR model under DOM 14.206 and records the
data source.

## 6.4 Recovery

6.4.1 IT confirms OMS is available and the feeds are current.

6.4.2 The OMS desk lead returns the room to normal mode and records the time.

6.4.3 Back-enter all paper tickets within 12 h of recovery, oldest first.

6.4.4 Compare OMS outage counts with the manual count. Report differences over 5 percent to the Planning
Section Chief.

6.4.5 File the paper pads with the incident record.

# 7.0 RECORDS

Paper ticket pads, paper switching logs, manual count sheets. Retain 7 years with the incident file.

# 8.0 REFERENCES

DOM 14.105. DOM 14.120. DOM 14.140. DOM 14.206. TSO 06.110. PCN 02.050. GEP 04.010.

<<PAGEBREAK>>
# ATTACHMENT A - Contacts

| Position | Primary | After hours |
|---|---|---|
| OMS desk lead | Storm room | Distribution Control Center, ext. 2262 |
| IT Service Desk, Operations Technology | OT service line | OT on-call, ext. 3890 |
| Planning Section Chief | EOC desk 4 | EM on-call phone, ext. 4417 |
