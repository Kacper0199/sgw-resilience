---
version: beta
name: SGW Resilience Decision Platform
description: Decision platform for a combined power and water utility; every open decision carries a computed deadline with its basis, evidence and accountable sign-off.
colors:
  canvas: "#E6ECF5"
  surface: "#FFFFFF"
  surface-2: "#F5F7FA"
  surface-3: "#ECEFF4"
  selected: "#E0EBFC"
  hair: "#DDE3EC"
  hair-strong: "#C3CCDA"
  divider: "#9AA8BE"
  handle: "#7F8FA8"
  ink: "#131B2A"
  ink-2: "#38445A"
  muted: "#566379"
  faint: "#5E6A7F"
  primary: "#1F3A68"
  on-primary: "#FFFFFF"
  primary-hover: "#172C50"
  blue: "#2563D4"
  blue-ink: "#1B4DAE"
  blue-soft: "#EAF1FD"
  blue-line: "#B8CDF3"
  warn: "#8A5300"
  warn-soft: "#FFF3DC"
  warn-mark: "#C47600"
  crit: "#B3261E"
  crit-soft: "#FDE9E7"
  ok: "#1F6B45"
  topband: "#16233A"
  on-topband: "#E8EDF6"
  topband-muted: "#B4C0D4"
  topband-dark: "#060B14"
  domain-power: "#D9A21B"
  domain-water: "#13A3B5"
  domain-docs: "#8B6FD0"
  canvas-dark: "#0A101D"
  surface-dark: "#111A2B"
  surface-2-dark: "#162033"
  surface-3-dark: "#1D2940"
  hair-dark: "#25314A"
  divider-dark: "#4A5B7A"
  handle-dark: "#6B7D9D"
  selected-dark: "#1A3157"
  chart-1: "#2563D4"
  chart-2: "#0F8FA0"
  chart-3: "#C98A00"
  chart-band-wide: "#9BB8EF"
  chart-band-mid: "#5F8FE3"
  chart-band-core: "#1F56BD"
  chart-1-dark: "#5B8DEF"
  chart-2-dark: "#1FA29A"
  chart-3-dark: "#C98A1C"
  chart-band-wide-dark: "#3A5A94"
  chart-band-mid-dark: "#5C86CC"
  chart-band-core-dark: "#9DC0FF"
  ink-dark: "#E8EDF6"
  muted-dark: "#94A3BB"
  primary-dark: "#9DB9F0"
  on-primary-dark: "#0B1630"
  blue-dark: "#7CAAFF"
  blue-ink-dark: "#A9C6FF"
  warn-dark: "#F2C26B"
  crit-dark: "#FF8D98"
typography:
  display: { fontFamily: IBM Plex Sans, fontSize: 34px, fontWeight: 700, lineHeight: 1.18, letterSpacing: -0.02em }
  headline: { fontFamily: IBM Plex Sans, fontSize: 26px, fontWeight: 700, lineHeight: 1.23, letterSpacing: -0.01em }
  figure: { fontFamily: IBM Plex Sans, fontSize: 28px, fontWeight: 600, lineHeight: 1.21 }
  title: { fontFamily: IBM Plex Sans, fontSize: 20px, fontWeight: 600, lineHeight: 1.3 }
  body: { fontFamily: IBM Plex Sans, fontSize: 14px, fontWeight: 400, lineHeight: 1.43 }
  reading: { fontFamily: IBM Plex Sans, fontSize: 16px, fontWeight: 400, lineHeight: 1.62 }
  label: { fontFamily: IBM Plex Sans, fontSize: 13px, fontWeight: 600, lineHeight: 1.35 }
  caption: { fontFamily: IBM Plex Sans, fontSize: 12px, fontWeight: 400, lineHeight: 1.33 }
  mono: { fontFamily: IBM Plex Mono, fontSize: 12px, fontWeight: 400, lineHeight: 1.4 }
rounded:
  none: 0px
  tag: 4px
  control: 8px
  popover: 10px
  toast: 12px
  dialog: 16px
  composer: 22px
  pill: 999px
spacing:
  xxs: 2px
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 24px
  xxl: 32px
  xxxl: 48px
