---
doc_id: "PCN 02.044"
title: "Global ETR Public Release Template"
family: notice_template
layout: controlled
owner_function: planning
sme: "Varnadoe, Celeste M."
revision: "C"
effective: 2024-06-10
supersedes: "PCN 02.044 Rev B (eff. 2023-06-05)"
next_review: 2025-05-31
approvals:
  - {function: planning, position: "Manager, Storm Planning (ETR Specialist lead)", name: "Okonkwo, Adaeze N.", date: 2024-06-03}
  - {function: communications, position: "Director, Corporate Communications", name: "Gadsden, Yolanda P.", date: 2024-06-04}
  - {function: command, position: "Incident Commander; Vice President, Emergency Management", name: "Wingard, Lorraine T.", date: 2024-06-05}
classification: "SGW Internal - Controlled"
trust: verified_internal
status: in_force
decisions: [D4]
states: [SC, GA]
changes:
  - {rev: "C", date: 2024-06-10, section: "3.2", change: "Global ETR shall be released as a range; single-time wording removed."}
  - {rev: "C", date: 2024-06-10, section: "Part 2", change: "Spanish release text moved to PCN 02.050 annex."}
  - {rev: "B", date: 2023-06-05, section: "3.4", change: "Next update time made a required slot."}
---
# 1.0 PURPOSE

This template gives the wording and approval path for the public release of SGW's global estimated time of restoration (ETR) during Event Types 1 to 3.

# 2.0 SCOPE

Applies to system-wide and district-level global ETR releases on sgw web outage pages, social channels, media advisories and the IVR storm message. Does not apply to routine single-feeder outages.

# 3.0 RULES FOR USE

3.1 The ETR Specialist (Planning Section) proposes the global ETR per DOM 14.206 section 6. The Incident Commander approves it before release.

3.2 The public release states the global ETR as a range (most customers restored between an earliest and a latest time), never as a single time. Take the earliest and latest bounds (the low and high ends of the restoration window) from the approved estimate per DOM 14.206 section 6.

3.3 State the range per district when district estimates differ by more than 24 h. Otherwise use one system range.

3.4 Every release states the time of the next update. Use a clock time and date in EDT, not "later today".

3.5 Director, Corporate Communications, approves wording changes. Numbers come only from the approved Planning Section estimate.

3.6 Do not release a global ETR until the Incident Commander has approved the estimate. Damage assessment coverage rules are in DOM 14.206.

3.7 Releases shall go out within 30 min of Incident Commander approval.

| Slot | Source | Filled by | Required |
|---|---|---|---|
| [AS-OF TIME] | Planning Section estimate time stamp | Communications | Yes |
| [CUSTOMERS OUT] | OMS count at as-of time | Planning Section | Yes |
| [PEAK OUT] | OMS peak for the event | Planning Section | Yes |
| [EARLIEST] / [LATEST] | Approved global ETR range | ETR Specialist | Yes |
| [DISTRICT TABLE] | District ranges, when 3.3 applies | ETR Specialist | When applicable |
| [NEXT UPDATE] | Communications schedule | Communications | Yes |
| [CREW COUNT] | Logistics check-in total | Logistics Section Chief | Optional |

<<PAGEBREAK>>
# PART 1 - RELEASE TEXT (ENGLISH)

FOR IMMEDIATE RELEASE - [DATE], [AS-OF TIME] EDT

SGW Storm Restoration Update: [EVENT NAME]

As of [AS-OF TIME], about [CUSTOMERS OUT] SGW electric customers remain without power, down from a peak of [PEAK OUT].

SGW expects most customers to be restored between [EARLIEST] and [LATEST]. Some customers in the hardest-hit areas may be restored after this window.

[DISTRICT TABLE]

| District | Customers out | Most customers restored between |
|---|---|---|
| [DISTRICT] | [N] | [EARLIEST] and [LATEST] |

More than [CREW COUNT] line, tree and assessment workers are working in the field, including crews from other utilities.

Stay at least 35 ft away from downed wires and anything touching them. Report downed wires to 1-800-555-0144 or 911.

Do not run a portable generator indoors or in a garage. Do not connect a generator to home wiring without a transfer switch.

SGW will provide the next update at [NEXT UPDATE].

Outage map and updates: sgw outage page and SGW social channels.

# PART 2 - IVR STORM MESSAGE (60 s maximum)

"Thank you for calling SGW. As of [AS-OF TIME], SGW crews are restoring power after [EVENT NAME]. We expect most customers to be restored between [EARLIEST] and [LATEST]. Our next update will be at [NEXT UPDATE]. To report a downed wire, press 1 now."

# 4.0 APPROVAL ROUTING

4.1 ETR Specialist enters the range in the release slots.
4.2 Manager, Storm Planning, checks numbers against the approved estimate.
4.3 Incident Commander approves.
4.4 Communications Duty Officer publishes on all channels and logs the time.
4.5 After hours, call the EOC Communications line; the Communications Duty Officer carries the release phone.

# 5.0 REFERENCES

DOM 14.206 (ETR Development); PCN 02.050 (Storm Media Statement Template); GEP 03.020 (Storm Organization); PCN 04.010 (Regulatory Outage Reporting to the SC PSC).
