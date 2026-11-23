---
doc_id: "DOM 14.170"
title: "Mobile Substation Deployment"
family: sop
layout: controlled
owner_function: operations
sme: "Lumpkin, Harlan E."
revision: "C"
effective: 2023-06-12
supersedes: "DOM 14.170 Rev B (eff. 2021-04-19)"
next_review: 2024-12-31
approvals:
  - {function: transmission, position: "Manager, Transmission Operations", name: "Pettigrew, Anselm K.", date: 2023-06-05}
  - {function: operations, position: "Director, Distribution Operations", name: "Thibodeaux, Marcus R.", date: 2023-06-06}
classification: "SGW Internal - Controlled"
trust: verified_internal
status: in_force
decisions: [D2, D4]
states: [SC, GA]
changes:
  - {rev: "C", date: 2023-06-12, section: "5.0", change: "MSUB-CORBETT-25 added to the fleet table."}
  - {rev: "C", date: 2023-06-12, section: "6.2", change: "Pre-move route survey required for every move over 40 mi."}
---
# 1.0 PURPOSE

Sets how SGW decides on, moves and connects a mobile substation when a distribution substation transformer
or bus is lost.

# 2.0 SCOPE

Mobile substations owned by SGW and those received through mutual assistance. Applies to 115-23 kV and
115-12 kV distribution substations.

# 3.0 RESPONSIBILITIES

| Position | Responsibility |
|---|---|
| Manager, Transmission Operations | Approves deployment; assigns the unit |
| Substation Operations Supervisor | Plans the site layout and connection; holds the clearance |
| Duty Manager | Requests the unit; plans feeder pickup |
| Logistics Section Chief | Arranges heavy haul, escorts and permits |
| Protection Engineer | Issues relay settings for the mobile |

# 4.0 DEFINITIONS

Mobile substation (MSUB): a trailer-mounted transformer with high-side and low-side switchgear and protection,
connected in place of a fixed transformer.

# 5.0 PRECAUTIONS AND LIMITS

5.1 Fleet:

| Unit | Rating (MVA) | Voltages (kV) | Home base | Set-up time after arrival (h) |
|---|---|---|---|---|
| MSUB-CORBETT-25 | 25 | 115-23 / 12.47 | DEP-AIK-GRANITEVILLE | 10 |
| MSUB-TURKEYCREEK-20 | 20 | 115-23 | STG-RLD-CONGAREEBEND-YARD | 12 |
| MSUB-PEEDEE-14 | 14 | 115-12.47 | STG-CHS-ASHLEYFERRY-YARD | 12 |

5.2 Load on the mobile shall not exceed its nameplate. Use the cold load pickup limits in DOM 14.130 when
feeders have been out 4 h or longer.

5.3 The site shall be above the flood elevation in TSO 06.120 Attachment A or protected to that elevation.

5.4 Do not move a mobile when sustained wind exceeds 40 mph on the route.

CAUTION: the mobile transformer is grounded to the station ground grid before any high-side connection.

# 6.0 PROCEDURE

## 6.1 Decide

6.1.1 The Duty Manager requests a mobile when the fixed transformer will be out longer than 48 h and feeders
cannot be carried on adjacent substations.

6.1.2 The Manager, Transmission Operations assigns the unit and records the decision in the incident log.

6.1.3 Restoration priority (DOM 14.215) guides which substation gets the unit when two request it.

## 6.2 Move

6.2.1 Logistics orders the heavy haul tractor, escorts and state oversize permits (SCDOT or GDOT).

6.2.2 For moves over 40 mi, survey the route for bridge limits, overhead clearance and flooding.

6.2.3 Check road closures on F-MAL-030 entries and county EOC reports.

## 6.3 Connect

6.3.1 Place the trailer per the site layout drawing in the substation file.

6.3.2 Bond the trailer to the station ground grid at two points.

6.3.3 Install relay settings from the Protection Engineer and test trip.

6.3.4 Connect high-side and low-side under a clearance per TSO 06.110. Ground per TSO 06.130.

6.3.5 Energize from the high side with low-side breakers open.

6.3.6 Pick up feeders one at a time per DOM 14.130.

## 6.4 Site Checks before Energizing

6.4.1 Confirm the trailer is level within 1 degree and the jacks are on cribbing.

6.4.2 Check oil level, nitrogen pressure and cooling fan operation.

6.4.3 Megger the high-side and low-side leads after connection.

6.4.4 Confirm SCADA points for the mobile breakers are reporting, or post a substation operator on site
until they are.

6.4.5 The Substation Operations Supervisor signs the pre-energizing checklist and tells the switching desk.

## 6.5 Return

Return the unit when the fixed transformer is back in service. Inspect, refill nitrogen or oil as needed,
and log hours under load.

# 7.0 RECORDS

Deployment log, relay setting sheets, switching orders, haul permits. Retain 5 years.

# 8.0 REFERENCES

DOM 14.130. DOM 14.215. TSO 06.110. TSO 06.120. TSO 06.130. GEP 2T.01. MAL 05.012.

# ATTACHMENT A - Contacts

| Position | Primary | After hours |
|---|---|---|
| Manager, Transmission Operations | Transmission control room | TCC shift supervisor, ext. 3305 |
| Substation Operations Supervisor | Area office | Substation on-call list in DocCtl |
| Logistics Section Chief (heavy haul) | EOC desk 6 | Supply Chain on-call, ext. 5521 |