components:
  page: { backgroundColor: "{colors.canvas}", textColor: "{colors.ink}" }
  page-dark: { backgroundColor: "{colors.canvas-dark}", textColor: "{colors.ink-dark}" }
  surface: { backgroundColor: "{colors.surface}", textColor: "{colors.ink}", rounded: "{rounded.none}" }
  surface-dark: { backgroundColor: "{colors.surface-dark}", textColor: "{colors.ink-dark}" }
  group-row: { backgroundColor: "{colors.surface-2}", textColor: "{colors.ink-2}" }
  group-row-dark: { backgroundColor: "{colors.surface-2-dark}", textColor: "{colors.muted-dark}" }
  count-badge: { backgroundColor: "{colors.surface-3}", textColor: "{colors.ink-2}", rounded: "{rounded.pill}" }
  count-badge-dark: { backgroundColor: "{colors.surface-3-dark}", textColor: "{colors.ink-dark}", rounded: "{rounded.pill}" }
  row-selected: { backgroundColor: "{colors.selected}", textColor: "{colors.ink}" }
  caption: { backgroundColor: "{colors.surface}", textColor: "{colors.muted}" }
  caption-dark: { backgroundColor: "{colors.surface-dark}", textColor: "{colors.muted-dark}" }
  placeholder: { backgroundColor: "{colors.surface}", textColor: "{colors.faint}" }
  button-primary: { backgroundColor: "{colors.primary}", textColor: "{colors.on-primary}", rounded: "{rounded.control}", padding: 8px 14px, height: 34px }
  button-primary-hover: { backgroundColor: "{colors.primary-hover}", textColor: "{colors.on-primary}" }
  button-primary-dark: { backgroundColor: "{colors.primary-dark}", textColor: "{colors.on-primary-dark}" }
  button-secondary: { backgroundColor: "{colors.surface}", textColor: "{colors.blue-ink}", rounded: "{rounded.control}" }
  button-secondary-dark: { backgroundColor: "{colors.surface-dark}", textColor: "{colors.blue-ink-dark}" }
  link: { backgroundColor: "{colors.surface}", textColor: "{colors.blue-ink}" }
  chip-on: { backgroundColor: "{colors.blue-soft}", textColor: "{colors.blue-ink}", rounded: "{rounded.pill}" }
  status-warn: { backgroundColor: "{colors.surface}", textColor: "{colors.warn}" }
  status-warn-dark: { backgroundColor: "{colors.surface-dark}", textColor: "{colors.warn-dark}" }
  status-crit: { backgroundColor: "{colors.surface}", textColor: "{colors.crit}" }
  status-crit-dark: { backgroundColor: "{colors.surface-dark}", textColor: "{colors.crit-dark}" }
  status-ok: { backgroundColor: "{colors.surface}", textColor: "{colors.ok}" }
  badge-warn: { backgroundColor: "{colors.warn-soft}", textColor: "{colors.warn}", rounded: "{rounded.pill}" }
  badge-crit: { backgroundColor: "{colors.crit-soft}", textColor: "{colors.crit}", rounded: "{rounded.pill}" }
  focus: { backgroundColor: "{colors.surface}", textColor: "{colors.blue}" }
  hairline: { backgroundColor: "{colors.hair}", textColor: "{colors.ink}" }
  outline: { backgroundColor: "{colors.hair-strong}", textColor: "{colors.ink}" }
  hairline-dark: { backgroundColor: "{colors.hair-dark}", textColor: "{colors.ink-dark}" }
  topband: { backgroundColor: "{colors.topband}", textColor: "{colors.on-topband}" }
  topband-meta: { backgroundColor: "{colors.topband}", textColor: "{colors.topband-muted}" }
  topband-dark: { backgroundColor: "{colors.topband-dark}", textColor: "{colors.ink-dark}" }
  graphic-warn: { backgroundColor: "{colors.warn-mark}", textColor: "{colors.ink}" }
---

# Design System: SGW Resilience Decision Platform

Visual direction: Console Flat. This file is the source of truth for colours, type, layout and components of the web app.

