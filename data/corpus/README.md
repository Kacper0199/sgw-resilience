# SGW procedure corpus (WP-18)

The retrieval corpus behind `search_procedures` and `answer_sop`: SGW controlled documents and issued records,
plus a few US federal public-domain documents. Style follows the R-CORPUS style guide (manual ids such as
`WQC 07.114 Rev E/2`, control box, Revision Summary, running header and footer, "Page n of N").
Provenance, licences and the synthetic origin of the SGW documents are recorded in `MANIFEST.yaml` and
`data/ATTRIBUTION.md`, never inside the documents.

| Path | Holds |
| --- | --- |
| `src/core/*.md` | hand-written documents (core SOPs, plans, the six superseded pairs, the four hostile records) |
| `src/extra/*.md` | hand-written supporting documents (other SOPs, annexes, templates, bulletins, AARs) |
| `src/federal/*.md` | US federal public-domain documents, text as published, front matter added |
| `generated/` | records written by the template generator (`sgw rag corpus build`): ICS forms, switching orders, sitreps, runbooks, inspections, issued notices, checklists |
| `rendered/*.txt` | every document as a reader sees it (pages, headers, footers); built, committed, checked for drift |
| `headers/chunk_headers.jsonl` | contextual chunk headers (Haiku, generated once through the gateway, keyed by chunk hash) |
| `llm_fixtures/<node>/` | K11 recordings of the corpus LLM calls (chunk headers, `answer_sop` dev runs) for keyless replay |
| `MANIFEST.yaml` | one row per document: id, revision, status, dates, family, origin, licence, sha256 of the rendered text |

## Source format

A source file is YAML front matter plus a plain-text body. The renderer adds the title block, the control box,
the SUPERSEDED line, the Revision Summary, pagination, the running header and footer and the last-page
uncontrolled-copy line, so the body never repeats them.

```yaml
---
doc_id: "WQC 07.114"              # manual code, chapter.sequence; records use their serial
legacy_id: "WQP-22"               # optional former number, shown as "(formerly WQP-22)"
title: "Boil Water Advisory: Issuance, Notification and Rescission (Georgia Systems)"
family: sop                       # erp_section|annex|sop|operating_plan|checklist|form_record|notice_template|
                                  # notice_issued|switching_order|runbook|inspection|sitrep|aar|bulletin|agreement
layout: controlled                # controlled (control box) | record (forms, sitreps, notices, orders, notes)
owner_function: compliance        # command|operations|planning|logistics|water_operations|compliance|communications
sme: "Quattlebaum, Rhea D."       # surname first
revision: "E"                     # letters skip I, O, Q, S; omit for records
change: 2                         # optional Chg number
effective: 2024-06-03
supersedes: "WQC 07.114 Rev D/1 (eff. 2022-11-14)"     # optional
superseded_by: "..."              # only on a superseded revision; renders the SUPERSEDED line
expires: 2024-10-15               # optional (bulletins)
next_review: 2025-05-31
approvals:                        # position titles by function; names surname first
  - {function: water_operations, position: "Water Incident Lead", name: "Sistrunk, Odell M.", date: 2024-05-28}
classification: "SGW Internal - Controlled"   # Public | SGW Internal - Controlled | SGW Restricted - Operations
trust: verified_internal          # verified_internal (controlled docs) | internal_free_text (field records) | external
status: in_force                  # in_force | superseded
decisions: [D3]
states: [GA]
changes:                          # Revision Summary / Record of Changes rows, newest first
  - {rev: "E/2", date: 2024-08-26, section: "Att. B", change: "Contact roster updated."}
  - {rev: "E", date: 2024-06-03, section: "6.4", change: "Rescission sampling raised from 40 to 50 percent of coliform sample sites."}
---
```

Body rules:
- `# 6.0 PROCEDURE` starts a top-level section, `## 6.2 Notification` a subsection (the markers are removed
  in the rendered text; chunks break at them). Records may use `# ` headings for their form boxes.
- Tables are pipe rows with a header row and a `|---|` separator; units go in column headers.
- `<<PAGEBREAK>>` forces a page break; otherwise the renderer paginates.
- Plain text only: no `*`, `**`, backticks or Markdown links. Lists use `a.` `b.` or step numbers (`6.2.3`).
