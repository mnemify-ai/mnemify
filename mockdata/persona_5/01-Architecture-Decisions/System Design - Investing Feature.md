# System Design — Investing Feature (Q3 launch)

**Author:** Maya
**Status:** Draft for team review
**Date:** 2026-05-08

## What we're building

Stencil's investing feature lets users put their savings into a small set of curated ETFs. MVP scope:
- 6 ETF options (broad market, bonds, ESG, sector)
- Fractional shares, $1 minimum
- Auto-invest cadence (matches savings cadence)
- Tax lot tracking
- Basic portfolio view

We are NOT building a brokerage. We are partnering with one (decision in progress, leaning toward DriveWealth).

## Architecture overview

```
Stencil Mobile App  ←→  Stencil Backend  ←→  DriveWealth API
                              ↓
                         Postgres + Snowflake
                              ↓
                         Pillar Bank (existing ACH)
```

User-facing flow:
1. User opens investing tab in app
2. Picks ETF (or auto-invest)
3. Money flows: Pillar Bank checking → DriveWealth brokerage → ETF position
4. Stencil mirrors position state in Postgres
5. Daily reconciliation against DriveWealth's positions API

## Critical components

### Brokerage relationship layer (new)

This is a thin Go service that owns the entire DriveWealth integration. All brokerage operations go through it. Reasons:
- DriveWealth's API is going to change. We isolate the blast radius.
- Compliance-sensitive code shouldn't be sprinkled through the monolith.
- Marcus owns it. Same team as ACH pipeline. Same Go stack.

### Position state machine

A position has states: `funded → ordered → filled → settled` (for buys) and `requested → liquidated → returned` (for sells). State transitions are idempotent. Reconciled nightly against DriveWealth.

### Money movement coordinator

The hard part. Money has to flow checking → brokerage → ETF, but the system has to handle:
- ACH from Pillar Bank can take 3 days
- DriveWealth needs settled cash before placing orders
- ETF market hours
- Failed funding (NSF)
- Partial fills

I'm sketching this as a state machine that's been the focus of the last two weeks of design. Marcus has a draft. We review Friday.

### Reconciliation pipeline

Nightly. Compare Stencil's view of every position to DriveWealth's. Flag discrepancies. We're going to find some in week 1 and we need to know about them before the customer does.

## What's deliberately out of scope for MVP

- Margin trading. No.
- Options. No.
- Crypto. No.
- Tax loss harvesting. Q4 at earliest.
- Real-time price updates in-app (we use end-of-day prices). Add later.
- Robo-rebalancing. Maybe Q1 2027.

I want this discipline. Brokerage scope creep is how you get a 12-month MVP.

## Compliance considerations

- DriveWealth carries the FINRA license. We are not a broker-dealer. We are an introducing relationship.
- Users open brokerage accounts via DriveWealth (their KYC + account opening).
- Disclosures must be presented at multiple points. Renee owns the legal copy. I own that they actually appear.
- Tax reporting (1099-B) flows from DriveWealth. We help users find them.

## Risks

- **DriveWealth onboarding time.** They've quoted 6 weeks for integration. Add 4 weeks buffer. Hard deadline becomes our Q3 ship date.
- **Compliance review.** Our BSA/AML auditor in June needs to see investing-side flows. Schedule the review early.
- **Sponsor bank coordination.** Pillar Bank needs to understand the money-movement flow. Internal call scheduled May 22.
- **User confusion.** Investing UX in a savings app is non-trivial. Lin is on it. Weekly design reviews.

## Team allocation

- Marcus: backend, brokerage integration layer
- Nadia: mobile investing UX
- Devon: position reconciliation, performance tracking
- Lin: design across both platforms
- Renee: product spec, legal copy, compliance UX
- Me: stitching it together, board-facing narrative

## What I want from this

Investing live by end of Q3. 10% of MAU using it within 90 days of launch. Zero major compliance findings. Series B narrative becomes "savings + investing" instead of "savings."
