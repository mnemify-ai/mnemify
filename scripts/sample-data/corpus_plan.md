# Corpus plan

The document list every corpus author works from. Facts come from `story_bible.yaml`.
"(P5: <path>)" means: adapt the existing file at `mockdata/persona_5/<path>`. Add
frontmatter, align names and facts with the bible (Bessemer → Granite Peak Capital,
surnames per bible), and lightly edit. Keep the body's substance; it's good.
Everything else is new.

Docs may reference docs from OTHER sources by exact title (plain text), e.g.
"see *ACH Cut-over Plan* in Confluence". Only Obsidian uses `[[wikilinks]]`, and
only to notes inside the vault.

## File layout and naming
- Confluence: `corpus/confluence/<SPACE>/<Title>.md`
- Notion: root page `corpus/notion/<Root>/_index.md` (title = root name, no `parent`); children `corpus/notion/<Root>/<Title>.md` with `parent: <Root>`
- Obsidian: `corpus/obsidian/Maya/<Folder>/<Title>.md`. File stem == title (wikilinks resolve by stem). Daily notes: `Daily/2026-09-22.md`, title `2026-09-22`.
- Local notes: `corpus/notes/<folder>/<Title>.md`
- Late batch (dated 2026-10-10, harvested AFTER the compile): same layout under `corpus/late/<source>/...`
- Filenames: the title with `/ : ? * " < > |` removed. Keep spaces.

## Confluence (~60) — owner: confluence agent
**ENG**
- (P5) ADR-024 - Move ACH Processing Off Sidekiq · ADR-026 - Vendor Choice for KYC Refresh · ADR-028 - iOS App Rewrite vs. Incremental · ADR-030 - Snowflake to Postgres for ML Features · Build vs Buy - Card Issuing · Mobile - Push Notification Architecture Rewrite · Postgres Sharding Strategy · System Design - Investing Feature
- (P5) Code Review Standards · Engineering Culture - Operating Principles · Engineering Org Design - Post Series B · Meeting Cadence for Engineering · On-Call Rotation Design · Performance Review Framework · Tech Lead Expectations
- (P5) Incident - Login Service Degradation 2026-03-22 · Incident - Snowflake Cost Spike Feb 2026 · Near Miss - Plaid Token Refresh Bug · Postmortem - April 6 ACH Pipeline Failure
- NEW: ADR-031 - Idempotency Keys for All Money-Moving Jobs (proposed 2026-10-05) · ADR-032 - Move Round-up Sweep onto the Outbox Pipeline (draft 2026-10-07) · Postmortem - Sep 26 Duplicate Round-up Debits (2026-10-01, author Marcus) · Incident Review Process · Android - Investing Screens Parity Plan · Architecture Overview 2026 (for data room, Sep) · Load Testing Guide · Engineering Onboarding Guide · Feature Flag Policy

**PLAT**
- NEW: ACH Pipeline - Design Doc (May) · ACH Cut-over Plan (Jun, updated Aug) · ACH Cut-over Retro (2026-08-25) · Sunday Load Test Results - June 27 · Outbox Vacuum Contention Analysis (Jul) · Runbook - ACH Submission Failures · Runbook - NACHA Cutoff Alert · Runbook - Customer Comms for Money Movement Delays (2026-06-02) · Sidekiq ACH Decommission Plan (2026-09-18) · Round-up Sweep Job - Overview · DriveWealth Integration Overview · Position Reconciliation Design · Reconciliation Discrepancy - Fractional Shares Investigation (2026-09-18) · Pillar Bank Integration Notes

**SEC**
- (P5) BSA-AML Audit Prep - June 2026 · Data Retention Policy · Investing Compliance Readiness Memo · Security Review - Quarterly 2026-Q1 · Vendor Risk Register (from `06-Strategy-Planning/`)
- NEW: SOC 2 Program Overview · SOC 2 Type I Report Summary (2026-06-30) · SOC 2 Readiness Review - September (2026-09-10) · Access Review Procedure · Q3 Access Review Tracker · Vendor Risk Assessment - DriveWealth · Vendor Risk Assessment - Lithic · MDM Rollout Plan · Security Review - Quarterly 2026-Q3 · Incident Response Policy · Investing Disclosures Review Checklist (signed 2026-10-07, Hana) · Information Security Policy

**Late (2026-10-10):** PLAT/Reconciliation Fix - Rollout Plan (Devon) · SEC/Q3 Access Review - Completed (Sam)

