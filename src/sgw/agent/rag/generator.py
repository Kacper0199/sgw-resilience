# ruff: noqa: E501 - record templates hold long literal lines of form text
"""Template generator for SGW issued records: ICS forms, switching orders, situation reports, equipment
runbooks, inspection reports, issued boil-water notices and H-hour checklists.

Deterministic (fixed seed, fixed tables). Times follow the Helene story of record
(`data/fixtures/helene/truth_table.json`): FDR-AIK-2207 trips 05:30Z on 2024-09-27, PS-17 falls below the
floor at 10:05Z, MGEN-HALBERD-500 is dispatched 15:45Z and running 18:15Z, the zone is back above the floor at
21:21Z, grid supply returns 02:29Z on 2024-09-28. Each record carries one form-family variance setting
(entry count, crossed-out entries, abbreviation style) so no two look machine-made alike.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from sgw.agent.rag.corpus import CORPUS_DIR

SEED = 20240927
INCIDENT = 'SGW-INC-24-0031 "HELENE"'


@dataclass(frozen=True)
class GenDoc:
    meta: dict[str, Any]
    body: str

    @property
    def file_name(self) -> str:
        base = "".join(c if c.isalnum() else "-" for c in str(self.meta["doc_id"]).lower())
        while "--" in base:
            base = base.replace("--", "-")
        rev = self.meta.get("revision")
        return f"{base.strip('-')}{'-rev-' + str(rev).lower() if rev else ''}.md"

    def source(self) -> str:
        head = yaml.safe_dump(self.meta, sort_keys=False, allow_unicode=False, width=200).strip()
        return f"---\n{head}\n---\n{self.body.strip()}\n"


def _record(doc_id: str, title: str, family: str, effective: str, owner: str, decisions: list[str],
            trust: str = "internal_free_text", classification: str = "SGW Internal - Controlled",
            **extra: Any) -> dict[str, Any]:  # fmt: skip
    meta: dict[str, Any] = {
        "doc_id": doc_id,
        "title": title,
        "family": family,
        "layout": "record",
        "owner_function": owner,
        "effective": effective,
        "classification": classification,
        "trust": trust,
        "status": "in_force",
        "decisions": decisions,
    }
    meta.update(extra)
    return meta


def _table(header: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


OPS = {
    4: ("2024-09-26 1900", "2024-09-27 0700", "2024-09-26"),
    5: ("2024-09-27 0700", "2024-09-27 1900", "2024-09-27"),
    6: ("2024-09-27 1900", "2024-09-28 0700", "2024-09-27"),
    7: ("2024-09-28 0700", "2024-09-28 1900", "2024-09-28"),
}
OBJECTIVES = {
    4: [
        "Provide for the safety of SGW and mutual-aid personnel; all crews sheltered by H-12 and released only "
        "on the Safety Officer's all-clear.",
        "Keep critical-facility feeders and water pump stations under watch; report trips on FDR-AIK-2207 and "
        "FDR-AIK-2231 to the Duty Manager within 15 min.",
        "Confirm portable generator readiness at DEP-AIK-GRANITEVILLE (MGEN-HALBERD-500) for dispatch at first light.",
    ],
    5: [
        "Patrol Priority 1 feeders first (DOM 14.215 Att. A); restore hospital and pump-station supply.",
        "Hold zone pressure at PS-17 Pellicott Road Booster; dispatch the portable generator on the Water Incident "
        "Lead's order (WDS 03.318).",
        "Stand up STG-AIK-SANDHILL-YARD and STG-RCH-MILLPOND-YARD for arriving mutual-aid crews; onboarding per "
        "OB-24-07.",
        "Issue boil water advisories where pressure falls below the state minimum (WQC 07.114, WQC 07.120).",
    ],
    6: [
        "Continue Priority 1 and 2 restoration through the night with bucket work only below the wind limit.",
        "Keep MGEN-HALBERD-500 fuelled at PS-17 until FDR-AIK-2207 is restored; fuel truck FTK-WREN-3 first.",
        "Complete damage assessment of feeder trunks in Aiken and Richmond districts for the global ETR.",
    ],
    7: [
        "Release the global ETR as a range per DOM 14.206 and PCN 02.044.",
        "Restore Priority 3 water and wastewater facilities; demobilise portable generators as grid returns.",
        "Begin partial rescission sampling for boil water zones where integrity is restored.",
        "Track crew rest periods (DOM 12.050) for crews on their third consecutive shift.",
    ],
}
EMPHASIS = {
    4: "Nobody climbs or works from a bucket until the wind drops. Downed wires are energised until proven otherwise.",
    5: "Hospital supply first: FDR-AIK-2207 trunk and PS-17. Three-part communication on every switching instruction.",
    6: "Night work: two-person rule at every pole. Report flooded low-water crossings to Logistics on F-MAL-030.",
    7: "Fatigue is the hazard today. Check rest hours before every assignment.",
}


def ics202(op: int, rng: random.Random) -> GenDoc:
    start, end, eff = OPS[op]
    objs = "\n".join(f"{chr(97 + i)}. {o}" for i, o in enumerate(OBJECTIVES[op]))
    weather = (
        rng.choice(
            [
                "Tropical storm conditions ending by 0900; gusts 35-45 mph inland.",
                "Winds easing to 10-15 mph; scattered showers; river flooding on the Edisto and Savannah tributaries.",
                "Clear, 84 F high; heat index near 95 F in the afternoon.",
            ]
        )
        if op > 4
        else "Hurricane Helene, Cat 1 to tropical storm over the area; sustained 50-60 mph, gusts to 70 mph."
    )
    body = f"""# INCIDENT OBJECTIVES (ICS 202)
