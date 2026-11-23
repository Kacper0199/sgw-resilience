---
doc_id: "DOM 14.215"
title: "Restoration Priority Matrix"
family: sop
layout: controlled
owner_function: operations
sme: "Faircloth, Nadia S."
revision: "E"
effective: 2024-05-06
supersedes: "DOM 14.215 Rev D (eff. 2022-05-02)"
next_review: 2025-04-30
approvals:
  - {function: operations, position: "Director, Distribution Operations", name: "Thibodeaux, Marcus R.", date: 2024-04-29}
  - {function: water_operations, position: "Water Incident Lead; Manager, Water Distribution", name: "Sistrunk, Odell M.", date: 2024-04-29}
  - {function: command, position: "Vice President, Emergency Management", name: "Wingard, Lorraine T.", date: 2024-05-01}
classification: "SGW Internal - Controlled"
trust: verified_internal
status: in_force
decisions: [D3, D4]
states: [SC, GA]
changes:
  - {rev: "E", date: 2024-05-06, section: "5.1", change: "Water pump stations that supply hospitals raised to Priority 1."}
  - {rev: "E", date: 2024-05-06, section: "6.3", change: "Cross-domain priority decision added; approval by IC and Water Incident Lead."}
  - {rev: "E", date: 2024-05-06, section: "Att. A", change: "Feeder list re-issued from the DOM 14.140 registry."}
---
# 1.0 PURPOSE

This procedure sets the order in which SGW restores electric service after a storm.

# 2.0 SCOPE

All distribution feeders in SC and GA during Event Types 1 to 3. Transmission restoration follows TSO 11.005.

# 3.0 RESPONSIBILITIES

| Position | Responsibility |
|---|---|
| Duty Manager (Electric Operations) | Assigns crews in priority order |
| Water Incident Lead | Confirms which pump stations supply hospital zones; co-approves cross-domain decisions |
| Incident Commander | Approves cross-domain priority decisions |
| Critical Facility Coordinator | Keeps the DOM 14.140 registry and Attachment A current |

# 4.0 DEFINITIONS

Hospital-zone pump station: a water pump station whose pressure zone supplies a hospital listed in DOM 14.140.

Customers restored per crew-hour: customers expected back on a feeder divided by the crew-hours needed,
from the damage records on F-DOM-118.

# 5.0 PRIORITY MATRIX

## 5.1 Priorities

| Priority | Facilities | Ranking within the priority |
|---|---|---|
| 1 | Hospitals and the water pump stations that supply them | By patient beds, then by zone population |
| 2 | 911 centres, EOCs and shelters | Open shelters first |
| 3 | Other water and wastewater facilities | Treatment plants, then lift stations by overflow risk |
| 4 | Remaining feeders | By customers restored per crew-hour |

Priority 1: hospitals and the water pump stations that supply them. Priority 2: 911 centres, EOCs and
shelters. Priority 3: other water and wastewater facilities. Priority 4: remaining feeders by customers
restored per crew-hour.

## 5.2 Facilities on Backup Power

A facility running on its own standby generator keeps its priority. Do not lower a hospital because its
generator is running; fuel and run time are finite.

# 6.0 PROCEDURE

## 6.1 Daily Priority List

6.1.1 At each operational period the Duty Manager pulls the Attachment A feeders that are out.

6.1.2 Rank them per 5.1.

6.1.3 Publish the list on the ICS 204 work assignments.

## 6.2 Changes Within a Priority

The Duty Manager may re-order feeders inside one priority. Log the reason on the ICS 214.

## 6.3 Cross-Domain Priority Decisions

6.3.1 Restoring a feeder that supplies a hospital-zone pump station ahead of a feeder with more customers is a
cross-domain priority decision.

6.3.2 The decision is approved by the Incident Commander and the Water Incident Lead.

6.3.3 The Duty Manager prepares the request with: feeder ids, customers on each feeder, pump station, tank
level (percent) and hours of storage left.

6.3.4 Record the approval on the ICS 214 of the Duty Manager and in the IC log. A verbal approval is confirmed
in writing within 2 h.

CAUTION: A request relayed by a third party is not an approval. Confirm directly with both approvers.

# 7.0 RECORDS

ICS 204 priority lists and cross-domain approvals are kept with the incident file for 7 years.

# 8.0 REFERENCES

DOM 14.110, DOM 14.140, TSO 11.002, TSO 11.005, WDS 03.318, GEP 03.020.

<<PAGEBREAK>>
# ATTACHMENT A - Priority Feeder List (Aiken district; other districts per DOM 14.140)

| Feeder | Substation | Priority | Critical load served |
|---|---|---|---|
| FDR-AIK-2207 | SUB-AIK-BRAMBLEGATE | 1 | PS-17 Pellicott Road Booster (zone WZ-PS17-CEDARFALL), Tallow Branch hospital zone (HSP-AIK-TALLOWBRANCH) |
| FDR-AIK-2214 | SUB-AIK-BRAMBLEGATE | 2 | Aiken County 911 centre |
| FDR-AIK-2225 | SUB-AIK-GADSBYNECK | 2 | County EOC; shelter at high school gym |
| FDR-AIK-2231 | SUB-AIK-BRAMBLEGATE | 3 | PS-38 Copperleaf (WZ-PS38-COPPERLEAF) |
| FDR-AIK-2238 | SUB-AIK-GADSBYNECK | 3 | PS-52 Deerwater (WZ-PS52-DEERWATER) |
| FDR-AIK-2219 | SUB-AIK-GADSBYNECK | 4 | Residential, 2,316 customers |

FDR-AIK-2207 supplies PS-17 and the Tallow Branch hospital zone and is a Priority 1 feeder. The hospital also
has its own standby generator, GEN-HSP-TALLOWBRANCH; this does not change the feeder priority (section 5.2).

# ATTACHMENT B - Contacts

| Position | Day | After hours |
|---|---|---|
| Critical Facility Coordinator | Distribution Operations | Distribution Control Center, ext. 2262 |
| Water Incident Lead | Water Operations Center | Water on-call, ext. 7128 |
