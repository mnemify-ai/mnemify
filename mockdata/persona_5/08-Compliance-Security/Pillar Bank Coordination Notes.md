# Pillar Bank Coordination Notes

**Author:** Maya
**Status:** Living doc for sponsor bank relationship
**Date:** 2026-05-26

## What Pillar is

Our sponsor bank for the BaaS (banking-as-a-service) layer of Stencil. They hold customer funds, originate ACH, handle interbank settlement, and are the regulated entity behind our consumer banking-adjacent product.

Without Pillar, Stencil cannot operate. This relationship is existential.

## Their internal structure (as I understand it)

- **Account team:** our day-to-day. Lead is Karim. Quarterly business reviews.
- **Operations team:** day-to-day ACH and settlement ops. Lead is Theresa.
- **Compliance team:** they review our compliance posture annually + ad-hoc. Lead is Priya.
- **Engineering team:** if we have integration issues. Lead is Brent.
- **Executive sponsor:** their COO (whose name I'll learn before our next executive review)

## Communication cadence

- **Weekly operational sync** between Marcus's team and Theresa's team. Quick, async.
- **Monthly business review** between Karim and me (with Aleks occasionally).
- **Quarterly business review** with broader teams from both sides.
- **Annual compliance review** between Priya's team and our compliance counsel.
- **Ad-hoc** as issues arise.

## What's currently in flight

### ACH pipeline change notification (ADR-024)

Marcus's team notified Theresa's team on April 17 about the pipeline rebuild. Pillar Bank's perspective: file format isn't changing (good), submission timing isn't changing (good), they want to be informed of the cut-over date (will do).

Status: Pillar is comfortable. Cut-over coordination meeting scheduled June 4.

### Investing feature

Aleks initiated the conversation with Pillar in March. The investing-funding flow uses Pillar's checking account as source. Some changes to our money-movement profile (more frequent ACH out, more individual transactions per user).

Status: Pillar is reviewing the operational impact. Final sign-off expected end of May.

### KYC vendor migration (Persona → Alloy)

Notified Priya's team April 22. Pillar Bank approves our choice of KYC vendor.

Status: Alloy was a known-good vendor to Pillar; no concerns raised.

### Card issuing (Lithic, Q4 launch)

Notified Karim in April. Card issuing relationship is a meaningful expansion of our partnership with Pillar (cards are issued on a Pillar BIN).

Status: working through commercial terms. Aleks owns. Pillar's pricing for card BIN sponsorship is the main negotiation point.

## Outstanding from last quarterly review

- **Q2 settlement reconciliation review.** Operational. Theresa's team reviewing.
- **Compliance refresh for investing.** Priya's team reviewing the program changes.
- **Annual relationship review.** Scheduled for July.

## What I worry about

### Concentration risk

We are 100% dependent on Pillar. They are one of perhaps 8-12 sponsor banks for fintechs. Any of them could lose interest, get acquired, get regulatory pressure, or change their risk appetite.

Mitigation: Aleks and I maintain executive-level rapport. We track Pillar's financial health (public filings). We have a generic understanding of which backup sponsors we could approach (no specific contingency plan beyond that).

### Pillar's evolving risk appetite

In 2024-2025, several sponsor banks got out of the BaaS business after regulatory pressure. Pillar's leadership has been steady, but the broader environment is unsettled.

Mitigation: stay above their compliance bar. Be a model fintech partner.

### Regulatory scrutiny on the BaaS model itself

OCC, FDIC, CFPB have all expressed concern about BaaS models. Could lead to broader changes that affect us.

Mitigation: outside counsel monitors. We adapt.

## What I'm doing right

- Direct relationship with Karim. He gets pinged when I need something.
- Operations cadence between Marcus's team and Theresa's is healthy.
- Compliance reviews go cleanly because we put work in upfront.
- Aleks owns the executive relationship; doesn't push it to me unnecessarily.

## What I'm doing wrong

- I don't know Pillar's COO well. Should fix.
- I haven't been to Pillar's offices since pre-COVID. Should visit Q3.
- We haven't run a contingency tabletop ("what if Pillar exits?") in a year. Should.

## Personal note

This is the relationship that keeps me up at night more than any other. Marcus has shipped infrastructure I trust. Customers love our product. Investors are interested. But if Pillar pulls support, none of it matters. The mitigation isn't a backup plan — there's no real one. The mitigation is being the partner Pillar wants to keep.