1. Incident Name: {INCIDENT}
2. Operational Period: Date From: {start[:10]}  Date To: {end[:10]}  Time From: {start[11:]}  Time To: {end[11:]} (EDT)
# 3. Objective(s)
{objs}
# 4. Operational Period Command Emphasis
{EMPHASIS[op]}
General Situational Awareness: {weather}
5. Site Safety Plan Required? Yes [X]  No [ ]   Approved Site Safety Plan(s) Located at: EOC Safety desk, binder S-{op}
# 6. Incident Action Plan (the items checked below are included in this Incident Action Plan)
[X] ICS 203  [X] ICS 204  [X] ICS 205  [ ] ICS 205A  [X] ICS 206  [X] ICS 208  [X] Map/Chart  [ ] Weather Forecast/Tides/Currents
7. Prepared by: Name: Okonkwo, Adaeze N.  Position/Title: Planning Section Chief  Signature: A. Okonkwo
8. Approved by Incident Commander: Name: Wingard, Lorraine T.  Signature: L. T. Wingard
ICS 202 | IAP Page 1 | Date/Time: {eff} {start[11:]}
"""
    meta = _record(
        f"IAP-HEL-24-OP{op:02d}/202",
        f"ICS 202 Incident Objectives, Helene, Operational Period {op}",
        "form_record",
        eff,
        "command",
        ["D1", "D2"],
    )
    return GenDoc(meta, body)


DIVISIONS = {
    (4, 1): ("Richmond South", "STG-RCH-MILLPOND-YARD", ["CRW-HARRIER-0103", "CRW-MERLIN-0102", "CRW-PLOVER-0105"],
             ["Hold crews at the yard until the all-clear.", "Patrol FDR-AIK-2238 trunk at first light.",
              "Report every tree on line on F-DOM-118 with photo."]),
    (5, 1): ("Aiken South", "STG-AIK-SANDHILL-YARD", ["CRW-SHRIKE-0104", "CRW-KESTREL-0101", "CRW-OSPREY-07"],
             ["Patrol and restore FDR-AIK-2231 trunk (hospital-adjacent water facilities) before laterals.",
              "Make safe downed wires at Gadsby Neck Road crossings (DOM 14.120).",
              "Replace transformer banks only after the trunk is energised."]),
    (6, 2): ("Aiken North", "STG-AIK-SANDHILL-YARD", ["CRW-OSPREY-04", "CRW-KESTREL-02", "CRW-HARRIER-0202"],
             ["Hold FDR-AIK-2207 trunk energised; patrol laterals off the Cedarfall tap.",
              "Coordinate with Water Branch before any planned outage on FDR-AIK-2207 (PS-17 on portable generator).",
              "Then FDR-AIK-2219 laterals, worst first per damage score queue."]),
    (6, 3): ("Richmond North", "STG-RCH-MILLPOND-YARD", ["CRW-MERLIN-0201", "CRW-PLOVER-0204", "CRW-SHRIKE-0203"],
             ["Restore FDR-AIK-2214 and FDR-AIK-2225 trunks.", "Mobile substation standby at Cawthorne Bluff (TSO 06.120 not affected).",
              "Report flooded crossings to Logistics before routing fuel."]),
}  # fmt: skip


def ics204(op: int, seq: int, rng: random.Random) -> GenDoc:
    start, end, eff = OPS[op]
    div, yard, crews, work = DIVISIONS[(op, seq)]
    rows = [[c, f"{rng.choice(['Ruff', 'Bledsoe', 'Moultrie', 'Pinckney', 'Dantzler', 'Kinard'])}, {rng.choice('ABDJKLMRT')}.",
             str(rng.choice([4, 5, 6])), f"Ch {rng.choice([3, 4, 7])} / 803-555-0{rng.randint(100, 199)}", ""]
            for c in crews]  # fmt: skip
    if rng.random() < 0.5:
        rows[-1][-1] = "~~released 1530~~ RT"
    body = (
        f"""# ASSIGNMENT LIST (ICS 204)
1. Incident Name: {INCIDENT}
2. Operational Period: Date From: {start[:10]}  Date To: {end[:10]}  Time From: {start[11:]}  Time To: {end[11:]}
3. Branch: Electric Operations  Division: {div}  Group: n/a  Staging Area: {yard}
# 4. Operations Personnel
Operations Section Chief: Thibodeaux, Marcus R.  Branch Director: Lumpkin, Harlan E.  Division/Group Supervisor: Dukes, Merritt A.
# 5. Resources Assigned
{_table(["Resource Identifier", "Leader", "# of Persons", "Contact (radio/phone)", "Reporting Info/Notes/Remarks"], rows)}
# 6. Work Assignments
"""
        + "\n".join(f"{chr(97 + i)}. {w}" for i, w in enumerate(work))
        + f"""
# 7. Special Instructions
No bucket work above 30 mph sustained wind. Treat every conductor as energised until tested and grounded (TSO 06.130).
Switching only on an issued SWO with repeat-back (TSO 06.110).
# 8. Communications
Division net Ch {rng.choice([3, 4, 7])}; Storm Room desk 803-555-0142 (after hours same number, roll to EOC).
9. Prepared by: Name: Bazemore, Tamsin L.  Position/Title: Resources Unit Leader  Date/Time: {eff} {start[11:]}
ICS 204 | IAP Page {seq + 2} | Date/Time: {eff} {start[11:]}
"""
    )
    meta = _record(
        f"IAP-HEL-24-OP{op:02d}/204-{seq:02d}",
        f"ICS 204 Assignment List, Helene, Operational Period {op}, Division {div}",
        "form_record",
        eff,
        "operations",
        ["D2", "D4"],
    )
    return GenDoc(meta, body)


def ics201() -> GenDoc:
    body = f"""# INCIDENT BRIEFING (ICS 201)
