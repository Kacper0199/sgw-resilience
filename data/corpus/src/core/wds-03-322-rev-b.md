---
doc_id: "WDS 03.322"
title: "Standby Generator Fueling and Run-Time Monitoring"
family: sop
layout: controlled
owner_function: water_operations
sme: "Dukes, Merritt A."
revision: "B"
change: 1
effective: 2022-07-11
superseded_by: "WDS 03.322 Rev C (eff. 2024-06-17)"
next_review: 2023-05-31
approvals:
  - {function: water_operations, position: "Water Incident Lead; Manager, Water Distribution", name: "Sistrunk, Odell M.", date: 2022-06-28}
  - {function: logistics, position: "Logistics Section Chief; Manager, Supply Chain", name: "Huggins, Delmar J.", date: 2022-06-30}
classification: "SGW Internal - Controlled"
trust: verified_internal
status: superseded
decisions: [D3]
states: [SC, GA]
changes:
  - {rev: "B/1", date: 2023-01-23, section: "Att. B", change: "Vendor phone list updated. No other changes; approvals not re-collected."}
  - {rev: "B", date: 2022-07-11, section: "6.2", change: "Fuel reading interval reduced from 6 h to 4 h."}
  - {rev: "B", date: 2022-07-11, section: "Att. A", change: "GEN-PS52-DEERWATER added."}
---
# 1.0 PURPOSE

This procedure sets fuel monitoring and refuel requests for fixed standby generators at water facilities.

# 2.0 SCOPE

It applies to diesel standby generators at SGW booster and pump stations in South Carolina and Georgia. Covered units include GEN-PS38-COPPERLEAF and GEN-PS52-DEERWATER; the full list is in Attachment A.

It does not apply to portable generators. For PS-17 see WDS 03.318; for monthly load tests see WDS 03.350.

# 3.0 RESPONSIBILITIES

Water Incident Lead: approves refuel priority when several stations need fuel at once.

Station Operator: reads and logs fuel level, raises refuel requests.

Water SCADA Operator: watches remote tank-level signals and alerts the Station Operator.

Logistics Section Chief: assigns the vendor or the SGW fuel truck per MAL 05.040.

# 4.0 DEFINITIONS AND ABBREVIATIONS

Run time remaining: usable fuel divided by burn rate at current load.

Usable fuel: tank contents above the 10 percent pickup level.

# 5.0 PRECAUTIONS AND LIMITS

5.1 Never let a running unit fall below 25 percent tank. Below this level sediment pickup is likely.

5.2 Refuel request trigger: 50 percent tank.

5.3 Do not refuel a running unit from a vehicle without a bonding cable in place.

5.4 Use ultra-low sulfur No. 2 diesel only. Request winter blend from 1 November to 31 March.

# 6.0 PROCEDURE

## 6.1 Start of Run

6.1.1 When a unit starts on loss of grid supply, record the start time and fuel level on F-WDS-207.

6.1.2 Report the start to the Water Incident Lead.

6.1.3 Calculate run time remaining using the Attachment A burn rate.

## 6.2 Monitoring

6.2.1 Read and log the fuel level every 4 h on F-WDS-207 while the generator runs.

6.2.2 Read the sight gauge, not only the SCADA signal. Record both if they differ by more than 5 percent.

6.2.3 Log load (kW), oil pressure and coolant temperature with each fuel reading.

NOTE: At unmanned stations a roving operator may cover up to three stations. Keep the 4 h interval.

## 6.3 Refuel Request

6.3.1 When the fuel tank falls to 50 percent, raise a refuel request.

6.3.2 Submit the request on F-MAL-022 to the Logistics desk. State unit id, level, burn rate and route.

6.3.3 Flag any route that crosses a low-water crossing in GEP 2F.01 Attachment 2. Copperleaf Road (PS-38) and Deerwater Spur (PS-52) are on that list.

6.3.4 If run time remaining is shorter than the vendor delivery time, tell Logistics. Logistics then sends the SGW fuel truck first (MAL 05.040).

6.3.5 Log the delivery time and gallons received.

## 6.4 Shutdown

6.4.1 After return to grid supply, run unloaded for 5 min, then stop.

6.4.2 Top off to 95 percent within 24 hours.

# 7.0 RECORDS

F-WDS-207 Generator Run Log; F-MAL-022 fuel request. Retain 5 years.

# 8.0 REFERENCES

MAL 05.040 Fuel and Portable Generator Logistics
GEP 2F.01 Flood Annex, Attachment 2
WDS 03.350 Standby Generator Monthly Load Test

<<PAGEBREAK>>
# ATTACHMENT A COVERED UNITS

| Unit | Station | Rating (kW) | Tank (gal) | Burn at 75% load (gal/h) | Route |
|---|---|---|---|---|---|
| GEN-PS38-COPPERLEAF | PS-38 Copperleaf | 350 | 660 | 19.1 | Copperleaf Road |
| GEN-PS52-DEERWATER | PS-52 Deerwater | 275 | 540 | 15.3 | Deerwater Spur |
| GEN-BPS46-TANYARDBRANCH | BPS-46 Tanyard Branch Booster | 400 | 800 | 21.8 | Tanyard Branch Road |
| GEN-PS29-HOLLOWAYMILL | PS-29 Holloway Mill | 230 | 480 | 12.6 | Holloway Mill Road |

# ATTACHMENT B VENDOR CONTACTS

| Contact | Day | After hours |
|---|---|---|
| Altamaha Fuel & Lube dispatch (MAL-CTR-0447) | 912-427-3368 | 912-427-3341 |
| SGW Logistics desk | 803-641-3315 | EOC Logistics desk 803-641-3300 |
