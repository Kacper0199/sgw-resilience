---
doc_id: "TSO 11.002"
title: "Load Shed Plan (EOP-011 Operating Plan)"
family: operating_plan
layout: controlled
owner_function: operations
sme: "Strom, Booker J."
revision: "D"
effective: 2024-01-29
supersedes: "TSO 11.002 Rev C (eff. 2023-03-27)"
next_review: 2025-01-31
approvals:
  - {function: transmission, position: "Manager, Transmission Operations", name: "Pettigrew, Anselm K.", date: 2024-01-22}
  - {function: operations, position: "Director, Distribution Operations", name: "Thibodeaux, Marcus R.", date: 2024-01-22}
  - {function: command, position: "Vice President, Emergency Management", name: "Wingard, Lorraine T.", date: 2024-01-24}
classification: "SGW Internal - Controlled"
trust: verified_internal
status: in_force
decisions: [D1]
states: [SC, GA]
changes:
  - {rev: "D", date: 2024-01-29, section: "5.5", change: "Extreme cold weather impact provisions added for EOP-011-2 R1.2.6."}
  - {rev: "D", date: 2024-01-29, section: "Att. 1", change: "FDR-AIK-2231 added to the excluded feeder list."}
  - {rev: "D", date: 2024-01-29, section: "Att. 3", change: "2024 annual review signed."}
---
# 1.0 PURPOSE

This is the SGW Transmission Operator Operating Plan to mitigate operating Emergencies under NERC EOP-011-2
Requirement R1. It covers manual load shed. It is reviewed by the Reliability Coordinator (RC) each year.

# 2.0 SCOPE

Applies to the SGW Transmission Operator Area in SC and GA and to distribution feeders assigned to load-shed
blocks. Automatic underfrequency load shed (UFLS) settings are in TSO 11.005 Attachment 6 and are not changed
by this plan.

# 3.0 ROLES AND RESPONSIBILITIES

| Position | Role in an Emergency |
|---|---|
| Transmission System Operator (on shift) | Declares the Emergency; orders load shed blocks |
| Manager, Transmission Operations | Activates this plan; reports to the RC |
| Distribution System Operator | Opens and restores block feeders on TSO order |
| Duty Manager (Electric Operations) | Informed at once; keeps critical-load feeders out of rotation |
| Incident Commander | Informed when shed exceeds 30 minutes or 2 blocks |

# 4.0 NOTIFICATIONS

4.1 Notify the RC before shedding load, or at once if shed is automatic or immediate.

4.2 Notify neighbouring TOPs and the Balancing Authority on the RC call.

4.3 Notify the Duty Manager and the PIO within 15 minutes.

# 5.0 MITIGATION STEPS

## 5.1 Outage Recall

Cancel or recall planned transmission and generation outages where this relieves the Emergency.

## 5.2 Reconfiguration

Reconfigure the transmission system per TSO 06.110 switching rules.

## 5.3 Redispatch

Request generation redispatch from the Balancing Authority.

## 5.4 Manual Load Shed

5.4.1 Shed load in rotating blocks from Attachment 2. Each block shall be shed within 10 minutes of the order.

5.4.2 Rotate blocks every 30 to 45 minutes to limit customer outage time.

5.4.3 Feeders serving hospitals and water pump stations are excluded from rotating load-shed blocks.
Attachment 1 lists FDR-AIK-2207 and FDR-AIK-2231.

5.4.4 Feeders with UFLS or UVLS relays are kept out of manual blocks where possible. Overlap is listed in
Attachment 2, column 5.

CAUTION: Do not place an excluded feeder in a block to meet a MW target. Use the next block instead.

## 5.5 Cold and Extreme Weather

Before a forecast cold snap below 20 F or a hurricane, the Manager, Transmission Operations reviews block MW
values against the forecast load and reissues Attachment 2 if any block changes by more than 15 percent.

# 6.0 RECORDS

Operator logs, RC call recordings and block rotation logs are kept for 3 years plus the current year.

# 7.0 REFERENCES

NERC EOP-011-2 R1. TSO 11.005. TSO 06.110. DOM 14.215 Attachment A. DOM 14.140.

<<PAGEBREAK>>
# ATTACHMENT 1 - Feeders Excluded from Rotating Load Shed (Aiken district)

| Feeder | Substation | Critical load | Basis |
|---|---|---|---|
| FDR-AIK-2207 | SUB-AIK-BRAMBLEGATE | PS-17 Pellicott Road Booster; Tallow Branch hospital zone (HSP-AIK-TALLOWBRANCH) | Hospital and water pump station |
| FDR-AIK-2231 | SUB-AIK-BRAMBLEGATE | PS-38 Copperleaf pump station | Water pump station |

Other districts: see DOM 14.140 registry extract held by the Transmission Control Center.

# ATTACHMENT 2 - Rotating Block Summary

| Block | Feeders (count) | Load at winter peak (MW) | Load at summer peak (MW) | UFLS overlap (feeders) |
|---|---|---|---|---|
| 1 | 23 | 148 | 131 | 0 |
| 2 | 21 | 139 | 126 | 1 |
| 3 | 24 | 152 | 137 | 0 |
| 4 | 19 | 127 | 118 | 2 |
| 5 | 22 | 144 | 129 | 0 |
| 6 | 20 | 133 | 121 | 1 |

# ATTACHMENT 3 - Requirement Cross-Reference and Review Signature Sheet

## Requirement cross-reference (EOP-011-2 R1)

| EOP-011-2 item | Subject | Plan section |
|---|---|---|
| R1.1 | Roles and responsibilities for activating the Operating Plan | 3.0 |
| R1.2.1 | Notification to the RC | 4.1, 4.2 |
| R1.2.2 | Cancellation or recall of transmission and generation outages | 5.1 |
| R1.2.3 | Transmission system reconfiguration | 5.2 |
| R1.2.4 | Redispatch of generation request | 5.3 |
| R1.2.5.1 | Manual load shed in an adequate timeframe | 5.4.1 |
| R1.2.5.2 | Minimize overlap with circuits serving critical loads | 5.4.3, Att. 1 |
| R1.2.5.3 | Minimize overlap with UFLS and UVLS circuits | 5.4.4, Att. 2 |
| R1.2.6 | Reliability impacts of cold and extreme weather | 5.5 |
| R1 (RC review) | Plan reviewed by the RC | Att. 3 signature sheet |

## Annual Review Signature Sheet

| Review year | Reviewed by (position) | Name | Date signed | Sent to RC |
|---|---|---|---|---|
| 2022 | Manager, Transmission Operations | Pettigrew, Anselm K. | 2022-01-18 | 2022-01-21 |
| 2023 | Manager, Transmission Operations | Pettigrew, Anselm K. | 2023-01-24 | 2023-01-26 |
| 2024 | Manager, Transmission Operations | Pettigrew, Anselm K. | 2024-01-22 | 2024-01-25 |

# ATTACHMENT 4 - Contacts

| Position | Day | After hours |
|---|---|---|
| Transmission System Operator | Transmission Control Center, console 1 | Same, staffed 24 h, ext. 2100 |
| Manager, Transmission Operations | TCC office | Transmission on-call, ext. 2104 |