1. Incident Name: {INCIDENT}
2. Incident Number: SGW-INC-24-0031
3. Date/Time Initiated: Date: 2024-09-26  Time: 0600 EDT
4. Map/Sketch: Forecast 34-kt wind swath over Aiken and Richmond districts (EOC map wall, layer NHC adv. 15).
# 5. Situation Summary and Health and Safety Briefing
Hurricane Helene forecast to move north through east Georgia and western South Carolina tonight, inland as a
Cat 1 to strong tropical storm. Event Type 1 set by the IC at 0545 (GEP 00.010); Activation Level 1 from 1200.
Mutual-aid request released to SEE at H-96 (GEP 2H.01 Rev F); first crews due at the yards from this evening.
Safety: shelter all crews by H-12; no bucket work above the wind limit; carbon monoxide warning at every
portable generator.
6. Prepared by: Name: Okonkwo, Adaeze N.  Position/Title: Planning Section Chief  Date/Time: 2024-09-26 0615
# 7. Current and Planned Objectives
a. Pre-stage crews outside the forecast 34-kt swath; release to divisions after the all-clear.
b. Confirm generator readiness at critical facilities (H-24 checks complete for 37 of 41 sites; 4 open).
c. Pre-deliver fuel to PS-38 and PS-52 ahead of forecast flooding at Copperleaf Road and Deerwater Spur (GEP 2F.01).
# 8. Current and Planned Actions, Strategies, and Tactics
{_table(["Time", "Actions"], [["0600", "EOC Level 1 staffing called; Duty Manager briefed IC on Event Type recommendation."], ["0745", "Logistics confirmed STG-AIK-SANDHILL-YARD open; Millpond yard opens 1400."], ["0900", "Altamaha Fuel & Lube placed on standby under MAL-CTR-0447."], ["1130", "~~Water Branch to test MGEN-HALBERD-500~~ moved to 1300 TLB"], ["1300", "MGEN-HALBERD-500 load test passed at DEP-AIK-GRANITEVILLE."]])}
# 9. Current Organization
IC Wingard, L.; Safety Ravenel, C.; PIO Gadsden, Y.; Ops Thibodeaux, M.; Plans Okonkwo, A.; Log Huggins, D.;
Water Branch Sistrunk, O.; Water Compliance Quattlebaum, R.
# 10. Resource Summary
{_table(["Resource", "Date/Time Ordered", "ETA", "Arrived", "Notes"], [["SEE line crews, 22", "2024-09-25 0800", "2024-09-26 2100", "", "Sandhill 12 / Millpond 9 (capacity), 1 overflow"], ["Portable generator 500 kW", "own", "on hand", "X", "MGEN-HALBERD-500 at Graniteville"], ["Fuel truck", "own", "on hand", "X", "FTK-WREN-3"]])}
"""
    meta = _record("ICS201-HEL-24-0926", "ICS 201 Incident Briefing, Helene, 2024-09-26", "form_record",
                   "2024-09-26", "command", ["D1", "D2"])  # fmt: skip
    return GenDoc(meta, body)


def ics213rr(num: int, item: str, qty: str, loc: str, when: str, priority: str, notes: str) -> GenDoc:
    body = f"""# RESOURCE REQUEST MESSAGE (ICS 213 RR)
1. Incident Name: {INCIDENT}
2. Date/Time: {when}
3. Resource Request Number: RR-{num:04d}
# 4. Order
{_table(["Qty", "Kind", "Type", "Detailed Item Description", "Requested Arrival Date/Time", "Estimated"], [[qty, item.split(":")[0], item.split(":")[1], item.split(":")[2], when, "-"]])}
5. Requested Delivery/Reporting Location: {loc}
6. Suitable Substitute(s) and/or Suggested Source(s): {notes}
7. Requested by Name/Position: Sistrunk, Odell M. / Water Incident Lead
8. Priority: [{"X" if priority == "Urgent" else " "}] Urgent  [{"X" if priority == "Routine" else " "}] Routine  [ ] Low
9. Section Chief Approval: Huggins, D. J.
10. Logistics Order Number: LOG-24-0927-{num % 100:02d}
11. Supplier Phone/Fax/Email: per MAL 05.040 vendor list
13. Approval Signature of Auth Logistics Rep: D. Huggins   14. Date/Time: {when}
15. Order placed by (check box): [X] SPUL  [ ] PROC
16. Reply/Comments from Finance: n/a for this order
"""
    meta = _record(f"ICS213RR-HEL-24-{num:04d}", f"ICS 213 RR Resource Request {num:04d}, Helene", "form_record",
                   when[:10], "logistics", ["D3"])  # fmt: skip
    return GenDoc(meta, body)


def ics214(doc_id: str, title: str, op: int, name: str, position: str, entries: list[tuple[str, str]],
           owner: str, decisions: list[str]) -> GenDoc:  # fmt: skip
    start, end, eff = OPS[op]
    body = f"""# ACTIVITY LOG (ICS 214)
