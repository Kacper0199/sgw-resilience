---
doc_id: "TSO 11.005"
title: "System Restoration Plan Summary (EOP-005 Operating Plan)"
family: operating_plan
layout: controlled
owner_function: operations
sme: "Lumpkin, Harlan E."
revision: "H"
effective: 2024-03-11
supersedes: "TSO 11.005 Rev G (eff. 2023-03-06)"
next_review: 2025-02-28
approvals:
  - {function: transmission, position: "Manager, Transmission Operations", name: "Pettigrew, Anselm K.", date: 2024-03-01}
  - {function: command, position: "Vice President, Emergency Management", name: "Wingard, Lorraine T.", date: 2024-03-04}
classification: "SGW Internal - Controlled"
trust: verified_internal
status: in_force
decisions: [D1]
states: [SC, GA]
changes:
  - {rev: "H", date: 2024-03-11, section: "R1.4", change: "Brier Landing CT-2 Mvar capability updated after 2023 reactive test."}
  - {rev: "H", date: 2024-03-11, section: "R1.5", change: "Cranking path CP-3 rerouted through SUB-AIK-GADSBYNECK."}
  - {rev: "H", date: 2024-03-11, section: "R1.2", change: "No changes."}
---
# 1.0 PURPOSE

This document summarizes the SGW Transmission Operator (TOP) System Restoration Plan required by NERC
EOP-005-3 R1. The full plan, switching sheets and cranking path drawings are held by Transmission Operations
and provided to the Reliability Coordinator (RC). This summary is the version used in the EOC.

# 2.0 SCOPE

Restoration of the SGW Bulk Electric System after a total or partial system blackout in South Carolina and
east Georgia. Distribution restoration after the transmission system is stable follows DOM 14.215, DOM 14.130
and the hazard annexes.

# 3.0 RESPONSIBILITIES

3.1 The TOP shift supervisor directs restoration switching until the RC assigns other direction.

3.2 The Manager, Transmission Operations coordinates with the RC and the Balancing Authority (BA), and keeps
this plan current.

3.3 The Incident Commander is told of each restoration milestone through the EOC bridge.

# 4.0 PLAN ELEMENTS (EOP-005-3 R1.1 TO R1.9)

## 4.1 R1.1 Strategies

SGW restores from its own Blackstart Resources toward three islands (Aiken, Midlands and Coastal), each built
from a blackstart unit along a cranking path to a large unit. Islands are synchronized to each other and to
neighboring systems only under RC direction. The strategy follows the RC restoration plan and is reviewed
with the RC each year.

## 4.2 R1.2 Nuclear Off-Site Power

No nuclear plant draws off-site power from the SGW transmission system. Off-site power arrangements of
neighboring nuclear plants rest with their host TOPs. SGW confirms this each year in the review with the RC.

## 4.3 R1.3 Interconnections

Interconnections with neighboring TOPs are restored in the order agreed with the RC. Each tie is closed only
after the RC confirms frequency and phase angle at both ends. Synchronizing is done at breakers with
synchroscope or sync-check relays listed in the full plan.

## 4.4 R1.4 Blackstart Resources

| Blackstart Resource | Location | MW (net) | Mvar (lag / lead) | Type |
|---|---|---|---|---|
| Kinard Shoals Hydro Unit 3 | Edgefield County, SC | 42 | 18 / 12 | Hydro |
| Brier Landing CT-2 | Barnwell County, SC | 68 | 31 / 22 | Combustion turbine, diesel start |
| Tobias Ferry Diesel Block (4 units) | Columbia County, GA | 11.2 | 6 / 3 | Reciprocating diesel |

Each Blackstart Resource is tested at least every 3 years under the testing requirements in chapter 5 of the full plan; testing records are kept by
Generation Operations.

## 4.5 R1.5 Cranking Paths and Initial Switching

| Path | From | To (unit to be started) | Via | Initial switching sheet |
|---|---|---|---|---|
| CP-1 | Kinard Shoals Hydro | Cawthorne Bluff combined cycle | SUB-AIK-BRAMBLEGATE 115 kV | RS-01 |
| CP-2 | Brier Landing CT-2 | Brier Landing steam unit 1 | Plant bus, direct | RS-02 |
| CP-3 | Tobias Ferry Diesel Block | Brier Landing CT-2 (alternate start) | SUB-AIK-GADSBYNECK 115 kV | RS-03 |

Open all breakers on the path before energizing. Pick up shunt reactors before line charging where listed on
the switching sheet.

## 4.6 R1.6 Voltage and Frequency Limits

| Parameter | Limit during restoration |
|---|---|
| Transmission voltage | 0.90 to 1.08 per unit |
| Frequency, island | 59.5 to 60.5 Hz before adding load |
| Frequency, minimum after load step | 59.2 Hz |
| Load step size | not more than 5 percent of online island generation |

## 4.7 R1.7 Loads Required to Restore the System

Restore in this order: station service at blackstart and cranking path substations; station service for the
units to be started; load to stabilize generation and frequency, chosen from feeders serving critical
facilities (DOM 14.140, flag codes CF-1 and CF-2), including FDR-AIK-2207; load for voltage control.

## 4.8 R1.8 Reconnecting Restored Areas

Restored areas are reconnected to the island only when voltage and frequency are inside R1.6 limits on both
sides. Under-frequency load shedding relays are re-armed before each reconnection.

## 4.9 R1.9 Transfer of Authority to the BA

Authority for generation dispatch and frequency control returns to the BA when the RC criteria are met and
the RC directs the transfer. The TOP shift supervisor logs the time.

# 5.0 REQUIREMENT CROSS-REFERENCE

| EOP-005-3 item | Section of this summary | Full plan chapter |
|---|---|---|
| R1.1 | 4.1 | 2 |
| R1.2 | 4.2 | 3 |
| R1.3 | 4.3 | 4 |
| R1.4 | 4.4 | 5 |
| R1.5 | 4.5 | 6 and switching sheets RS-01 to RS-03 |
| R1.6 | 4.6 | 7 |
| R1.7 | 4.7 | 8 |
| R1.8 | 4.8 | 9 |
| R1.9 | 4.9 | 10 |
| R3 (annual review to RC) | 6.0 | 1 |

# 6.0 ANNUAL REVIEW

The plan is reviewed each year and submitted to the RC by 1 March. Changes to Blackstart Resources or cranking
paths are submitted within 90 days of the change.

<<PAGEBREAK>>
# ATTACHMENT 1 - Review Signature Sheet

| Review year | Reviewed by (position) | Name | Date signed | Submitted to RC |
|---|---|---|---|---|
| 2024 | Manager, Transmission Operations | Pettigrew, Anselm K. | 2024-02-26 | 2024-02-28 |
| 2023 | Manager, Transmission Operations | Pettigrew, Anselm K. | 2023-02-20 | 2023-02-24 |
| 2022 | Manager, Transmission Operations | Pettigrew, Anselm K. | 2022-02-21 | 2022-02-25 |
