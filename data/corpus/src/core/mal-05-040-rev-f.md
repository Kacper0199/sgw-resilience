---
doc_id: "MAL 05.040"
title: "Fuel and Portable Generator Logistics"
family: sop
layout: controlled
owner_function: logistics
sme: "Faircloth, Nadia S."
revision: "F"
effective: 2024-05-27
supersedes: "MAL 05.040 Rev E (eff. 2023-05-22)"
next_review: 2025-05-31
approvals:
  - {function: logistics, position: "Logistics Section Chief; Manager, Supply Chain", name: "Huggins, Delmar J.", date: 2024-05-20}
  - {function: water_operations, position: "Water Incident Lead; Manager, Water Distribution", name: "Sistrunk, Odell M.", date: 2024-05-21}
classification: "SGW Internal - Controlled"
trust: verified_internal
status: in_force
decisions: [D3]
states: [SC, GA]
changes:
  - {rev: "F", date: 2024-05-27, section: "6.3", change: "Fuel source selection rule added: SGW truck first when vendor time exceeds remaining run time."}
  - {rev: "F", date: 2024-05-27, section: "Att. A", change: "FTK-WREN-3 load and drive time planned at 90 min."}
  - {rev: "F", date: 2024-05-27, section: "Att. B", change: "Vendor allocation table aligned with contract MAL-CTR-0447 renewal."}
---
# 1.0 PURPOSE

This procedure sets how Logistics dispatches portable generators and delivers diesel to SGW standby and portable generators during declared events.

# 2.0 SCOPE

Applies to water pump stations, lift stations, tanks with powered controls, and electric facilities that run on generator power. Does not apply to customer-owned generators, including hospital standby units such as GEN-HSP-TALLOWBRANCH.

# 3.0 RESPONSIBILITIES

Logistics Section Chief: owns the fuel plan, vendor call-outs and the generator dispatch log.
Fuel Coordinator (Logistics): receives F-MAL-022 requests, chooses the fuel source, tracks each delivery to completion.
Water Incident Lead: sets generator priority among water facilities and requests portable generators.
Depot Supervisor, DEP-AIK-GRANITEVILLE: loads FTK-WREN-3 and readies MGEN-HALBERD-500 for transport.

# 4.0 DEFINITIONS

Remaining run time: hours of fuel left at the current load, from the tank gauge reading and the unit's burn rate in Attachment A.
Declared event: any event with Activation Level 3 or higher under GEP 00.010.

# 5.0 PRECAUTIONS AND LIMITS

5.1 Altamaha Fuel & Lube delivers within 18 h of a call during a declared event (contract MAL-CTR-0447). Outside a declared event the contract time is 24 h.
5.2 SGW fuel truck FTK-WREN-3 is based at DEP-AIK-GRANITEVILLE; load and drive time is planned at 90 min.
5.3 FTK-WREN-3 carries 2,800 gal of ULSD. Do not dispatch it to a site whose access road is listed in GEP 2F.01 Attachment 2 while a Flood Warning is in effect.
5.4 Portable generator MGEN-HALBERD-500 (500 kW) is kept at the Graniteville depot DEP-AIK-GRANITEVILLE.
5.5 Transport of MGEN-HALBERD-500 needs the lowboy tractor and a CDL Class A driver.

# 6.0 PROCEDURE

## 6.1 Requests

6.1.1 Generator dispatch and fuel requests are made on form F-MAL-022 and logged by Logistics.
6.1.2 The requester gives facility id, generator id, gauge reading, time of reading and load (kW).
6.1.3 Fuel Coordinator computes remaining run time from Attachment A.

## 6.2 Generator dispatch

6.2.1 Water Incident Lead confirms the target site and the connection point per WDS 03.318.
6.2.2 Depot Supervisor starts load-out and reports departure time to Logistics.
6.2.3 Logistics logs dispatched, on-site and running times against the F-MAL-022 number.
6.2.4 NOTE: Hookup and start-up times are set by WDS 03.318 section 6.4, not by this procedure.

## 6.3 Fuel source selection

6.3.1 Compare the vendor delivery time with the generator's remaining run time.
6.3.2 Where the vendor delivery time is longer than a generator's remaining run time, the SGW fuel truck is used first.
6.3.3 Call Altamaha for the next delivery to the same site at the same time, so the truck can be released.
6.3.4 Where two sites compete for FTK-WREN-3, the Water Incident Lead sets the order. Sites serving a hospital or critical facility per DOM 14.140 go first.
6.3.5 CAUTION: Do not fuel a running generator unless the unit is rated for hot refuelling.

## 6.4 Records of delivery

6.4.1 Driver records gallons delivered, gauge before and after, and time (24-hour EDT).
6.4.2 Vendor delivery tickets are scanned to the F-MAL-022 record within 12 h.

# 7.0 RECORDS

F-MAL-022 forms, vendor tickets and the dispatch log are retained 6 years by Logistics.

# 8.0 REFERENCES

WDS 03.318; GEP 2F.01; GEP 00.010; DOM 14.140; MAL-CTR-0447 contract summary; F-MAL-022.

<<PAGEBREAK>>
# ATTACHMENT A - FUEL ASSETS AND BURN RATES

| Asset | Base | Capacity | Burn rate source | Planning time |
|---|---|---|---|---|
| FTK-WREN-3 fuel truck | DEP-AIK-GRANITEVILLE | 2,800 gal | n/a | 90 min load and drive |
| MGEN-HALBERD-500 (500 kW) | DEP-AIK-GRANITEVILLE | belly tank, per nameplate | nameplate curve, unit binder | hookup per WDS 03.318 |
| GEN-PS38-COPPERLEAF | PS-38 Copperleaf | per WDS 03.350 load test sheet | WDS 03.350 load test sheet | n/a |
| GEN-PS52-DEERWATER | PS-52 Deerwater | per WDS 03.350 load test sheet | WDS 03.350 load test sheet | n/a |

# ATTACHMENT B - VENDOR ALLOCATION

| Vendor | Contract | Delivery time, declared event (h) | Delivery time, normal (h) | Call-out |
|---|---|---|---|---|
| Altamaha Fuel & Lube | MAL-CTR-0447 | 18 | 24 | Dispatch desk, 24 h line; after hours page the on-call dispatcher |
