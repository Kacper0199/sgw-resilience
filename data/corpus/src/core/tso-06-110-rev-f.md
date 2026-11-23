---
doc_id: "TSO 06.110"
legacy_id: "TSP-14"
title: "Switching and Clearance"
family: sop
layout: controlled
owner_function: operations
sme: "Varnadoe, Celeste M."
revision: "F"
effective: 2024-02-26
supersedes: "TSO 06.110 Rev E (eff. 2022-02-28)"
next_review: 2025-02-28
approvals:
  - {function: transmission, position: "Manager, Transmission Operations", name: "Pettigrew, Anselm K.", date: 2024-02-19}
  - {function: operations, position: "Director, Distribution Operations", name: "Thibodeaux, Marcus R.", date: 2024-02-19}
classification: "SGW Internal - Controlled"
trust: verified_internal
status: in_force
decisions: [D4]
states: [SC, GA]
changes:
  - {rev: "F", date: 2024-02-26, section: "6.2", change: "Three-part communication made mandatory for all switching instructions, including radio."}
  - {rev: "F", date: 2024-02-26, section: "6.5", change: "Mutual-aid crew clearance rules added."}
  - {rev: "F", date: 2024-02-26, section: "Att. B", change: "No Changes."}
---
# 1.0 PURPOSE

This procedure sets the rules for switching orders, clearances and Hot Line Holds on the SGW transmission and
distribution system.

# 2.0 SCOPE

Applies to every person who orders, performs or works under a switching order or clearance on SGW facilities,
including contractors and mutual-aid crews. Does not apply to customer-owned equipment beyond the meter.

# 3.0 RESPONSIBILITIES

| Position | Responsibility |
|---|---|
| Transmission System Operator | Issues switching orders on transmission and substations |
| Distribution System Operator | Issues switching orders on distribution feeders |
| Clearance holder | Holds the clearance or Hot Line Hold; the only person who may release it |
| Switchman | Performs each step as ordered and reports completion |
| Crew leader (mutual aid) | Requests clearances through the SGW crew guide assigned to the crew |

# 4.0 DEFINITIONS

Clearance: a written assurance from the operator that equipment is isolated, tagged and safe to work on.

Hot Line Hold: a hold placed on an energized line for live-line work. The device is set to non-reclose and
tagged at the control point.

Three-part communication: the sender gives the instruction, the receiver restates it, the sender confirms.

Switching order (SWO): the written sequence of steps, numbered SWO-yymm-nnnn.

# 5.0 PRECAUTIONS AND LIMITS

5.1 Never operate a device without a switching order, except to protect life in an emergency. Report such an
operation to the operator at once.

5.2 Test for voltage before grounding. Apply grounds per TSO 06.130.

5.3 One clearance holder per clearance. A clearance cannot be transferred by radio.

CAUTION: An open switch is not a clearance. Work starts only after the operator grants the clearance.

# 6.0 PROCEDURE

## 6.1 Preparing the Switching Order

6.1.1 The operator writes the switching order on the SWO form with station or feeder, purpose and clearance
holder.

6.1.2 A second qualified operator checks the order against the system map.

6.1.3 The operator approves the order and assigns the SWO number.

## 6.2 Giving Instructions

6.2.1 Switching instructions use three-part communication: the receiver restates location, equipment and
action exactly as spoken.

6.2.2 The operator confirms "That is correct" before the step is performed.

6.2.3 If the restatement differs in any word, repeat the full instruction.

6.2.4 Give one step at a time unless the order groups steps.

6.2.5 Record each step time (24 h, EDT) and the repeat-back check on the SWO.

## 6.3 Hot Line Hold

6.3.1 A Hot Line Hold sets the device to non-reclose.

6.3.2 Tag the device at the control point and in the SCADA display.

6.3.3 Only the clearance holder releases the Hot Line Hold.

6.3.4 If the clearance holder leaves the site, the hold stays in place until that person releases it or the
operator follows the abandoned-hold process in 6.6.

## 6.4 Releasing a Clearance

6.4.1 The clearance holder confirms all persons are clear and all grounds removed.

6.4.2 The clearance holder releases the clearance to the operator using three-part communication.

## 6.5 Mutual-Aid Crews

6.5.1 Mutual-aid crews work under SGW clearances only.

6.5.2 Each mutual-aid crew is briefed on this procedure before first work (DOM 12.040 section 6.3).

6.5.3 A mutual-aid crew leader may hold a clearance after the briefing.

## 6.6 Abandoned Hold or Clearance

6.6.1 The operator calls the clearance holder by radio and phone at least 3 times over 30 minutes.

6.6.2 The Duty Manager or Transmission Branch Director sends a supervisor to the site.

6.6.3 The supervisor confirms all persons clear and signs the release on the SWO.

# 7.0 RECORDS

Switching orders and clearance logs are kept for 7 years.

# 8.0 REFERENCES

TSO 06.130, TSO 11.002, DOM 12.040, DOM 14.120, OSHA 29 CFR 1910.269.

<<PAGEBREAK>>
# ATTACHMENT A - Repeat-Back Check

| Sender says | Receiver restates | Sender confirms |
|---|---|---|
| Bramblegate, breaker 2207, open | Bramblegate, breaker 2207, open | That is correct |
| FDR-AIK-2219, recloser R-14, place Hot Line Hold | FDR-AIK-2219, recloser R-14, place Hot Line Hold | That is correct |

# ATTACHMENT B - Contacts

| Position | Day | After hours |
|---|---|---|
| Transmission System Operator | Transmission Control Center | Staffed 24 h, ext. 2100 |
| Distribution System Operator | Distribution Control Center | Staffed 24 h, ext. 2262 |
