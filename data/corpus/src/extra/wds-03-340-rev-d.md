---
doc_id: "WDS 03.340"
title: "Lift Station Bypass Pumping"
family: sop
layout: controlled
owner_function: water_operations
sme: "Ingle, Prentice W."
revision: "D"
effective: 2022-10-03
supersedes: "WDS 03.340 Rev C (eff. 2020-05-18)"
next_review: 2023-09-30
approvals:
  - {function: water_operations, position: "Water Incident Lead; Manager, Water Distribution", name: "Sistrunk, Odell M.", date: 2022-09-26}
  - {function: compliance, position: "Water Compliance Officer", name: "Quattlebaum, Rhea D.", date: 2022-09-27}
classification: "SGW Internal - Controlled"
trust: verified_internal
status: in_force
decisions: [D3]
states: [SC, GA]
changes:
  - {rev: "D", date: 2022-10-03, section: "5.4, 6.2", change: "Wet well level at which bypass starts lowered from 70 to 65 percent; dry-run check added."}
  - {rev: "D", date: 2022-10-03, section: "Att. A", change: "LS-212 Cawthorne Bluff added to the priority list."}
  - {rev: "D", date: 2022-10-03, section: "7.0", change: "No Changes."}
---
# 1.0 PURPOSE

This procedure sets how a portable bypass pump is placed and run when a sanitary lift station cannot pump, so that the wet well does not overflow.

# 2.0 SCOPE

Applies to SGW wastewater lift stations in all SC and GA districts. Does not apply to treatment plant influent pumping.

# 3.0 RESPONSIBILITIES

3.1 Water Incident Lead: orders bypass at any station during a declared event; sets the priority among stations when bypass pumps are short.

3.2 Collections Supervisor: places and runs the bypass; posts a watch.

3.3 Water Compliance Officer: decides whether an overflow is reportable and reports it per WQC 07.150.

# 4.0 DEFINITIONS

Bypass: pumping from the wet well or upstream manhole directly to the force main or a downstream manhole, around the station's own pumps. Wet well level is percent of the distance from the invert to the overflow elevation.

# 5.0 PRECAUTIONS AND LIMITS

5.1 Entry into a wet well is a permit-required confined space entry. Bypass setup shall be done from grade.

5.2 Suction hose shall be hard-wall, rated for full vacuum.

5.3 Discharge into the force main shall not exceed the station's rated discharge pressure.

5.4 Start bypass when wet well level reaches 65 percent and the station is not expected to resume within the time to overflow in Attachment A.

5.5 CAUTION: Hydrogen sulfide may exceed 10 ppm at the hatch. Use a 4-gas meter before opening.

# 6.0 PROCEDURE

## 6.1 Assessment

6.1.1 Confirm the station alarm on SCADA. If SCADA is lost, follow WDS 03.115.

6.1.2 Determine the cause: grid outage, pump failure, control failure or flooding.

6.1.3 Read the time to overflow from Attachment A. Report it to the Water Incident Lead.

## 6.2 Bypass setup

6.2.1 Select a pump from Attachment B sized for the station's peak wet-weather flow.

6.2.2 Place the pump on level ground clear of traffic. Set cones and signs.

6.2.3 Run suction hose through the wet well hatch. Keep the foot valve at least 18 in. above the invert.

6.2.4 Connect discharge to the bypass connection on the force main. If none exists, discharge to the next downstream manhole.

6.2.5 Pressure test the discharge hose at operating pressure for 5 min. Inspect every joint.

6.2.6 Set the float controls: pump on at 60 percent, off at 25 percent.

6.2.7 Do a dry-run check: confirm the low-level float stops the pump before air enters the suction.

6.2.8 Start the pump. Confirm level falls.

## 6.3 Operation

6.3.1 Keep a person on watch at any bypass running without a level float.

6.3.2 Check fuel, hose joints and wet well level every 2 h. Log each check in the station log book.

6.3.3 Report any spill, however small, to the Water Compliance Officer at once.

## 6.4 Removal

6.4.1 Restore the station pumps and run two full cycles.

6.4.2 Stop the bypass. Drain hoses to the wet well.

6.4.3 Remove equipment and clean the site.

# 7.0 RECORDS

Station log book entries, retained 5 years. Overflow reports per WQC 07.150.

# 8.0 REFERENCES

WDS 03.115; WQC 07.150; MAL 05.040 (fuel for portable pumps).

# ATTACHMENT A PRIORITY STATIONS AND TIME TO OVERFLOW

| Station | District | Dry-weather time to overflow from 65 percent (h) | Wet-weather (h) |
|---|---|---|---|
| LS-212 Cawthorne Bluff | Aiken | 3.5 | 1.2 |
| LS-74 Ruddell Landing | Aiken | 6.0 | 2.1 |
| LS-158 Gadsby Neck | Richmond | 4.25 | 1.6 |
| LS-93 Pelham Crossroads | Richmond | 9.0 | 3.4 |

# ATTACHMENT B PORTABLE BYPASS PUMPS

| Unit | Size | Rated flow (gpm) | Kept at |
|---|---|---|---|
| BYP-6-TALLEY | 6 in. diesel trash pump | 1,400 | DEP-AIK-GRANITEVILLE |
| BYP-4-MERRICK | 4 in. diesel trash pump | 650 | DEP-AIK-GRANITEVILLE |
| BYP-6-HOLLIS | 6 in. diesel trash pump | 1,400 | Richmond Millpond depot |