## Overview
- Purpose and primary action: the operator sees which decision matters now, why (deadline basis, evidence) and signs it or sends it back. Primary action: open the most urgent decision and sign it.
- Audience: Incident Commander, Duty Manager, Water Incident Lead, Compliance, Logistics, Executive (read-only); many are not technical; under time pressure and tired. Desktop and large screens, laptops; phone for the Briefing and a Decisions glance.
- What only this product can claim: one decision queue across power and water, each item with a computed deadline, its basis (impact starts minus lead time, with an 8-in-10 scenario range), the sequence between decisions and a timing verdict across forecast scenarios.
- Personality: calm, organised, professional, like a mature cloud console; nothing may overwhelm a first-time, non-technical reader.
- Direction: **Console Flat** — the AWS console visual update applied to SGW: a dark navy top band, a white sidebar with collapsible groups, one white content surface with thin strokes and no container shadows, breadcrumb + bold title + "Info" link, a key-number strip, tabs, full-width tables with expandable rows, list + full-height detail pane. Additions: Ask AI with history on the left and Sources on the right, sparklines next to changing values, explicit links into Decisions everywhere, minimal domain markers. Light by default, dark fully supported. Two accents, navy and blue; no orange.
- Scope: product. Platforms: desktop web primary (1440-1920), tablet 1024, phone 390 for Briefing, Decisions and Ask AI. Site type: operations web app.

