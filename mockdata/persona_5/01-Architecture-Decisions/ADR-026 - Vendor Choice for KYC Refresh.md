# ADR-026 — Vendor Choice for KYC Refresh

**Author:** Maya
**Status:** Accepted
**Date:** 2026-05-09

## Context

Our current KYC vendor (Persona) onboarded us at the seed stage and they've been fine. As we expand into investing — which requires identity proofing for FINRA-regulated brokerage opening — we need stronger identity assurance, document verification, and ongoing watchlist monitoring. Persona can do all of this but their pricing at Stencil's projected volume (300k new users over the next 12 months) is brutal.

Aleks asked me to make a vendor call by end of week. Here it is.

## Options

**Persona (incumbent).** Strong product. Their pricing curve is "we'll work with you" until you're large enough to negotiate, at which point you discover you should have negotiated harder a year ago. Estimated annual spend at projected volume: $480k.

**Alloy.** More banking-native. Their orchestration layer means we can swap downstream vendors (Mitek, Socure, Onfido) without code changes on our side. Estimated spend: $360k. But: their default UX is uglier than Persona's.

**Build it ourselves on top of raw vendors.** Marcus floated this. I said no in the meeting and I'm saying no here. We're not a KYC company. The number of person-hours to keep up with regulatory changes alone would eat our backend team.

## Decision

Move to Alloy. Phase Persona out by Q3.

## Why Alloy

The orchestration story is what wins this. We don't know what FINRA's identity-proofing requirements will look like in 2027. We don't know what regulators will demand for the investing product. Alloy lets us swap providers without rewriting our integration. That optionality is worth the migration cost.

Cost matters too — $120k/year savings funds half an engineer. But I'd have picked Alloy on optionality alone.

Persona's better UX is real but solvable. Lin's already mocked up the friction-points; we can match Persona's flow with Alloy's primitives in roughly two weeks of design + frontend work.

## Why not stay with Persona

Their pricing model penalizes growth. Our entire fundraising story is growth. The numbers don't work as we scale into the investing product. I asked their account team for a Series B-friendly contract last month. They came back with a 10% reduction. Not enough.

## Migration plan

- May 12 — Sign Alloy contract (Aleks's signature, my push)
- May 13–24 — Backend integration on parallel path
- May 25–June 7 — Migrate new signups to Alloy (Persona keeps existing users alive)
- June 8–July 31 — Migrate existing user re-verification to Alloy
- August 1 — Persona contract terminates

I want Nadia and Marcus paired on this. Mobile flow + backend integration need to land together.

## Risks

- **Migration breaks something.** It will. We've planned for it. Customer support gets ahead of it with internal training.
- **Alloy's downstream vendor changes mid-migration.** Their SLA covers this. Read the contract.
- **Persona makes a last-minute pricing offer.** Won't matter. Decision made on optionality, not just cost.

## What I want from this in 12 months

- KYC re-verification happens monthly for high-risk segments without engineering touching anything
- Adding a new identity-proofing requirement for investing takes 1 week, not 6
- We have a clean handoff story to our BSA/AML auditor about why we picked Alloy

## What I'm explicit about

This is a one-way door I'm choosing. Switching KYC vendors twice in a year would be reckless. Locking in.