1. Incident Name: {INCIDENT}
2. Operational Period: Date From: {start[:10]}  Date To: {end[:10]}  Time From: {start[11:]}  Time To: {end[11:]}
3. Name: {name}   4. ICS Position: {position}   5. Home Agency (and Unit): SGW
# 7. Activity Log
{_table(["Date/Time", "Notable Activities"], [list(e) for e in entries])}
8. Prepared by: Name: {name}  Position/Title: {position}  Signature: on file
ICS 214, Page 1 | Date/Time: {end}
"""
    return GenDoc(_record(doc_id, title, "form_record", eff, owner, decisions), body)


SWITCHING = [
    ("0412", "SUB-AIK-BRAMBLEGATE / FDR-AIK-2207", "Isolate the Cedarfall tap for pole replacement; trunk stays energised (PS-17 supply).",
     [("R-2207-14", "Hot Line Hold"), ("SW-2207-33", "Open"), ("SW-2207-33", "Ground"), ("SW-2207-35", "Open")], "2024-09-27"),
    ("0413", "SUB-AIK-BRAMBLEGATE / FDR-AIK-2219", "Sectionalise FDR-AIK-2219 at Ruddell Landing to pick up 1,284 customers ahead of the washout.",
     [("R-2219-06", "Open"), ("SW-2219-21", "Open"), ("R-2219-06", "Close")], "2024-09-27"),
    ("0414", "SUB-AIK-GADSBYNECK / FDR-AIK-2231", "Restore FDR-AIK-2231 trunk after tree removal.",
     [("BRK-2231", "Open"), ("SW-2231-08", "Close"), ("BRK-2231", "Close")], "2024-09-28"),
    ("0415", "SUB-AIK-BRAMBLEGATE / FDR-AIK-2207", "Return Cedarfall tap to normal after pole replacement; remove grounds.",
     [("SW-2207-35", "Remove ground"), ("SW-2207-33", "Remove ground"), ("SW-2207-33", "Close"), ("R-2207-14", "Release Hot Line Hold")], "2024-09-28"),
    ("0416", "SUB-RCH-OGLETREE / FDR-RCH-1452", "Transfer 2.7 MW to FDR-RCH-1457 for transformer replacement at Ogletree.",
     [("TIE-1452-1457", "Close"), ("SW-1452-02", "Open"), ("BRK-1452", "Open"), ("BRK-1452", "Ground")], "2024-09-26"),
]  # fmt: skip


def swo(n: int, rng: random.Random) -> GenDoc:
    num, station, purpose, steps, day = SWITCHING[n]
    t = rng.randint(6, 18) * 60 + rng.randint(0, 59)
    rows = []
    for i, (dev, op) in enumerate(steps, start=1):
        t += rng.randint(3, 14)
        hhmm = f"{t // 60 % 24:02d}{t % 60:02d}"
        rows.append(
            [
                str(i),
                dev,
                op,
                "SO " + rng.choice(["Ingle", "Strom", "Pettigrew"]),
                rng.choice(["CRW-OSPREY-04", "CRW-KESTREL-02", "CRW-HARRIER-0202", "CRW-MERLIN-0201"]),
                "Y",
                hhmm,
            ]
        )
    body = f"""# SWITCHING ORDER
SWO Number: SWO-2409-{num}    Station / Feeder: {station}
Purpose: {purpose}
Clearance holder: {rng.choice(["Kinard, J.", "Dantzler, R.", "Moultrie, A."])}    Requested by: Division Supervisor    Approved by: Pettigrew, Anselm K. (Transmission Operations)
Prepared under TSO 06.110. Three-part communication on every step; the performer restates device, location and operation exactly as spoken before acting.
# Steps
{_table(["Step", "Device", "Operation", "Ordered", "Performed", "Repeat-back", "Time"], rows)}
# Completion
All steps complete. Clearance {"issued" if "Ground" in " ".join(o for _, o in steps) else "n/a"} and logged. Order closed by the System Operator; copy to Storm Room.
"""
    meta = _record(f"SWO-2409-{num}", f"Switching Order SWO-2409-{num}, {station}", "switching_order", day,
                   "operations", ["D4"], trust="verified_internal")  # fmt: skip
    return GenDoc(meta, body)


SITREPS = {
    1: ("2024-09-25", "17:00", "Helene forecast to reach the area as a hurricane overnight on 2024-09-26.",
        ["Event Type 1 recommendation under review; Activation Level 3 (partial).",
         "Mutual-aid request decision taken at H-96 (GEP 2H.01 Rev F); 22 crews requested through SEE.",
         "Fuel pre-delivery to PS-38 and PS-52 ordered ahead of forecast flooding (GEP 2F.01)."],
        "No customer outages attributed to Helene yet.", "All pump stations on grid supply. Generator readiness checks at H-24 scheduled.",
        "SR-HEL-24-02 at 17:00 EDT 2024-09-26."),
    2: ("2024-09-26", "17:00", "Helene inland over north Florida, moving north-northeast at 23 mph.",
        ["Event Type 1 (Catastrophic) set by the IC at 05:45 EDT; Activation Level 1 since 12:00 EDT.",
         "Crews pre-staged outside the forecast 34-kt swath; shelter by H-12 (approx. 23:00 EDT).",
         "MGEN-HALBERD-500 load-tested at DEP-AIK-GRANITEVILLE, ready."],
        "About 41,000 customers out from outer bands, mostly Richmond district.", "Pump stations on grid; PS-38 and PS-52 tanks full, fuel pre-delivered.",
        "SR-HEL-24-03 at 07:00 EDT 2024-09-27."),
    3: ("2024-09-27", "07:00", "Helene passed over the service area overnight; tropical-storm winds ending by mid-morning.",
        ["As of 06:30 EDT about 1.37 million customers out, still rising.",
         "FDR-AIK-2207 tripped at 05:30Z (01:30 EDT); PS-17 Pellicott Road Booster on tank TNK-PS17-CEDARFALL.",
         "Crews released from shelter at 06:12 EDT where the Safety Officer gave the all-clear."],
        "Damage assessment starting on Priority 1 feeders (DOM 14.215).", "PS-17 zone drawing down; Water Incident Lead watching pressure every 15 min (WDS 03.240).",
        "SR-HEL-24-04 at 17:00 EDT 2024-09-27."),
    5: ("2024-09-28", "07:00", "Clearing skies; river flooding on lower tributaries continues.",
        ["As of 06:00 EDT about 1.31 million customers out, down 19% from the 1,612,400 peak at 09:15 EDT 2024-09-27.",
         "PS-17 zone back above the 25 psi floor at 21:21Z; grid supply to PS-17 restored at 02:29Z on FDR-AIK-2207.",
         "MGEN-HALBERD-500 demobilised at 02:30Z and returning to Graniteville."],
        "Global ETR in preparation for release within 24 h of the all-clear (DOM 14.206 Rev K).", "Boil water advisory in effect for WZ-PS17-CEDARFALL pending rescission samples.",
        "SR-HEL-24-06 at 17:00 EDT 2024-09-28."),
    6: ("2024-09-28", "17:00", "Fair weather; heat index near 95 F tomorrow.",
        ["As of 16:00 EDT about 1.06 million customers out.",
         "Global ETR released as a range (PCN 02.044); next update 09:00 EDT 2024-09-29.",
         "Mutual-aid crews on site: 214 line crews, 61 tree crews."],
        "Restoration on Priority 3 and 4 feeders; transformer replacements rising.", "Rescission sampling under way in WZ-PS17-CEDARFALL (WQC 07.114).",
        "SR-HEL-24-07 at 17:00 EDT 2024-09-29."),
}  # fmt: skip


def sitrep(n: int) -> GenDoc:
    day, hour, wx, summary, electric, water, nxt = SITREPS[n]
    body = (
        f"""TLP:CLEAR