## Colors
- **Navy `primary` #1F3A68** = structure: the one primary button per view, selected tab bar, active nav bar, avatar, Ask AI send button. **Blue #2563D4 / blue-ink #1B4DAE** = interaction: links, secondary buttons, selected row tint and bar, filter chips, focus ring, source pills, "View decision" links. Navy never carries status. No orange anywhere.
- Top band #16233A (text #E8EDF6, meta #B4C0D4); dark #060B14. Canvas #E6ECF5 only behind maps and page edges; content on one white surface; s2 #F5F7FA for group rows and hover, s3 #ECEFF4 for tracks, badges and the user bubble; hairlines #DDE3EC, outlines #C3CCDA.
- Status: grey for normal; amber `warn` #8A5300 for Elevated and numbers that need attention; red `crit` #B3261E for Critical, Severe, Overdue and destructive; dashed grey for No data; green `ok` only for rare confirmations. Always icon shape + word, never colour alone, never a filled lozenge. Severity: Critical (red filled diamond) · Severe (red outline diamond) · Elevated (amber outline triangle) · Minor (grey outline circle) · Normal (grey check) · No data (grey dashed circle).
- **Domain markers** (8 px rounded square before the word): Power #D9A21B, Water #13A3B5, Documents #8B6FD0 (dark #F0C04A, #4FD0E0, #B4A0F0) — only in tags, Sources rows and legends; never fills, row tints, nav or next to status. The word always stays.
- Deadline colour: neutral until under 60 minutes, amber below, red only when missed. Timing verdicts are bold ink, not coloured.
- **Dividers:** vertical separators between key numbers use `divider` #9AA8BE (dark #4A5B7A); the resize grip uses `handle` #7F8FA8 (dark #6B7D9D), 3:1 on white. Hairlines stay for horizontal rules.
- **Charts:** one `chart-*` token set in both themes, never opacity on the surface: range bands run `chart-band-wide` → `-mid` → `-core` (light #9BB8EF → #5F8FE3 → #1F56BD; dark #3A5A94 → #5C86CC → #9DC0FF, lighter toward the core so they stand out on navy); the median tick is `chart-median`; bars and tracks use `chart-1` blue #2563D4 (dark #5B8DEF) on `chart-track`; further series `chart-2` teal, `chart-3` amber. Checked with the dataviz validator: ordinal ramp passes in both modes; the three series pass light, and dark passes CVD and contrast with the amber 0.02 above the lightness band.
- **Map basemap tokens** (light / dark): `map-land-us` #F1F3F6 / #172033, `map-land-other` #E2E7EE / #0F1726, `map-state` lines #CBD3DE / #2A3652, `map-region` fill #FFFFFF / #1D2940 with `map-region-line` #1F3A68 / #9DB9F0 for the SGW service area, `map-geo-label` #7A879B / #7F8DA6; they live in `styles/tokens.css` with the other map tokens.
- Map risk ramp #F1EEE6 → #DDA774 is a data scale. Dark tokens: `-dark` suffix; full table in `web/src/styles/tokens.css`.

## Typography
- IBM Plex Sans 400/500/600/700; IBM Plex Mono only for identifiers, rule numbers and times. Self-hosted (OFL).
- Scale: display 34/40 (Briefing status word) · headline 26/32 (page title) · figure 28/34 (key numbers, tabular) · title 20/26 (detail and dialog titles) · report section 18/24 · pane section 15/20 bold with a rule · body 14/20 · reading 16/26 (chat answers) · label 13-14/600 · caption 12/16 · mono 11-12.5.
- Sentence case. Tabular numerals wherever a number changes.

## Layout
- Shell: dark top band 56 px (product, Jump to…, scope "Helene, SGW service area", scenario clock "11:25 ET (15:25Z)", the one replay/synthetic-data chip, theme, person and role); solid white sidebar 232 px with collapsible groups Respond, Inform, Your account. Below 820 px the sidebar becomes a bottom tab bar (Decisions, Water, Ask AI, Briefing, Health).
- One white surface; **no rounded containers, no card piles, no box inside a box, no container shadows**. Sections are separated by a heading, space and a 1 px rule. Panes are full height and do not scroll unless their content is a genuinely long list; headers, tab rows and filters stay fixed and only the list or tab body scrolls. A tab row that does not fit moves its last tabs into a "More" menu instead of scrolling. A scrollbar appears only when the user narrows a pane.
- **Resizable panes:** every page that puts two panes side by side (shell navigation | content, Decisions list | detail, Map | panel, Readiness, Admin people, Ask history | chat | sources) uses the one `SplitPane`: a 1 px `divider` line with a short `handle` grip at its middle, a 12 px hit area, blue 3 px highlight on hover, drag and keyboard focus, `col-resize` cursor, arrow keys, double-click reset, minimum and maximum size per pane, sizes remembered per page. Below 1100 px (Readiness 1280) the panes stack.
- Page header: breadcrumb, bold title with count, plain "Info" link, at most one secondary action; then the **key-number strip** (four tiles between hairlines, optional sparkline); then **tabs**.
- Templates: **Decisions** list + detail (480 px pane with a 150 px map strip, facts 2 x 2, tabs Deadline | Signatures | Sequence | Evidence | History); **Water** overview (tabs Zones | PS-17 plan | Boil-water advisories | Sensor checks; expandable rows; pressure bar + value + sparkline); **Ask AI** chat; **Briefing** report (820 column + sticky "On this page"); **System health** overview (tabs Data | Models | AI runs | Safety); **Readiness** list + detail; **dialog and side sheet**. Crews and Forecast reuse the overview template, After-action the report, Admin users the list + detail. The Map page has its own layout (map with a side panel).
- Spacing 4 px base; page padding 32 (16 on phone); pane 24; table rows 56, header 36.

## Elevation & Depth
- **Sign-in page only:** a slow, soft glow behind the sign-in card — radial blurs in navy #1F3A68, blue #2563D4, water teal #13A3B5 and documents violet #8B6FD0 at about 18-25% opacity, about 96 px blur, drifting over 20-40 s; the card and every text sit on opaque surfaces; reduced motion stops the drift; reduced transparency replaces the glow with a flat tint. Nowhere else in the app.
- No shadow on content. Shadows only on the "Open map" chip over the map (e-float, with 16 px blur), popovers/menus/toasts (e-pop), the Ask AI composer (e-composer), dialogs and sheets (e-dialog). Values in `web/src/styles/tokens.css`.
- **Scrim** behind dialogs and sheets: rgba(19,27,42,.30) + blur(8px) (dark rgba(3,6,12,.58)); dialogs and sheets are opaque. No frosted bars. Reduce transparency (system or the in-app setting `html[data-transparency=reduced]`) turns the scrim plain.

## Shapes
Tables and panes 0; tags and tier chips 4; buttons, inputs, selects 8; popovers and tooltips 6-10; dialogs 16; sheet 16 on the left corners; composer 22; chips, count badges, send button, top-bar search fully round. Lucide line icons 1.5 px.

## Components
- **Buttons, one look per job:** Primary navy (one per view: Sign as Command, Record result, Confirm); Secondary white with 1.5 px blue outline (Send back, Assign, Edit, New chat, Compare N and N+1); Tertiary blue-ink text (View decision, Open the full PS-17 plan); Destructive red text (Approve alone…; red fill only for the final confirm); icon buttons 34 px with a tooltip, pressed = blue-soft.
- **StatusText**, **Tag** (outline, optional domain marker), **Tier** (T3 solid ink chip, T1/T2 grey chip), **FilterChip** (blue-soft pill, × with tooltip), **CountBadge** (grey pill; amber only when it counts a problem), **SegmentedControl** (Table | Map, Now | Forecast, All | Power | Water), **Select** ("Utility: All"), **Tabs** (3 px blue bar, #2563D4; dark #5B8DEF), **KeyNumberStrip**, **Table** (sticky header, group rows, selected or expanded row tint (`selected` #E0EBFC, dark #1A3157) + 3 px blue bar, expandable rows (their detail row on the same tint at 40 %), folded groups when nothing needs attention), **InfoTip / "Info" link** (≤25 words, "More in Help"), **Dialog** 540 px, **Side sheet** 480 px, **Toast**, **Form field**, **Sparkline**.
- **Sparkline:** 1.5 px stroke in muted, end dot, no axes or fill; warn-mark only when the value is abnormal; 56 x 22 in cells and tiles, 72 x 24 in detail rows; bounded quantities on a fixed range; real history only — no line when there is no history.
- **Deadline:** "in 12 h 4 m" over "23:29 ET (03:29Z)"; the Deadline tab draws decide by, lead time, impact starts and the 8-in-10 band on one time axis; "Earlier by 1 h 16 m, was 00:45 ET (04:45Z)" after an advisory moves it.
- **Cross-links into Decisions:** every row that names a decision shows its id as a link (tooltip "Open this decision"); rows about one decision end with "View decision ›" — in Water, the PS-17 plan, the Sequence tab, Ask AI Sources, Briefing, Readiness and the Map panel.
- **Ask AI:** header left to right: history toggle (opens the 264 px history panel on the left; closed by default), title, "Info", the **only "New chat"**; on the right the **Sources toggle** (list icon with count badge) — the 340 px Sources panel opens by default as soon as an answer has sources. Tooltips on every icon button. Thread: only the user's message is a bubble; a folded steps line ("Checked 3 decision cases and 1 procedure · 41 s", accessible name "Show steps"); answer 16/26 with inline source pills; icon actions; follow-ups as arrow rows; docked composer with scope chip and navy send circle; "AI can make mistakes. Check the sources before you act. Read-only." Empty state "Where should we start?" with four starters and no Sources panel. Sources rows: Documents first, then Platform data, each with id link, title, location, quote, and "Open document" or "View decision".
- **States:** empty (icon, one bold line, one grey line), loading (row-shaped skeleton), error ("{Thing} did not load." + "Try again").
- Provenance: the replay chip in the top band "Replay of Hurricane Helene, 23 Sep – 6 Oct 2024, synthetic SGW data" (ET date, like the rest of the app) and the export footer; no per-caption synthetic tags.

## Copy
Plain US English, sentence case, verb-first buttons ≤3 words, InfoTips ≤25 words. No middle-dot " · " separators in UI text: write natural text with commas, "of", "in", "at" or a colon ("Heat wave, July 2024", "11:05 ET (15:05Z)", "Outage surge in Burke, GA"); times are "ET (UTC)". Term choices: Ask AI · Deadline | Signatures | Sequence | Evidence | History · Act now · Before next advisory · Can wait · Emergency approval / Approve alone… · Timing · Briefing · System health · Minor · No data · times in ET first, UTC second where useful.

## Motion
Easing cubic-bezier(.2,.8,.2,1): hover 120 ms, tooltip 120 ms, chevron 160 ms, scrim 160 ms, dialog 200 ms (opacity, 6 px rise, .985 scale), sheet 220 ms (24 px slide). The 400 ms queue reorder when an advisory moves PS-17 up, with the changed deadline outlined. `prefers-reduced-motion`: all instant. No countdown animation.

## Accessibility
WCAG 2.2 AA: every text pair measured ≥4.5:1 on every page in light and dark. 2 px blue focus ring with 2 px offset. Full keyboard: j/k in lists, Enter opens, Esc closes, Cmd+K; page hotkeys off while a dialog or menu is open; tooltips also on focus; aria-label equals the tooltip. Status never colour-only; domain markers are redundant with the word.

## Platforms
Web. Verification viewports: 1440x900 and 1920x1080 for every page (light and dark), 1024x768 for Decisions, Map and Briefing, 390x844 for Briefing, Decisions and Ask AI.

## Do's and Don'ts
- Do: one surface; headings and rules instead of boxes; key numbers + tabs; full-width tables with expandable rows; links into Decisions wherever a decision is named; one primary per view; real identifiers and times; sparklines only on real history.
- Don't: rounded cards per section, cards inside panes, container shadows, KPI cards with icons, identical-looking buttons/badges/selects, glass on content or bars, gradients, glow, emoji, "AI-powered" copy, stock shadcn dashboards, coloured row tints by domain, more than two accents, orange.

## References
- AWS Management Console visual update (Nov 2024): flatter containers, thin strokes, less padding, bolder headings, blue secondary actions, one primary.
- ChatGPT / Claude-style chat layout, Linear-style sparklines, AWS-style cross-links.
