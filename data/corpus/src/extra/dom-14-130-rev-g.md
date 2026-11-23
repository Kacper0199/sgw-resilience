---
doc_id: "DOM 14.130"
title: "Cold Load Pickup after Extended Outages"
family: sop
layout: controlled
owner_function: operations
sme: "Ingle, Prentice W."
revision: "G"
effective: 2022-08-08
supersedes: "DOM 14.130 Rev F (eff. 2020-07-13)"
next_review: 2024-12-31
approvals:
  - {function: operations, position: "Director, Distribution Operations", name: "Thibodeaux, Marcus R.", date: 2022-08-01}
  - {function: transmission, position: "Manager, Transmission Operations", name: "Pettigrew, Anselm K.", date: 2022-08-01}
classification: "SGW Internal - Controlled"
trust: verified_internal
status: in_force
decisions: [D4]
states: [SC, GA]
changes:
  - {rev: "G", date: 2022-08-08, section: "5.2", change: "Pickup block limit set at 3.2 MW per step on 23 kV feeders."}
  - {rev: "G", date: 2022-08-08, section: "Att. A", change: "Winter factors added for outages over 12 h below 25 F."}
---
# 1.0 PURPOSE

Limits the load picked up when a feeder is re-energized after a long outage, so that protective devices do
not trip and equipment is not overloaded.

# 2.0 SCOPE

Distribution feeders and laterals out of service for 4 h or longer. Does not apply to transmission load
restoration, which follows TSO 11.005.

# 3.0 RESPONSIBILITIES

3.1 The switching desk plans the pickup sequence and issues the switching.

3.2 The Duty Manager approves a pickup that exceeds the limits in section 5.

3.3 Field crews operate the sectionalizing devices and report loads.

3.4 Substation Operations confirms transformer loading at the source substation.

# 4.0 DEFINITIONS

Cold load pickup (CLPU): the high, slowly decaying load that follows re-energizing after an outage, caused
by loss of diversity among thermostatic loads.
CLPU factor: the ratio of pickup load to normal pre-outage load for the same hour.
Pickup step: the load closed in at one time.

# 5.0 PRECAUTIONS AND LIMITS

5.1 Expected CLPU factors are in Attachment A. Use the higher factor when the outage spans two rows.

5.2 Do not close more than 3.2 MW of estimated pickup load in one step on a 23 kV feeder, or 1.8 MW on a 12 kV
feeder.

5.3 Wait at least 5 min between steps on the same feeder, or until feeder current has fallen below the
relay pickup setting less 15 percent, whichever is longer.

5.4 Do not raise relay pickup settings or block reclosing to force a pickup without Duty Manager approval
and a switching order.

5.5 Do not exceed 120 percent of substation transformer nameplate for more than 2 h.

CAUTION: a feeder that trips on pickup shall not be re-closed until the crew has patrolled the first
section for faults.

# 6.0 PROCEDURE

## 6.1 Plan

6.1.1 Get the pre-outage load for the same hour from SCADA history.

6.1.2 Apply the CLPU factor from Attachment A.

6.1.3 Divide the feeder into pickup steps using sectionalizing switches, reclosers and fused laterals.

6.1.4 Order the steps so critical facilities flagged in the DOM 14.140 registry are in the first step where
the switching allows (priority per DOM 14.215).

6.1.5 Write the steps on the switching order.

## 6.2 Execute

6.2.1 Open all downstream sectionalizing points before closing the feeder breaker.

6.2.2 Close the breaker with the first step only.

6.2.3 Read feeder current at 1 min and 5 min.

6.2.4 Close the next step when 5.3 is met.

6.2.5 Repeat to the last step.

6.2.6 Return relay settings and reclosing to normal and record the time.

## 6.3 Trips during Pickup

6.3.1 If the breaker trips on the first step, patrol for a fault before any reclose.

6.3.2 If it trips on a later step with no fault found, split that step in two and retry.

6.3.3 After two trips on the same step with no fault found, call the Duty Manager.

# 7.0 RECORDS

Switching orders, SCADA load trend for the pickup, trip reports. Retain 3 years.

# 8.0 REFERENCES

DOM 14.140. DOM 14.215. TSO 06.110. TSO 11.005. GEP 2W.01. GEP 2X.01.

<<PAGEBREAK>>
# ATTACHMENT A - CLPU Factors

| Outage duration (h) | Summer, above 90 F | Mild, 50 to 90 F | Winter, 25 to 50 F | Winter, below 25 F |
|---|---|---|---|---|
| 4 to 8 | 1.8 | 1.4 | 2.0 | 2.4 |
| 8 to 12 | 2.1 | 1.5 | 2.3 | 2.8 |
| over 12 | 2.3 | 1.6 | 2.6 | 3.1 |

Factors apply to residential-dominated feeders. Use 1.3 for feeders with more than 60 percent commercial
load.