SGW Situation Report #{n} | {day} | {hour} EDT
Incident: {INCIDENT}    REPORT DISTRIBUTION: SGW EOC, county EOC liaisons, SC and GA state EOCs
# Executive Summary
"""
        + "\n".join(f"{s}" for s in summary)
        + f"""
# Weather
{wx}
# Electric
{electric}
# Water
{water}
# Resources
Staging: STG-AIK-SANDHILL-YARD and STG-RCH-MILLPOND-YARD open. Fuel: Altamaha Fuel & Lube on call (MAL-CTR-0447).
# Safety
No recordable injuries this period. Carbon monoxide reminder issued for all portable generator sites.
# Next report
{nxt}
TLP:CLEAR
"""
    )
    meta = _record(f"SR-HEL-24-{n:02d}", f"SGW Situation Report #{n}, Hurricane Helene, {day} {hour} EDT", "sitrep",
                   day, "planning", ["D4"], trust="verified_internal")  # fmt: skip
    return GenDoc(meta, body)


RUNBOOKS = [
    ("RB-MGEN-HALBERD-500", "Runbook: Portable Generator MGEN-HALBERD-500 (500 kW Trailer Unit)", "C", "2024-04-22",
     [["Rated output (kW)", "500"], ["Voltage", "480 V, 3-phase"], ["Fuel tank (gal)", "720"], ["Burn at 75% load (gal/h)", "27.8"], ["Run time at 75% load (h)", "25.9"], ["Home", "DEP-AIK-GRANITEVILLE"]],
     ["Confirm the dispatch order from the Water Incident Lead (WDS 03.318) and the destination station.", "Walk-around: tyres, hitch, breakaway cable, fuel level at least 90%.",
      "Tow to site; plan 150 min from dispatch to pumping for PS-17 (travel, cable connection, manual transfer).", "Connect cam-lock cables to the station's generator receptacle; verify phase rotation before closing.",
      "Start, warm up 5 min, close output breaker, operate the manual transfer switch.", "Log fuel level every 4 h on F-WDS-207; request fuel at 60% per WDS 03.322.",
      "On grid return, transfer back, cool down 10 min, disconnect, demobilise."]),
    ("RB-GEN-PS38-COPPERLEAF", "Runbook: Standby Generator GEN-PS38-COPPERLEAF (350 kW Diesel, PS-38)", "B", "2023-10-02",
     [["Rated output (kW)", "350"], ["Fuel tank (gal)", "1,000 (sub-base)"], ["Burn at 75% load (gal/h)", "19.6"], ["Transfer", "Automatic transfer switch, 10 s"]],
     ["Confirm automatic start on loss of utility; check ATS position.", "Read fuel level at start and every 4 h (F-WDS-207).",
      "Raise a refuel request at 60% tank (WDS 03.322); Copperleaf Road is a listed low-water crossing (GEP 2F.01 Att. 2), pre-deliver before flooding.",
      "Weekly exercise without load; monthly load test per WDS 03.350."]),
    ("RB-GEN-PS52-DEERWATER", "Runbook: Standby Generator GEN-PS52-DEERWATER (300 kW Diesel, PS-52)", "D", "2024-02-26",
     [["Rated output (kW)", "300"], ["Fuel tank (gal)", "840"], ["Burn at 75% load (gal/h)", "16.9"], ["Transfer", "Automatic transfer switch, 10 s"]],
     ["Confirm automatic start and transfer.", "Log fuel every 4 h; refuel request at 60%.", "Route via Deerwater Spur only when open; alternate route via SC 302 per Logistics.",
      "After any run over 8 h, check coolant and oil before the next start."]),
    ("RB-FTK-WREN-3", "Runbook: Fuel Truck FTK-WREN-3 (2,800 gal Diesel Tanker)", "B", "2024-03-11",
     [["Capacity (gal)", "2,800"], ["Base", "DEP-AIK-GRANITEVILLE"], ["Load and drive, planning value (min)", "90"], ["Driver qualification", "CDL with tank and hazmat endorsements"]],
     ["Take dispatch from Logistics on F-MAL-022.", "Load at the depot rack; record gallons and seal numbers.", "Drive the route Logistics confirms; never through water over the roadway.",
      "Fuel the generator to 95%; record start and end gallons on F-WDS-207 at site.", "Return to depot; report remaining gallons to Logistics."]),
    ("RB-MSUB-ORCHARDKNOB-02", "Runbook: Mobile Substation MSUB-ORCHARDKNOB-02 (115/23 kV, 20 MVA)", "E", "2022-11-07",
     [["Rating (MVA)", "20"], ["Primary / secondary (kV)", "115 / 23"], ["Set-up time, planning value (h)", "9"], ["Escort", "State oversize permit required"]],
     ["Request through TSO per DOM 14.170.", "Survey pad, access and clearances before moving.", "Ground the trailer and test before energising (TSO 06.130).",
      "Energise only on an issued switching order (TSO 06.110)."]),
    ("RB-BPS46-TANYARD-ATS", "Runbook: BPS-46 Tanyard Branch Booster Automatic Transfer Switch", "C", "2023-06-19",
     [["ATS rating (A)", "800"], ["Transfer delay (s)", "10"], ["Retransfer delay (min)", "30"], ["Exercise", "Monthly with load (WDS 03.350)"]],
     ["Confirm generator running and ATS on emergency.", "Do not bypass the ATS without the Water Incident Lead's approval.", "On utility return, allow the 30 min retransfer delay; log on F-WDS-207."]),
]  # fmt: skip


def runbook(n: int) -> GenDoc:
    doc_id, title, rev, eff, specs, steps = RUNBOOKS[n]
    body = (
        "# 1.0 PURPOSE\nOperate the unit safely and keep it available during declared events.\n# 2.0 DATA\n"
    )
    body += _table(["Item", "Value"], specs) + "\n# 3.0 OPERATION\n"
    body += "\n".join(f"3.{i} {s}" for i, s in enumerate(steps, start=1))
    body += "\nCAUTION: Carbon monoxide. Never run a generator inside a building or near an air intake.\n"
    body += "# 4.0 RECORDS\nRun hours and fuel on F-WDS-207; defects to the maintenance work queue.\n"
    meta = {
        "doc_id": doc_id, "title": title, "family": "runbook", "layout": "controlled",
        "owner_function": "logistics" if "FTK" in doc_id else ("operations" if "MSUB" in doc_id else "water_operations"),
        "sme": "Lumpkin, Harlan E.", "revision": rev, "effective": eff, "next_review": "2025-05-31",
        "approvals": [{"function": "water_operations", "position": "Manager, Water Distribution", "name": "Sistrunk, Odell M.", "date": eff}],
        "classification": "SGW Internal - Controlled", "trust": "verified_internal", "status": "in_force", "decisions": ["D3"],
        "changes": [{"rev": rev, "date": eff, "section": "2.0", "change": "Data table updated after annual load test."}],
    }  # fmt: skip
    return GenDoc(meta, body)


INSPECTIONS = [
    ("INS-WDS-2409-0088", "Field Inspection, PS-38 Copperleaf Generator Pre-Storm Check", "2024-09-25", "water_operations",
     "GEN-PS38-COPPERLEAF ran 30 min under load. Fuel 96%. Battery 12.8 V. No leaks. ATS transferred in 9 s. Copperleaf Road dry at 1410."),
    ("INS-WDS-2409-0091", "Field Inspection, TNK-PS17-CEDARFALL Level Transmitter", "2024-09-27",
     "water_operations", "Level transmitter reading matched sight gauge within 0.4 ft at 1215. Hatch secure. Vent screen intact. No overflow evidence."),
    ("INS-DOM-2409-0214", "Damage Assessment Patrol Note, FDR-AIK-2219 Lateral L-7", "2024-09-27", "operations",
     "Two poles broken at Ruddell Landing (P-2219-711, P-2219-713). Tree on primary span 712. Damage state: extensive. Photos queued. Recorded on F-DOM-118."),
    ("INS-TSO-2409-0031", "Substation Inspection, SUB-AIK-BRAMBLEGATE Post-Storm", "2024-09-27", "operations",
     "Yard dry. Fence intact. Transformer T2 oil level normal. Breaker BRK-2207 tripped and locked out at 0530Z, reclosed after patrol at 0912Z per SO."),
    ("INS-WDS-2408-0076", "Field Inspection, LS-212 Cawthorne Bluff Lift Station", "2024-08-09", "water_operations",
     "Hurricane Debby follow-up. Wet well level normal. Pump 2 seal leak noted, work order raised. Bypass pump connection point tested."),
]  # fmt: skip


def inspection(n: int, rng: random.Random) -> GenDoc:
    doc_id, title, day, owner, finding = INSPECTIONS[n]
    inspector = rng.choice(["Kinard, J.", "Dantzler, R.", "Moultrie, A.", "Bledsoe, T."])
    body = f"""# INSPECTION REPORT
