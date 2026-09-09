# Diligence Room Setup Plan

**Author:** Maya
**Status:** In progress
**Date:** 2026-05-20

## What this is

The data room we send to Series B investors once a term sheet is in hand (or for warm intros prior). I own the engineering/compliance/security sections. Aleks owns commercial/financial sections. CFO owns financial detail.

Building it now so we're not scrambling when the term sheet hits.

## Engineering section structure

### Architecture overview

- 1-page system architecture diagram
- 1-page data flow diagram (focus on money movement)
- 5-page architecture narrative (the long version of the deck slide)

### Technology choices

- Stack overview: languages, key frameworks, infrastructure providers
- Vendor list with renewal dates and SLA terms
- Justification for build vs. buy decisions (KYC, card issuing, brokerage)

### Scalability

- Current scale metrics (peak/sustained QPS, transactions/day, GB stored)
- Tested scale metrics (load test results)
- Identified bottlenecks and mitigation plans
- 12-month capacity plan

### Team

- Org chart (current)
- Org chart (Q1 2027 plan)
- Key technical leaders with credentials
- Engineering hiring plan
- Tenure distribution
- Attrition history (it's near-zero, good story)

## Security section

- Information security policy
- Access control documentation
- Data encryption (at-rest, in-transit, key management)
- Pen test results + remediation
- Bug bounty / responsible disclosure program
- Security incident history (one minor in Q1, no exposure)

## Compliance section

- BSA/AML program documentation
- KYC procedures
- Sponsor bank relationship (Pillar Bank) — agreement summary
- Regulator interactions (CFPB monitoring, no actions)
- SOC2 Type 1 report
- SOC2 Type 2 status
- DPA / privacy compliance (CCPA, GDPR — even though we're US-only, ready for expansion)

## Incident history

- April 6 ACH incident — full postmortem
- Other notable incidents — summary list (5 in past 12 months, all customer-comms-clean)
- Pattern analysis — what we've learned

## Vendor risk

- Top 10 vendors by criticality
- Risk assessment per vendor
- Backup / contingency plans where applicable

## What I want this to read as

A grown-up engineering organization at a young company. Honest about what we have and what we don't. Specific where it matters. Not over-marketed.

The worst thing a diligence room can do is make the company look bigger than it is. Sophisticated investors see through it. Honest specificity wins.

## What I'm explicitly not including

- Source code access. (Standard. We provide read-only via a secure pattern if requested specifically.)
- Customer-level data. (Aggregated only.)
- Employee personal information. (Org chart is public-facing only.)
- Vendor contract texts. (Summaries with key terms; full contracts only if specifically asked.)

## Timeline

- May 20 → June 30: build out all sections
- July: internal review with Aleks, Bessemer
- July: external legal review for risk language
- August: ready to share

## Risks

- **Sensitive content leakage.** Mitigation: secure data room (DocSend or similar) with access logs. NDA before access.
- **Information dating quickly.** Mitigation: monthly refresh on metrics sections.
- **Underselling.** A diligence room can be too sparse. Erring on the side of substantive content where defensible.

## Personal note

Watching the diligence room come together feels like watching the company grow up. Three years ago we were 4 people in a coworking space. Now I'm writing an information security policy. It's a good kind of weird.
