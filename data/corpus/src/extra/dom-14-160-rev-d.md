---
doc_id: "DOM 14.160"
title: "Distribution Transformer Replacement under Storm Conditions"
family: sop
layout: controlled
owner_function: operations
sme: "Strom, Booker J."
revision: "D"
effective: 2021-09-20
supersedes: "DOM 14.160 Rev C (eff. 2019-06-03)"
next_review: 2024-09-30
approvals:
  - {function: operations, position: "Director, Distribution Operations", name: "Thibodeaux, Marcus R.", date: 2021-09-13}
  - {function: logistics, position: "Manager, Supply Chain", name: "Huggins, Delmar J.", date: 2021-09-14}
classification: "SGW Internal - Controlled"
trust: verified_internal
status: in_force
decisions: [D2, D4]
states: [SC, GA]
changes:
  - {rev: "D", date: 2021-09-20, section: "6.3", change: "Like-for-like substitution table added for 25, 50 and 75 kVA pole-mounted units."}
  - {rev: "D", date: 2021-09-20, section: "5.0", change: "Yard minimum stock levels revised."}
  - {rev: "D", date: 2021-09-20, section: "7.0", change: "No changes."}
---
# 1.0 PURPOSE

Sets how failed or damaged distribution transformers are replaced during storm restoration, including
substitution, oil spill handling and records.

# 2.0 SCOPE

Pole-mounted and pad-mounted distribution transformers up to 500 kVA. Substation power transformers follow
DOM 14.170 and TSO procedures.

# 3.0 RESPONSIBILITIES

3.1 Line crews replace transformers and report the change.

3.2 The Staging Area Manager issues transformers from yard stock.

3.3 Stores replenishes yards per section 5 and MAL 05.050.

3.4 Environmental Services handles reportable oil spills.

# 4.0 DEFINITIONS

Like-for-like: same kVA, voltage, phase and mounting.
Storm substitution: a unit of the next larger kVA, or a different but compatible style, used when the
like-for-like unit is not in stock.

# 5.0 PRECAUTIONS, LIMITS AND STOCK

5.1 Do not install a unit smaller than the failed one.

5.2 Check the primary voltage and the secondary configuration on the nameplate before hanging.

5.3 Treat oil from a failed unit as containing PCBs until the nameplate or test shows "non-PCB".

5.4 Yard minimum stock at Activation Level 2 or higher:

| Unit | STG-AIK-SANDHILL-YARD (each) | STG-RCH-MILLPOND-YARD (each) | Reorder point (each) |
|---|---|---|---|
| 25 kVA 1-phase pole | 64 | 48 | 30 |
| 50 kVA 1-phase pole | 52 | 38 | 24 |
| 75 kVA 1-phase pole | 18 | 14 | 8 |
| 167 kVA 1-phase pad | 6 | 4 | 3 |
| 300 kVA 3-phase pad | 3 | 2 | 1 |

5.5 Stores restocks a yard within 24 h of hitting the reorder point. Emergency issue follows MAL 05.050.

CAUTION: a transformer that has been under floodwater shall not be re-energized. Replace it.

# 6.0 PROCEDURE

## 6.1 Assess

6.1.1 Confirm the transformer has failed. Check the primary fuse and secondary first; a blown fuse alone is
re-fused, not replaced.

6.1.2 Record damage type: tank rupture, bushing, internal fault, flooded, or missing.

6.1.3 Check for oil on the ground or in water. Report spills over 25 gallons, or any spill reaching water, to
the Duty Manager.

## 6.2 Draw Stock

6.2.1 Request the unit at the yard on the material ticket with the work order number.

6.2.2 If the like-for-like unit is out, take a substitute per 6.3.

## 6.3 Substitution

| Failed unit | First substitute | Second substitute |
|---|---|---|
| 25 kVA pole | 50 kVA pole | 75 kVA pole |
| 50 kVA pole | 75 kVA pole | Two 25 kVA banked only with Duty Manager approval |
| 75 kVA pole | 100 kVA pole | 167 kVA pad on temporary pad |
| 167 kVA pad | 250 kVA pad | None; request from Stores |

6.3.1 Record the substitution on the work order so the planner can right-size later.

## 6.4 Replace

6.4.1 Isolate the transformer at the primary cutout and test for absence of voltage.

6.4.2 Ground per TSO 06.130.

6.4.3 Remove the failed unit. Cap bushings and set it upright on the truck.

6.4.4 Hang the replacement, connect the secondary, then the primary.

6.4.5 Remove grounds, close the cutout and check secondary voltage at the meter base or service.

6.4.6 Where the outage was 4 h or longer, follow DOM 14.130 for pickup on the affected section.

## 6.5 Failed Units

Return failed units to the yard spill pad. Tag them with the work order and the PCB status.

# 7.0 RECORDS

Work orders, material tickets, spill reports. Retain 5 years. Spill reports retained 10 years.

# 8.0 REFERENCES

DOM 14.130. DOM 14.170. TSO 06.130. MAL 05.050. GEP 2X.01. 40 CFR 761 (PCB handling).