Report No.: {doc_id}    Date: {day}    Inspector: {inspector}
Location: {title.split(", ", 1)[1]}
# Findings
{finding}
# Condition
{_table(["Item", "Condition", "Action"], [["Access", rng.choice(["Good", "Fair - debris cleared"]), "None"], ["Equipment", rng.choice(["Serviceable", "Serviceable, defect logged"]), "Work order if noted"], ["Safety", "No hazards remaining", "None"]])}
Reviewed by: {rng.choice(["Sistrunk, O.", "Lumpkin, H.", "Dukes, M."])}
"""
    return GenDoc(_record(doc_id, title, "inspection", day, owner, ["D3"]), body)


def notices() -> list[GenDoc]:
    ga = """Public Notification
BOIL WATER ADVISORY
Notice No. BWA-GA-2409-07
Due to a loss of pressure in the water distribution system caused by Hurricane Helene power outages, SGW, in
consultation with the Georgia Environmental Protection Division, is issuing a boil water advisory for customers
in the area listed below, out of an abundance of caution.
# Area affected
Augusta-Richmond County service zone WZ-RCH-OGLETREE: Ogletree Road, Bunche Lane, Pruitt Mill Circle, and all
streets east of Tobacco Spur to the zone valve at Sardis Crossroads.
# What to do
Heat water until bubbles come quickly from the bottom of the container, then continue heating for one minute.
Let the water cool before use. Use boiled or bottled water for drinking, making ice, brushing teeth, washing
food and preparing baby formula.
# How long
We expect the advisory to last at least 48 hours while samples are collected and tested.
We will provide the next update at: 18:00 EDT 2024-09-28.
Questions: SGW Water Customer Line 706-555-0188 (24 hours).
Issued by: Quattlebaum, Rhea D., Water Compliance Officer. Approved: Water Incident Lead and Water Compliance Officer.
"""
    rescind = """Public Notification
