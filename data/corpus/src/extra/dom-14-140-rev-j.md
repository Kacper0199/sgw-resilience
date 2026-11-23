---
doc_id: "DOM 14.140"
title: "Critical Facility Registry"
family: sop
layout: controlled
owner_function: operations
sme: "Faircloth, Nadia S."
revision: "J"
effective: 2024-04-01
supersedes: "DOM 14.140 Rev H (eff. 2022-03-21)"
next_review: 2025-03-31
approvals:
  - {function: operations, position: "Director, Distribution Operations", name: "Thibodeaux, Marcus R.", date: 2024-03-25}
  - {function: water_operations, position: "Manager, Water Distribution", name: "Sistrunk, Odell M.", date: 2024-03-22}
classification: "SGW Internal - Controlled"
trust: verified_internal
status: in_force
decisions: [D3, D4]
states: [SC, GA]
changes:
  - {rev: "J", date: 2024-04-01, section: "5.0", change: "SGW water facilities given their own flag code CF-W; pump stations that supply a hospital zone flagged CF-1."}
  - {rev: "J", date: 2024-04-01, section: "6.3", change: "Annual verification moved from September to March, before hurricane season."}
  - {rev: "J", date: 2024-04-01, section: "Att. A", change: "No changes."}
---
# 1.0 PURPOSE

Defines the facility types SGW treats as critical and how they are flagged on feeders in the Outage
Management System (OMS) and the GIS. The registry is the source for the priority classes in DOM 14.215.

# 2.0 SCOPE

All facilities served by the SGW distribution system that meet a type in section 5. The registry holds
facility type, flag code, serving feeder, backup power status and a contact position. It does not hold
outage or restoration information for any facility.

# 3.0 RESPONSIBILITIES

3.1 The Critical Facility Registry Coordinator (Distribution Operations) maintains the registry and runs the
annual verification.

3.2 District account representatives submit additions, changes and removals on the registry change request.

3.3 The Water Incident Lead confirms the entries for SGW water and wastewater facilities.

3.4 GIS Services applies the feeder flags within 5 working days of an approved change.

3.5 County emergency management agencies may nominate facilities through the Liaison Officer.

# 4.0 DEFINITIONS

Critical facility: a facility whose loss of power threatens life, public health or emergency response.
Flag code: the registry class shown on the feeder and premise in OMS and GIS.
Feeder flag: the highest flag code of any facility on a feeder, shown on the feeder in OMS.

# 5.0 FACILITY TYPES AND FLAG CODES

| Flag code | Facility types | DOM 14.215 priority |
|---|---|---|
| CF-1 | Hospitals with inpatient beds; SGW water pump stations that supply a hospital pressure zone | 1 |
| CF-2 | 911 centers; county and SGW EOCs; designated shelters (when opened); fire and EMS stations | 2 |
| CF-W | Other SGW water treatment plants, booster stations, wells and wastewater lift stations | 3 |
| CF-3 | Nursing homes and assisted living; dialysis centers; police stations; jails | 3 |
| CF-4 | Telecom central offices and cell hubs; fuel terminals; radio and TV emergency alert stations | 3 |
| CF-5 | Schools and other buildings listed as shelter candidates but not yet opened | 4 |

5.1 A facility has one flag code. Where a facility fits two types, use the higher one.

5.2 A shelter is CF-5 until the county opens it, then CF-2 until it closes. The Liaison Officer reports each
opening and closing to the OMS desk.

5.3 Water facilities that supply a hospital zone are CF-1 even when the hospital has its own standby
generator. Hospital generators cover building power, not water supply.

# 6.0 PROCEDURE

## 6.1 Add or Change a Facility

6.1.1 The account representative submits the registry change request with the facility type, service point,
backup power details and contact position.

6.1.2 The Registry Coordinator checks the type against section 5 and assigns the flag code.

6.1.3 GIS Services flags the premise and updates the feeder flag.

6.1.4 The Registry Coordinator confirms the flag shows in OMS.

## 6.2 Feeder Flagging

6.2.1 The feeder flag shall be the highest flag code of any facility on the feeder, including facilities on
laterals and those supplied by alternate feed.

6.2.2 A facility with automatic transfer to a second feeder is flagged on both feeders.

6.2.3 OMS shows the feeder flag in the outage list, the switching view and the load-shed roster used by
TSO 11.002.

6.2.4 Damage assessment patrols feeder trunks with CF-1 and CF-2 flags right after transmission and
substations (DOM 14.110).

## 6.3 Annual Verification

6.3.1 By 31 March each year, confirm each facility's type, contact and backup power with the facility.

6.3.2 Remove facilities that have closed. Record the reason.

6.3.3 Send the verified registry extract to the Duty Manager and the Water Incident Lead.

# 7.0 RECORDS

Registry change requests and verification records. Retain 5 years.

# 8.0 REFERENCES

DOM 14.110. DOM 14.215. TSO 11.002. WDS 03.318. GEP 04.010. PCN 03.010.

<<PAGEBREAK>>
# ATTACHMENT A - Registry Entries, Aiken District Feeders (extract)

| Feeder | Feeder flag | Facility | Flag code | Backup power |
|---|---|---|---|---|
| FDR-AIK-2207 | CF-1 | HSP-AIK-TALLOWBRANCH Tallow Branch hospital | CF-1 | GEN-HSP-TALLOWBRANCH (building only) |
| FDR-AIK-2207 | CF-1 | PS-17 Pellicott Road Booster (supplies WZ-PS17-CEDARFALL) | CF-1 | None onsite; portable per WDS 03.318 |
| FDR-AIK-2214 | CF-W | PS-23 Laurel Spur booster | CF-W | None onsite |
| FDR-AIK-2219 | CF-3 | DLY-AIK-RUDDELLLANDING dialysis center | CF-3 | Facility generator |
| FDR-AIK-2225 | CF-2 | County 911 center | CF-2 | Facility generator, ATS |
| FDR-AIK-2231 | CF-W | PS-38 Copperleaf booster | CF-W | GEN-PS38-COPPERLEAF |
| FDR-AIK-2238 | CF-W | PS-52 Deerwater booster | CF-W | GEN-PS52-DEERWATER |

# ATTACHMENT B - Contacts

| Position | Primary | After hours |
|---|---|---|
| Critical Facility Registry Coordinator | Distribution Operations, Columbia | Distribution Control Center, ext. 2262 |
| Water Incident Lead | Water Operations Center | Water on-call, ext. 7128 |
