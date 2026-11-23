---
doc_id: "WDS 03.205"
legacy_id: "WOP-105"
title: "Elevated Tank Level Monitoring and Overflow"
family: sop
layout: controlled
owner_function: water_operations
sme: "Varnadoe, Celeste M."
revision: "F"
effective: 2023-09-11
supersedes: "WDS 03.205 Rev E (eff. 2021-08-02)"
next_review: 2024-08-31
approvals:
  - {function: water_operations, position: "Water Incident Lead; Manager, Water Distribution", name: "Sistrunk, Odell M.", date: 2023-09-01}
classification: "SGW Internal - Controlled"
trust: verified_internal
status: in_force
decisions: [D3]
states: [SC, GA]
changes:
  - {rev: "F", date: 2023-09-11, section: "Att. A", change: "Alarm setpoints for TNK-PS38-COPPERLEAF and TNK-PS52-DEERWATER revised after altitude valve replacement."}
  - {rev: "F", date: 2023-09-11, section: "6.3", change: "Overflow notification to the Water Compliance Officer added."}
---
# 1.0 PURPOSE

Sets the level alarms for SGW elevated storage tanks and the response to high level, overflow and low level.

# 2.0 SCOPE

All elevated tanks and standpipes in SGW water systems. Ground storage at treatment plants is covered by plant procedures.

# 3.0 RESPONSIBILITIES

3.1 Water Control Room Operator: watches tank levels on SCADA, acknowledges alarms and takes the first actions in section 6.

3.2 Distribution Field Operator: verifies level locally and operates altitude and isolation valves when directed.

3.3 Water Incident Lead: directs response during declared events and orders any valve isolation.

# 4.0 DEFINITIONS

Level is feet of water above the tank floor. HH: high-high alarm. LL: low-low alarm. Residual-pressure limit: the lowest tank level that still holds the zone above the state pressure floor at the highest service connection.

# 5.0 PRECAUTIONS AND LIMITS

5.1 Tanks shall not be drawn below the LL setpoint in normal operation.

5.2 A tank overflow that leaves SGW property shall be reported to the Water Compliance Officer within 1 h.

5.3 NOTE: Level transmitters drift after lightning. Verify a sudden step change of more than 3 ft locally before acting on it.

# 6.0 PROCEDURE

## 6.1 High level (H)

6.1.1 Confirm the filling pump station has stopped on its level control.

6.1.2 If pumps are still running, stop the lead pump from SCADA.

6.1.3 Log the event in the control room log.

## 6.2 High-high level (HH)

6.2.1 Stop all pumps filling the tank.

6.2.2 Dispatch a Distribution Field Operator to check the altitude valve.

6.2.3 If the altitude valve is stuck open, close the tank inlet valve by hand.

## 6.3 Overflow

6.3.1 Confirm overflow by camera or field report.

6.3.2 Stop filling. Close the inlet valve.

6.3.3 Estimate the volume lost from the level trend and the overflow pipe size.

6.3.4 Notify the Water Compliance Officer. Report any erosion or off-site flow.

6.3.5 Inspect the overflow screen and flap gate before the tank returns to service.

## 6.4 Low level (L) and low-low level (LL)

6.4.1 Check whether the filling station is in alarm or without power.

6.4.2 If the filling station has lost power, start tank drawdown tracking per WDS 03.240. Drawdown is tracked every 15 min.

6.4.3 At LL, inform the Water Incident Lead. Pressure response follows WDS 03.105.

6.4.4 Do not isolate the tank without the Water Incident Lead's order.

## 6.5 Before a forecast storm

6.5.1 From 48 h before forecast tropical-storm-force winds, raise each tank to between H and HH less 0.5 ft.

6.5.2 Check that the overflow screen is in place and the flap gate closes.

6.5.3 Confirm the level transmitter reads within 1 ft of the sight gauge or a field tape reading.

6.5.4 Report tanks that cannot be filled to the Water Incident Lead, with the reason.

# 7.0 RECORDS

Control room log; SCADA trend exports kept 3 years. Valve isolations are recorded on F-WDS-212.

# 8.0 REFERENCES

WDS 03.105; WDS 03.240; WDS 03.115; WQC 07.150 (for tank drains reaching a sewer).

# ATTACHMENT A TANK ALARM SETPOINTS

| Tank | Overflow (ft) | HH (ft) | H (ft) | L (ft) | LL (ft) |
|---|---|---|---|---|---|
| TNK-PS17-CEDARFALL | 38.0 | 37.2 | 36.0 | 22.5 | 17.0 |
| TNK-PS23-LAURELSPUR | 32.5 | 31.8 | 30.5 | 19.0 | 14.5 |
| TNK-PS38-COPPERLEAF | 40.0 | 39.1 | 38.0 | 24.0 | 18.5 |
| TNK-PS52-DEERWATER | 35.0 | 34.3 | 33.0 | 21.0 | 16.0 |
| TNK-BPS46-TANYARDBRANCH | 30.0 | 29.4 | 28.0 | 17.5 | 13.0 |

# ATTACHMENT B CONTACTS

| Position | Day | After hours |
|---|---|---|
| Water Control Room Operator | Control room console | Same, staffed 24 h |
| Water Incident Lead | Water Distribution office | Through the Water Control Room |
| Water Compliance Officer | Compliance office | Compliance on-call phone |
