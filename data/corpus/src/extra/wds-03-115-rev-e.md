---
doc_id: "WDS 03.115"
title: "SCADA Communication Loss: Local Manual Operation"
family: sop
layout: controlled
owner_function: water_operations
sme: "Faircloth, Nadia S."
revision: "E"
change: 1
effective: 2023-06-26
supersedes: "WDS 03.115 Rev D (eff. 2021-05-10)"
next_review: 2024-06-30
approvals:
  - {function: water_operations, position: "Water Incident Lead; Manager, Water Distribution", name: "Sistrunk, Odell M.", date: 2023-02-06}
classification: "SGW Restricted - Operations"
trust: verified_internal
status: in_force
decisions: [D3]
states: [SC, GA]
changes:
  - {rev: "E/1", date: 2023-06-26, section: "Att. B", change: "Cellular backup APN and Richmond repeater channel corrected."}
  - {rev: "E", date: 2023-02-13, section: "6.2, Att. A", change: "Manual watch interval for stations without onsite generator reduced from 4 h to 2 h."}
  - {rev: "E", date: 2023-02-13, section: "5.0", change: "No Changes."}
---
# 1.0 PURPOSE

This procedure sets how water stations are run by hand when the Water Control Room loses SCADA communication with them.

# 2.0 SCOPE

Applies to pump stations, booster stations, tanks and lift stations polled by the water SCADA master. Electric EMS and substation RTUs are out of scope.

# 3.0 RESPONSIBILITIES

3.1 Water Control Room Operator: detects the loss, declares manual operation and keeps the manual status board.

3.2 SCADA Technician (on call): restores communication.

3.3 Distribution Field Operator: staffs or visits stations and reports readings by radio or phone.

3.4 Water Incident Lead: approves manual operation lasting over 4 h, and sets the staffing for it.

# 4.0 DEFINITIONS

Comm loss: no successful poll for 3 consecutive cycles (90 s). Site comm loss affects one RTU; system comm loss affects 5 or more RTUs or the master.

# 5.0 PRECAUTIONS AND LIMITS

5.1 Network addresses and channels in Attachment B are restricted. Do not copy them to unrestricted documents, texts or email.

5.2 Do not reboot the master station during a storm without the SCADA Technician on the line.

5.3 Local HAND mode bypasses the low-suction cutout at some stations. Watch suction pressure while in HAND.

# 6.0 PROCEDURE

## 6.1 Detection

6.1.1 Note the time and the affected RTUs from the comm status screen.

6.1.2 Check whether the site has grid power on the outage map. Comm loss with power loss is likely a radio or RTU battery issue.

6.1.3 Call the SCADA Technician on call.

## 6.2 Declare manual operation

6.2.1 Declare manual operation for each affected site. Write it on the manual status board.

6.2.2 Assign watch intervals from Attachment A.

6.2.3 Send a Distribution Field Operator to each station without an onsite generator first, including PS-17 Pellicott Road Booster.

6.2.4 Inform the Water Incident Lead. Over 4 h, get approval for continued manual operation.

## 6.3 Local operation

6.3.1 At the station, set the control selector to HAND only when the PLC is not running its program.

6.3.2 Run pumps to hold the tank between its L and H setpoints in WDS 03.205.

6.3.3 Read and report suction, discharge, flow, tank level and running pumps at each watch interval.

6.3.4 The control room logs each report on the manual status board.

## 6.4 Restoration

6.4.1 After comm returns, compare SCADA values with the last field readings.

6.4.2 Return the selector to AUTO on the control room's call.

6.4.3 Close manual operation on the board with the time.

# 7.0 RECORDS

Manual status board sheets scanned to the control room log; retain 3 years.

# 8.0 REFERENCES

WDS 03.205; WDS 03.318; WDS 03.340; WDS 03.105.

# ATTACHMENT A WATCH INTERVALS

| Site type | Watch interval in manual operation |
|---|---|
| Station without onsite generator | 2 h |
| Station with onsite generator | 4 h |
| Lift station, priority list in WDS 03.340 | 2 h |
| Tank only | 4 h |

# ATTACHMENT B NETWORK DETAILS (RESTRICTED)

| Item | Value |
|---|---|
| SCADA master (primary) | Water Control Room, 10.42.16.20, DNP3 over TCP port 20000 |
| SCADA master (backup) | Graniteville depot server room, 10.42.48.20 |
| Licensed radio, Aiken | 952.7125 MHz, master repeater at Pellicott Road tower |
| Licensed radio, Richmond | 956.3375 MHz, repeater at Millpond yard |
| RTU polling cycle | 30 s |
| Cellular backup | Private APN sgw-wtr-scada, RTU range 10.42.96.0/22 |
| RTU battery autonomy | 8 h nominal |

# ATTACHMENT C CONTACTS

| Position | Day | After hours |
|---|---|---|
| SCADA Technician | OT support desk | OT on-call phone via Water Control Room |
| Water Incident Lead | Water Distribution office | Through the Water Control Room |