## Notion (~58) — owner: notion agent
**Leadership** (`_index.md` + children)
- (P5) Board Update May 2026 · Diligence Room Setup Plan · Investor Call Prep - Granite Peak Quarterly (was "Bessemer") · Series B Pitch - Engineering Section Draft · Build vs Buy Framework · Q3 Engineering Plan · Stencil 3-Year Technical Vision · Technical Strategy 2026-2027 · Pillar Bank Coordination Notes
- NEW: Board Update August 2026 · Board Meeting Oct 21 - Prep · Series B - Process Tracker · Northfield Term Sheet - Summary and Open Points (2026-09-23) · Technical Diligence Prep - Elena Sorensen Call (2026-10-08) · Q4 Engineering Plan (draft 2026-10-05) · Budget 2027 - Engineering Headcount · Pillar Bank Remediation Plan - Sep 26 Incident (draft, due 2026-10-15) · Exec Staff Offsite - September (2026-09-12)

**Product**
- (P5) Pricing Strategy for Investing Feature
- NEW: Investing PRD v3 · Investing Launch Checklist · Investing Beta - Week 1 Metrics · Investing Beta - Week 3 Readout · Go-No-Go 1 - Investing GA (2026-09-29) · Go-No-Go 2 - Agenda (2026-10-09, for 10-16) · Card Issuing - Program Design Review (2026-09-30) · Card Issuing - Timeline Change (2026-10-01) · Round-up Multiplier Results · Growth Experiments - Freeze During Beta · Customer Feedback - Investing Beta

**Hiring**
- (P5) Senior Backend Engineer JD · Interview Scorecard - Backend Engineer · Candidate Notes - Sarah K Final Round · Hiring Funnel Health - May 2026 · VP Engineering Search Brief
- NEW: Hiring Funnel Health - September 2026 · Hiring Plan - Post Series B · VP Eng Finalist - Grace Liu · VP Eng Finalist - Tomas Reyes · VP Eng Decision Matrix · Senior iOS Engineer JD · Offer Approval - Senior iOS (Ama) · Onboarding Plan - Theo Brandt

**Meeting Notes**
- NEW: Eng Staff 2026-08-24 · Eng Staff 2026-09-08 · Eng Staff 2026-09-21 · Eng Staff 2026-09-28 · Eng Staff 2026-10-05 · ACH Cut-over Go Decision 2026-08-14 · Pillar MBR - August · Pillar MBR - September · Pillar QBR - Q3 (2026-10-02) · Pillar Ops Sync 2026-10-02 · Investing Launch Standup 2026-10-07

**Late (2026-10-10):** Hiring/Grace Liu - Reference Check Summary · Meeting Notes/Investing Launch Standup 2026-10-10

## Obsidian vault "Maya" (~53) — owner: obsidian agent
- **1on1s/** (P5: `04-Team-1on1s/*`, six files) + NEW: 1on1 Nadia - 2026-09-15 · 1on1 Nadia - 2026-10-06 · 1on1 Marcus - 2026-08-26 · 1on1 Marcus - 2026-10-01 · 1on1 Devon - 2026-09-17 · 1on1 Devon - 2026-10-07 · 1on1 Kavi - 2026-09-23 · 1on1 Renee - 2026-09-30 · 1on1 Sarah - 2026-08-05 · 1on1 Sam - 2026-09-11 · 1on1 Lin - 2026-09-09
- **Daily/**: 2026-06-27 · 2026-08-18 · 2026-09-22 · 2026-09-26 · 2026-09-29 · 2026-10-01 · 2026-10-02 · 2026-10-05 · 2026-10-06 · 2026-10-07 · 2026-10-08 · 2026-10-09
- **People/**: Nadia Okafor · Marcus Bell · Devon Park · Aleks Varga · Renee Alvarez · Sam Whitfield · Karim Haddad · Grace Liu · Tomas Reyes
- **Projects/** (maps of content linking people, dailies, 1on1s): ACH Pipeline · Investing Launch · Series B · SOC 2 · VP Eng Search
- **Reflections/** (P5: `09-Random-Notes/*`, three files) + NEW: Stop Being the Router · What I Owe the Board · Therapy Notes 2026-09-29
- **Reading/** (P5: `10-Reading-Learning/*`, two files) + NEW: Book Notes - An Elegant Puzzle · Book Notes - Thinking in Systems
- **Late (2026-10-10):** Daily/2026-10-10

## Local notes "~/Notes" (~22) — owner: notes agent
- **drafts/**: Board Deck - Eng Section Draft Oct · Data Room - Architecture Narrative v2 · SOC 2 Status Letter - Draft · Pillar Remediation Plan - Rough Notes · All-Hands Talk - What the Incident Taught Us · Eng Blog Draft - The Outbox Pattern
- **scratch/**: Maya - Running TODO · Series B Data Room Checklist · VP Eng Reference Questions · Comp Review Notes Post-Close · Q4 Headcount Scratch · Reconciliation Math Scratch · Questions for Elena Sorensen · Investing GA Risks Scratch · Ideas - Q1 2027 · Weekend Reading List
- **board/**: Board Meeting Oct 21 - Talking Points · Board Update August - Raw Numbers · Metrics Snapshot Sep 2026 · Investor Update Email - Draft
- **Late (2026-10-10):** scratch/VP Eng - Leaning Grace
