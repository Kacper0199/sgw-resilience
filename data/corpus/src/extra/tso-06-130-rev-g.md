---
doc_id: "TSO 06.130"
legacy_id: "SCP-27"
title: "Temporary Protective Grounding for Storm Work"
family: sop
layout: controlled
owner_function: operations
sme: "Ravenel, Cyrus B."
revision: "G"
effective: 2022-02-07
supersedes: "TSO 06.130 Rev F (eff. 2020-03-02)"
next_review: 2024-12-31
approvals:
  - {function: transmission, position: "Manager, Transmission Operations", name: "Pettigrew, Anselm K.", date: 2022-01-31}
  - {function: operations, position: "Director, Distribution Operations", name: "Thibodeaux, Marcus R.", date: 2022-01-31}
classification: "SGW Internal - Controlled"
trust: verified_internal
status: in_force
decisions: [D2]
states: [SC, GA]
changes:
  - {rev: "G", date: 2022-02-07, section: "6.2", change: "Generator backfeed added as a reason to ground both sides of the work."}
  - {rev: "G", date: 2022-02-07, section: "Att. A", change: "Minimum ground set rating for 115 kV stations raised to 40 kA."}
---
# 1.0 PURPOSE

Sets how temporary protective grounds are applied during storm restoration so that workers are protected
from accidental energizing, induced voltage and backfeed.

# 2.0 SCOPE

All de-energized overhead and substation work on SGW lines and equipment during storm restoration, by
SGW, mutual-aid and contract crews. Mutual-aid crews follow this procedure, not their home rules, while
working on the SGW system (briefed under DOM 12.040).

# 3.0 RESPONSIBILITIES

3.1 The clearance holder (TSO 06.110) decides grounding locations and keeps the ground log.

3.2 Crew members apply and remove grounds as directed by the clearance holder.

3.3 The Staging Area Manager issues inspected ground sets from the yard.

# 4.0 DEFINITIONS

Equipotential zone (EPZ): grounding arranged so that a worker is never in series with a path for fault
current.
Ground set: clamps, ferrules and cable rated for the available fault current.
Backfeed: voltage returning from the secondary side, often from customer-owned portable generators.

# 5.0 PRECAUTIONS AND LIMITS

5.1 Ground only after a clearance has been issued and a Hot Line Hold or open point is in place.

5.2 Test for absence of voltage with a tested detector immediately before applying grounds.

5.3 Use ground sets rated for the location per Attachment A.

5.4 Do not use a ground set that has a broken strand at the ferrule, a cracked clamp or missing inspection
tag.

5.5 Attach the ground end first; remove it last. Use a hot stick for all phase connections.

CAUTION: storm damage creates crossed circuits and customer generator backfeed. Treat every conductor as
energized until grounded.

# 6.0 PROCEDURE

## 6.1 Before Grounding

6.1.1 Confirm the clearance and every open point by three-part communication with the switching desk.

6.1.2 Hold a tailboard. Name the grounding locations and the worker who applies each set.

## 6.2 Apply

6.2.1 Ground at the work location to build an EPZ: bracket the work, or ground at the pole being worked with
a cluster bar.

6.2.2 Ground both sides of the work when backfeed is possible, including any section with services that
could carry customer generator power.

6.2.3 Connect the ground end to the system neutral, cluster bar or station ground grid.

6.2.4 Connect phases nearest to farthest.

6.2.5 Record each ground on the ground log: location, set number, time applied.

## 6.3 Remove

6.3.1 Confirm all workers are clear.

6.3.2 Remove phase ends farthest to nearest, then the ground end.

6.3.3 Record the removal time. The clearance holder counts sets back before releasing the clearance.

6.3.4 Return sets to the yard. Damaged sets are tagged out of service.

## 6.4 Special Cases

6.4.1 Pad-mounted transformers and underground cable: ground at the elbow with a feed-through bushing and a
grounding elbow rated per Attachment A.

6.4.2 Substations: connect to the station ground grid at the tagged grounding points only.

6.4.3 Long spans in parallel with an energized line: expect induced voltage. Ground at each end of the
section and at the work location.

6.4.4 Wire on the ground: ground the conductor on both sides of the break before cutting (DOM 14.120).

# 7.0 RECORDS

Ground logs are kept with the clearance record for 3 years.

# 8.0 REFERENCES

TSO 06.110. DOM 12.040. DOM 14.120. DOM 14.160. DOM 14.170. 29 CFR 1910.269(n). ASTM F855 (temporary
protective grounds).

<<PAGEBREAK>>
# ATTACHMENT A - Ground Set Ratings

| Location | Minimum ground set rating (kA, 15 cycles) | Cable size |
|---|---|---|
| 12 kV and 23 kV distribution lines | 21 | 2/0 copper |
| Distribution substation low side | 27 | 4/0 copper |
| 115 kV station and line | 40 | 4/0 copper, paralleled where noted on the station drawing |
