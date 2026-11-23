---
doc_id: "WDS 03.350"
title: "Standby Generator Monthly Load Test"
family: sop
layout: controlled
owner_function: water_operations
sme: "Lumpkin, Harlan E."
revision: "G"
effective: 2024-01-15
supersedes: "WDS 03.350 Rev F (eff. 2022-02-21)"
next_review: 2025-01-31
approvals:
  - {function: water_operations, position: "Water Incident Lead; Manager, Water Distribution", name: "Sistrunk, Odell M.", date: 2024-01-08}
classification: "SGW Internal - Controlled"
trust: verified_internal
status: in_force
decisions: [D3]
states: [SC, GA]
changes:
  - {rev: "G", date: 2024-01-15, section: "6.3", change: "Test failure now opens a work order within 24 h and is reported to the Water Incident Lead from June 1 to November 30."}
  - {rev: "G", date: 2024-01-15, section: "Att. A", change: "GEN-BPS46-TANYARDBRANCH added."}
---
# 1.0 PURPOSE

Sets the monthly load test for onsite standby generators at SGW water facilities.

# 2.0 SCOPE

Onsite diesel standby generators at water and wastewater facilities. Portable generators such as MGEN-HALBERD-500 are tested under MAL 05.040.

# 3.0 RESPONSIBILITIES

3.1 Station Operator: runs the test and fills the test record.

3.2 Generator Maintenance Technician: corrects defects found.

3.3 Water Control Room Operator: is told before and after each test, because the test transfers station load.

# 4.0 PRECAUTIONS AND LIMITS

4.1 Test under station load through the ATS where one is fitted. A no-load run does not count.

4.2 Load shall reach at least 30 percent of nameplate kW for 30 min, or the exhaust temperature shall reach the manufacturer's minimum.

4.3 No test when a tropical storm watch or warning covers the district. Generator readiness checks then follow the GEP 2H.01 phase table.

4.4 CAUTION: Hearing protection is required inside the enclosure.

# 5.0 PROCEDURE

5.1 Call the Water Control Room. Give station, generator id and planned start time.

5.2 Walk down the unit: oil, coolant, belts, battery terminals, fuel leaks, louvers clear.

5.3 Read the fuel gauge. Record it.

5.4 Simulate utility loss at the ATS test switch.

5.5 Confirm transfer within 15 s. Record the time to transfer.

5.6 Run under load for 30 min. Record kW, volts, amps, frequency, oil pressure and coolant temperature at 0, 15 and 30 min.

5.7 End the test. Confirm retransfer and the 5 min cooldown.

5.8 Read the fuel gauge again.

5.9 From June 1 to November 30 keep the sub-base tank at or above 90 percent after the test. Request fuel on F-MAL-022 if lower.

5.10 Return the unit to AUTO. Call the Water Control Room.

# 6.0 DEFECTS

6.1 A test fails if transfer takes over 15 s, the unit shuts down, or any reading leaves the limits in Attachment A.

6.2 Tag the unit and report it to the Generator Maintenance Technician the same day.

6.3 Open a work order within 24 h. From June 1 to November 30 also report the failure to the Water Incident Lead, who decides whether to pre-stage a portable unit.

# 7.0 ANNUAL LOAD BANK TEST

7.1 Where monthly tests ran below 30 percent load for 3 or more months of the year, the Generator Maintenance Technician runs an annual load bank test.

7.2 Steps: 30 min at 50 percent of nameplate, then 60 min at 75 percent, then return to station load.

7.3 Schedule the load bank test between February 1 and April 30, so units go into hurricane season tested.

7.4 Fuel burned on the load bank is replaced the same week.

NOTE: The load bank connection box is on the generator side of the ATS. Do not connect it with the unit carrying station load.

# 8.0 TEST SCHEDULE

| Week of month | Units tested | Usual day |
|---|---|---|
| 1 | GEN-PS38-COPPERLEAF | Tuesday |
| 2 | GEN-PS52-DEERWATER | Tuesday |
| 3 | GEN-BPS46-TANYARDBRANCH | Wednesday |
| 4 | Make-up tests for any failed or skipped unit | As set by the district supervisor |

Tests should start between 0900 and 1400 so that a failed transfer can be corrected in daylight. A skipped test is recorded with the reason.

# 9.0 RECORDS

Monthly test record kept with the station file, 5 years. Readings during an actual outage go on F-WDS-207, not on the test record.

# 10.0 REFERENCES

WDS 03.322; WDS 03.330; MAL 05.040; NFPA 110 section 8.4.

# ATTACHMENT A UNITS AND LIMITS

| Unit | Nameplate (kW) | Minimum test load (kW) | Oil pressure (psi) | Coolant max (deg F) |
|---|---|---|---|---|
| GEN-PS38-COPPERLEAF | 400 | 120 | 40-65 | 215 |
| GEN-PS52-DEERWATER | 300 | 90 | 40-65 | 215 |
| GEN-BPS46-TANYARDBRANCH | 350 | 105 | 38-62 | 210 |
