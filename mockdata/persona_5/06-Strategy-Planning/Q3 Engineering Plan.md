# Q3 Engineering Plan

**Author:** Maya
**Status:** Draft, reviewed with TLs
**Date:** 2026-05-25
**Quarter:** July-September 2026

## Frame

Q3 is the investing-feature quarter. Everything else is in service of either shipping investing on time or staying out of its way.

## Top priorities (in order)

### 1. Ship investing feature

- Cut and shipped by end of Q3
- DriveWealth integration live
- Position reconciliation reliable
- Mobile UX clean
- Disclosures legally reviewed

Owner: Marcus + Nadia, with Devon on reconciliation.

### 2. ACH pipeline cut-over

- Phase 2 of ADR-024 — cut over from Sidekiq to new pipeline
- Target: end of June (technically Q2 but spills into Q3)
- 30-day stability hold before deleting old code

Owner: Marcus.

### 3. KYC vendor migration

- Persona → Alloy migration completes by August
- New signups on Alloy in June, existing user migration through July

Owner: Marcus.

### 4. iOS architecture refactor

- 3 screens migrated to SwiftUI + TCA (settings, account, deposits)
- Navigation layer migration starts

Owner: Nadia.

### 5. BSA/AML audit

- June 8 audit happens
- Remediation of any findings before end of Q3
- SOC2 Type 2 evidence collection

Owner: Maya (with Aleks).

## Secondary priorities (only if capacity)

- Card issuing prep (Lithic integration design)
- Behavioral push notification campaigns (Kavi-driven)
- Snowflake-to-Postgres feature migration (Devon)

## What we're explicitly NOT doing in Q3

- Card issuing implementation (Q4)
- VPE hiring (post-Series B)
- Mobile design system formalization (Lin pushed; deferred)
- Snowflake-out-of-analytics work (stays where it is)
- Backend Go service for non-money-movement code (stays in monolith)

## Capacity model

14 engineers + Maya. Roughly:
- Marcus's pod (4 backend engineers): ACH cut-over + investing backend (50/50)
- Nadia's pod (3 mobile engineers): investing mobile + iOS refactor (60/40)
- Devon's pod (2 data engineers): position reconciliation + Snowflake migration (60/40)
- Cross-pod: 2 engineers on hiring loops, code review, ops
- Maya: architecture review, board prep, compliance, hiring conversations, 1:1s, sleep

Doesn't quite add up to 100%. Always doesn't. That's the gap that compounds if we don't watch it.

## Risks

- **Investing slips.** Re-prioritize. Cut sub-features (no auto-invest at launch? No fractional shares at launch?) before slipping the whole thing.
- **ACH cut-over reveals new issues.** Plan: stay on shadow longer, don't cut over until diffs are clean.
- **Hiring market doesn't loosen.** We close 0 senior backend hires. Adjust by adding mid-level slots or keeping headcount flat.
- **An incident eats a week.** Plan: 80% capacity assumption. Don't plan to 100%.

## What I want at end of Q3

- Investing feature live, 5%+ MAU adoption in week 1
- ACH pipeline boring (zero Sunday incidents)
- BSA/AML audit clean (no significant findings)
- iOS refactor 50% done
- Team energized, not exhausted
- Series B story stronger than it is today

## What I'm explicit about

This is an ambitious quarter. I am not going to add anything else once it's locked. Anyone (including Aleks) who wants to add to this plan needs to remove something equivalent first.

## Review cadence

Mid-quarter check-in (August 15). Adjust if needed.