BOIL WATER ADVISORY PARTIALLY RESCINDED
Notice No. BWA-GA-2410-02 (partial rescission of BWA-GA-2409-07)
Tests of samples from the zone show the water is safe to drink in the area listed below. The advisory issued
2024-09-27 is lifted for these streets only.
# Area where the advisory is lifted
Ogletree Road, Bunche Lane and Pruitt Mill Circle.
# Area where the advisory remains in effect
Streets east of Tobacco Spur to Sardis Crossroads.
After the advisory is lifted, flush all faucets for a minimum of two minutes before use.
We will provide the next update at: 12:00 EDT 2024-10-05.
Questions: SGW Water Customer Line 706-555-0188.
Issued by: Quattlebaum, Rhea D., Water Compliance Officer.
"""
    sc = """BOIL WATER NOTICE
Notice No. BWN-SC-2409-03
SGW, in coordination with the South Carolina Department of Environmental Services (SCDES), advises customers in
pressure zone WZ-PS17-CEDARFALL to boil water before drinking. Pressure fell below the minimum at service
connections after a power loss at the PS-17 Pellicott Road Booster on 2024-09-27.
# Area affected
Cedarfall zone: Pellicott Road, Tallow Branch Road, Cedarfall Estates, and Gadsby Neck Road north of the creek.
Tallow Branch hospital facilities staff were notified directly.
# What to do
Bring water to a rolling boil for one minute, let it cool, then use it for drinking, cooking and brushing teeth.
SCDES and SGW will lift this notice when tests confirm there is no longer a public health concern.
We will provide the next update at: 09:00 EDT 2024-09-28.
Questions: SGW Water Customer Line 803-555-0177.
Approved: Water Incident Lead and Water Compliance Officer.
"""
    return [
        GenDoc(_record("BWA-GA-2409-07", "Boil Water Advisory BWA-GA-2409-07, Ogletree Zone", "notice_issued",
                       "2024-09-27", "compliance", ["D3"], trust="verified_internal", classification="Public", states=["GA"]), ga),
        GenDoc(_record("BWA-GA-2410-02", "Partial Rescission BWA-GA-2410-02, Ogletree Zone", "notice_issued",
                       "2024-10-04", "compliance", ["D3"], trust="verified_internal", classification="Public", states=["GA"]), rescind),
        GenDoc(_record("BWN-SC-2409-03", "Boil Water Notice BWN-SC-2409-03, Cedarfall Zone", "notice_issued",
                       "2024-09-27", "compliance", ["D3"], trust="verified_internal", classification="Public", states=["SC"]), sc),
    ]  # fmt: skip


CHECKLISTS = [
    ("F-GEP-012", "Hurricane H-Hour Checklist (Electric)", "D", "2024-09-16", "operations", [
        ("H-120", "Duty Manager", "Review NHC advisory; propose Event Type to IC (GEP 00.010)"),
        ("H-96", "Duty Manager / Logistics Section Chief", "Decide mutual-aid request and pre-staging plan (GEP 2H.01 Rev F)"),
        ("H-72", "Logistics Section Chief", "Issue pre-staging orders; confirm yard capacity (DOM 12.040)"),
        ("H-48", "Division Supervisors", "Crews staged outside forecast 34-kt swath"),
        ("H-24", "Distribution Ops", "Critical-facility feeder list confirmed (DOM 14.215 Att. A)"),
        ("H-12", "Safety Officer", "All crews sheltered; buckets stowed"),
        ("H+0", "Duty Manager", "Start trip log; no field work until all-clear")]),
    ("F-GEP-013", "Hurricane H-Hour Checklist (Water)", "C", "2024-09-16", "water_operations", [
        ("H-96", "Water Incident Lead", "Confirm portable generator and fuel truck availability (MAL 05.040)"),
        ("H-72", "Logistics", "Pre-deliver fuel where routes cross low-water crossings (GEP 2F.01)"),
        ("H-48", "Water Ops", "Fill elevated tanks to operating maximum"),
        ("H-24", "Water Ops", "Generator readiness checks at critical facilities; log on F-WDS-207"),
        ("H-12", "Water Compliance Officer", "Pre-draft boil water notices for at-risk zones (PCN 02.031, PCN 02.032)"),
        ("H+0", "Water Incident Lead", "Pressure watch every 15 min on booster zones without onsite generation")]),
    ("F-GEP-014", "Joint Command H-Hour Checklist", "B", "2024-05-13", "command", [
        ("H-120", "Incident Commander", "Set Event Type and Activation Level separately (GEP 00.010)"),
        ("H-96", "Incident Commander", "Approve mutual-aid request with Logistics Section Chief (MAL 05.012)"),
        ("H-72", "PIO", "Pre-storm customer messaging released"),
        ("H-24", "Incident Commander", "Confirm cross-domain priorities: hospital feeders and their pump stations (DOM 14.215)"),
        ("H-12", "Safety Officer", "Shelter order issued")]),
    ("F-DOM-121", "Storm Room Opening Checklist", "F", "2023-08-07", "operations", [
        ("Open", "Duty Manager", "Storm Room staffed per DOM 14.105 roster; shift turnover log started"),
        ("Open", "OMS Lead", "Confirm OMS health; if degraded, switch to DOM 14.190 manual mode"),
        ("Open", "Planning", "ETR Specialist assigned for the event (DOM 14.206)"),
        ("Open", "Communications", "Storm desk phone 803-555-0142 forwarded to the EOC after hours")]),
]  # fmt: skip


def checklist(n: int) -> GenDoc:
    doc_id, title, rev, eff, owner, rows = CHECKLISTS[n]
    body = "# CHECKLIST\nInitial and time each row when done. Return the completed form to the Planning Section.\n"
    body += "\n".join(f"[ ] {h} | {who} | {task} | ____ initials / time" for h, who, task in rows)
    body += "\n# NOTES\nH-hour is the forecast arrival of tropical-storm-force (34-kt) winds at the service area edge.\n"
    meta = {
        "doc_id": doc_id, "title": title, "family": "checklist", "layout": "controlled", "owner_function": owner,
        "sme": "Varnadoe, Celeste M.", "revision": rev, "effective": eff, "next_review": "2025-05-31",
        "approvals": [{"function": "command", "position": "Vice President, Emergency Management", "name": "Wingard, Lorraine T.", "date": eff}],
        "classification": "SGW Internal - Controlled", "trust": "verified_internal", "status": "in_force", "decisions": ["D1", "D2"],
        "changes": [{"rev": rev, "date": eff, "section": "Rows", "change": "Aligned with the current hurricane annex."}],
    }  # fmt: skip
    return GenDoc(meta, body)


def generate() -> list[GenDoc]:
    rng = random.Random(SEED)  # noqa: S311
    docs: list[GenDoc] = [ics202(op, rng) for op in (4, 5, 6, 7)]
    docs += [ics204(op, seq, rng) for op, seq in DIVISIONS]
    docs.append(ics201())
    docs.append(ics213rr(311, "Equipment:Pump:Trailer-mounted:6-inch diesel bypass pump with 200 ft suction and discharge hose",
                         "2", "LS-212 Cawthorne Bluff lift station", "2024-09-27 0940", "Urgent", "Rental pool via MAL 05.050"))  # fmt: skip
    docs.append(ics213rr(316, "Supplies:Water:Bulk:Potable water tanker 4,000 gal with hospital connection kit",
                         "1", "HSP-AIK-TALLOWBRANCH loading dock", "2024-09-27 1015", "Urgent", "Tanker pool; 120 min request to connection (WDS 03.240)"))  # fmt: skip
    docs.append(ics214("ICS214-HEL-24-OP06-LOG", "ICS 214 Activity Log, Logistics Section, Operational Period 6", 6,
                       "Huggins, Delmar J.", "Logistics Section Chief",
                       [("2024-09-27 1915", "Shift brief. 22 SEE crews at yards; Millpond at capacity."),
                        ("2024-09-27 2040", "FTK-WREN-3 loaded at Graniteville for PS-17 top-off."),
                        ("2024-09-27 2210", "Copperleaf Road reported flooded on F-MAL-030; PS-38 fuel already pre-delivered."),
                        ("2024-09-28 0030", "~~Altamaha call for PS-52~~ not needed, tank at 71% RH"),
                        ("2024-09-28 0245", "MGEN-HALBERD-500 released from PS-17; return to depot.")], "logistics", ["D2", "D3"]))  # fmt: skip
    docs.append(ics214("ICS214-HEL-24-OP05-WTR", "ICS 214 Activity Log, Water Branch, Operational Period 5", 5,
                       "Sistrunk, Odell M.", "Water Incident Lead",
                       [("2024-09-27 0715", "PS-17 on tank since grid loss 0130 EDT; drawdown tracked every 15 min."),
                        ("2024-09-27 0605Z", "n/a - entry in wrong format, see 1005Z"),
                        ("2024-09-27 1005Z", "Cedarfall zone below 25 psi at the hospital connection. Compliance notified."),
                        ("2024-09-27 1145", "Hospital facilities manager notified; tanker requested on RR-0316."),
                        ("2024-09-27 1545Z", "Dispatch ordered: MGEN-HALBERD-500 to PS-17."),
                        ("2024-09-27 1815Z", "MGEN-HALBERD-500 running at PS-17; pressure recovering.")], "water_operations", ["D3"]))  # fmt: skip
    docs += [swo(i, rng) for i in range(len(SWITCHING))]
    docs += [sitrep(n) for n in (1, 2, 3, 5, 6)]
    docs += [runbook(i) for i in range(len(RUNBOOKS))]
    docs += [inspection(i, rng) for i in range(len(INSPECTIONS))]
    docs += notices()
    docs += [checklist(i) for i in range(len(CHECKLISTS))]
    return docs


def write_generated(
    out_dir: Path = CORPUS_DIR / "generated", writer: Callable[[Path, str], None] | None = None
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for doc in generate():
        path = out_dir / doc.file_name
        text = doc.source()
        if writer:
            writer(path, text)
        else:
            path.write_text(text, encoding="utf-8")
        paths.append(path)
    return paths
