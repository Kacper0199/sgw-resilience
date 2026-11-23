---
doc_id: "WDS 03.360"
title: "Chemical Feed Systems on Generator Power"
family: sop
layout: controlled
owner_function: water_operations
sme: "Bazemore, Tamsin L."
revision: "C"
change: 2
effective: 2022-05-09
supersedes: "WDS 03.360 Rev B (eff. 2019-10-21)"
next_review: 2023-04-30
approvals:
  - {function: water_operations, position: "Water Incident Lead; Manager, Water Distribution", name: "Sistrunk, Odell M.", date: 2021-07-12}
  - {function: compliance, position: "Water Compliance Officer", name: "Quattlebaum, Rhea D.", date: 2021-07-13}
classification: "SGW Internal - Controlled"
trust: verified_internal
status: in_force
decisions: [D3]
states: [SC, GA]
changes:
  - {rev: "C/2", date: 2022-05-09, section: "Att. A", change: "Day tank volume at PS-52 corrected to 55 gal."}
  - {rev: "C/1", date: 2021-11-15, section: "8.0", change: "Reference to WQC 07.140 added."}
  - {rev: "C", date: 2021-07-19, section: "6.2, 6.3", change: "Flow-paced restart sequence added; hypochlorite feed now restarts before the pumps reach full speed."}
---
# 1.0 PURPOSE

This procedure keeps disinfectant feed at booster stations correct while the station runs on an onsite or portable generator, and after it returns to grid supply.

# 2.0 SCOPE

Applies to booster stations with sodium hypochlorite feed listed in Attachment A. Treatment plant chemical systems are out of scope. Fluoride and orthophosphate are fed only at plants and are not covered.

# 3.0 RESPONSIBILITIES

3.1 Station Operator: verifies feed after every transfer and keeps the feed log.

3.2 Water Quality Technician: measures free chlorine residual downstream and reports low results.

3.3 Water Compliance Officer: decides on actions when residual falls below the state minimum.

# 4.0 DEFINITIONS

Flow-paced feed: metering pump speed set by a 4-20 mA signal from the station flow meter. Day tank: the small tank feeding the metering pump directly.

# 5.0 PRECAUTIONS AND LIMITS

5.1 Hypochlorite metering pumps shall be on the generator-backed panel. Confirm this at each monthly test under WDS 03.350.

5.2 A metering pump that restarts before flow is established can overfeed. Never start feed with zero station flow.

5.3 Target free chlorine residual leaving the station is 1.2 to 2.0 mg/L. The distribution minimum is 0.2 mg/L in Georgia (Ga. Comp. R. & Regs. 391-3-5-.14); see WQC 07.140 for both states.

5.4 CAUTION: Hypochlorite off-gasses when heated. Keep the chemical room vent fan on the generator panel running.

5.5 Store no more than 30 days of hypochlorite at a station. It loses strength in summer heat.

# 6.0 PROCEDURE

## 6.1 On transfer to generator

6.1.1 Confirm pumps restarted and flow is above 150 gpm.

6.1.2 Confirm the metering pump is running and its stroke counter is moving.

6.1.3 Check the calibration column. Record the draw-down rate in gal/h.

6.1.4 Take a free chlorine reading at the station discharge tap within 30 min.

## 6.2 Flow-paced restart sequence

6.2.1 If feed did not restart, wait until station flow is stable for 2 min.

6.2.2 Start the metering pump in HAND at 25 percent speed.

6.2.3 After 5 min, switch to AUTO (flow-paced).

6.2.4 Recheck residual after 30 min.

## 6.3 While on generator power

6.3.1 Read the day tank level every 4 h with the generator readings.

6.3.2 Refill the day tank at 25 percent. Do not let it run dry; air in the suction line stops feed.

6.3.3 Take a residual at the discharge every 8 h and at the far zone point once per day.

6.3.4 If the discharge residual is below 1.0 mg/L, raise the feed rate by 10 percent and recheck in 30 min.

6.3.5 If any distribution reading is below the state minimum, notify the Water Compliance Officer.

## 6.4 On return to grid supply

6.4.1 Confirm feed restarted after retransfer.

6.4.2 Take a discharge residual within 30 min.

6.4.3 Log the end of generator operation in the feed log.

# 7.0 RECORDS

Station feed log, kept 5 years. Residual results go to the Water Quality data system.

# 8.0 REFERENCES

WDS 03.322; WDS 03.330; WDS 03.350; WQC 07.140; Ga. Comp. R. & Regs. 391-3-5-.14.

# ATTACHMENT A STATIONS WITH HYPOCHLORITE FEED

| Station | Chemical | Bulk tank (gal) | Day tank (gal) | Power source in outage |
|---|---|---|---|---|
| PS-38 Copperleaf | 12.5 percent NaOCl | 400 | 60 | GEN-PS38-COPPERLEAF |
| PS-52 Deerwater | 12.5 percent NaOCl | 300 | 55 | GEN-PS52-DEERWATER |
| BPS-46 Tanyard Branch Booster | 12.5 percent NaOCl | 250 | 45 | GEN-BPS46-TANYARDBRANCH |
| PS-17 Pellicott Road Booster | 12.5 percent NaOCl | 250 | 45 | Portable generator (WDS 03.318) |
