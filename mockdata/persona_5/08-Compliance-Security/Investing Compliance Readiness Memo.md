# Investing Compliance Readiness Memo

**Author:** Maya, with outside counsel review
**Status:** Final, for board file
**Date:** 2026-05-20

## What this memo is

A snapshot of where we are on compliance readiness for the investing feature, written for the board, with sufficient detail to satisfy diligence questions during Series B.

## The regulatory frame

Stencil is not a broker-dealer. DriveWealth is. Our customers open brokerage accounts with DriveWealth through our app. We are an introducing relationship.

That said, we have meaningful compliance obligations:
- Suitability disclosures
- Marketing rules (especially around projections, promises of return)
- Data handling for FINRA-regulated information
- Customer communications during account opening
- Tax document delivery
- BSA/AML extending into the brokerage relationship

We've engaged outside FINRA-experienced counsel since Q1 to make sure we get this right.

## What we have in place

### Account opening flow

- KYC re-verification at brokerage account opening (above and beyond our existing KYC)
- Suitability questionnaire (basic, expandable)
- Risk acknowledgment screens
- Disclosure delivery (we provide, DriveWealth records)
- Customer agreement signed (DriveWealth's, we facilitate)

### Marketing copy

All marketing copy for investing has been reviewed by outside counsel. Specific things we don't do:
- No projected returns
- No "get rich" language
- No comparisons to specific outcomes
- Clear disclosure of "investments lose value" on all customer-facing screens

### Data handling

- FINRA-regulated data flows are isolated from analytics
- Position data has separate retention requirements; we honor them
- Audit logs cover all customer-initiated investing actions

### Customer communications

- Tax document delivery (1099-B) automated through DriveWealth's system, surfaced in our app
- Account statements monthly
- Disclosures on material changes

## What we don't have in place yet

### Suitability monitoring

Once a user is invested, we need to monitor for unsuitable activity (e.g., elderly user moving into volatile assets). DriveWealth handles this baseline. We add a UX layer.

Status: design in flight. Will be in place by launch.

### Tax loss harvesting messaging

We don't currently message about tax loss harvesting. As users start to see realized gains/losses, we'll need to add appropriate disclosures about tax consequences. Not blocking for launch.

### Pattern day trader rules

PDT rules apply to users who make 4+ day trades in 5 days with < $25k account value. Our auto-invest product doesn't trigger this naturally, but as we add more features, we'll need to monitor.

Status: research, not implementation. Q4.

## Compliance staffing

- Compliance officer: Aleks's title currently includes this; we'll consider a dedicated compliance hire post-Series B
- BSA/AML officer: outside counsel handles formally, we manage operationally
- Designated FINRA contact: DriveWealth's responsibility (they carry the license)

## Key risks

### Regulatory surprise

FINRA rules evolve. Outside counsel keeps us current. Quarterly review.

### Customer confusion

Users may misunderstand the introducing relationship. Disclosures help; UX clarity helps more. Lin's work on this is excellent.

### State-level requirements

Some states have additional requirements for investment advisers (we're not one, but the line can blur). Outside counsel confirms we're clean.

### Cybersecurity for brokerage

Securities-account compromise has different reporting requirements than checking-account compromise. We have the playbook.

## What the BSA/AML auditor will see (June)

Investing isn't launched yet. Auditor will ask about readiness. Our story:
- We have a comprehensive compliance plan
- Outside counsel engaged and supportive
- DriveWealth carries the FINRA-regulated obligations
- We have time to address remaining gaps before launch
- We're not cutting corners to ship

I'm confident this story holds.

## What Series B investors will see

The diligence binder includes:
- This memo
- The DriveWealth integration agreement
- The marketing copy review trail
- The KYC procedures for investing
- Outside counsel engagement letter
- A compliance roadmap through Q4

This reads as a serious company. Last year's BaaS shakeout has investors looking for exactly this kind of preparation.

## What I'd improve

- Earlier counsel engagement. We brought outside counsel in at Q1 2026 for a Q3 launch. Should have been Q4 2025. Lesson for next product.
- Faster suitability monitoring design. Should have started in Q1, not Q2.

## What I want from the board

- Acknowledgment that we are doing this right (we are)
- Permission to slow the investing launch if compliance gaps surface (we should)
- Budget for outside counsel ongoing (~$15k/month) — already approved

## Personal note

Compliance is the kind of work that's invisible when it goes well. The first 1099-B that arrives in a customer's inbox on January 31, 2027 — without errors, without confusion — will be the moment I know this was done right.
