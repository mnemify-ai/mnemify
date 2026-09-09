# Build vs Buy — Card Issuing

**Author:** Maya
**Status:** Recommendation to Aleks
**Date:** 2026-05-03

## The question

Aleks wants Stencil to issue a debit card. The pitch: link the card to the user's investing account, every swipe triggers a micro-investment ("round-up to invest"). Compelling consumer product. Sticky retention.

Question for me: do we build the issuing platform or partner?

## My recommendation

Partner. Use a card-issuing platform (Marqeta or Lithic). Don't even start the "build it" conversation.

## Why

There are exactly two reasons a company at our stage builds something like card issuing:
1. The capability is core to your product differentiation
2. No vendor can do what you need

Neither applies. The card is a delivery vehicle for the investing product. The differentiation is the round-up-to-invest behavior, not the card itself. And every neobank, fintech, and rewards startup uses Marqeta or Lithic. The pattern is well-trodden.

## What "build it" would cost

- PCI compliance work: real, expensive, ongoing
- Network integration (Visa or Mastercard): months of work
- Issuing processor relationship: months more
- Fraud monitoring: hire a team
- Card production logistics: physical operations we don't have
- Card management UX (lock card, dispute, replace): six months of frontend
- Regulatory overhead: separate compliance lift

Estimated cost: 18 months and a 6-person team we don't have.

## What partnering costs

- Marqeta integration: 8-12 weeks
- Card management UX: 4-6 weeks
- Transaction processing fee: ~$0.10 per swipe (negotiable at volume)
- Annual platform fee: $100-200k

Tradeoff: we pay per-swipe forever. Acceptable.

## Marqeta vs. Lithic

**Marqeta.** Industry leader. More mature platform. Bigger customers. Pricing reflects all that.

**Lithic.** Younger, more API-first, more startup-friendly pricing. Smaller customer base but their tech is excellent.

I'd pick **Lithic**. Reasons:
- Better DX (developer experience)
- Pricing scales more gracefully for our growth curve
- Their team will pick up the phone when we have a problem
- Their tooling for fraud monitoring is comparable to Marqeta's for our use case

Marqeta is the "safe" choice. Lithic is the better choice for us specifically.

## What I want from Aleks's side

- Sign the Lithic contract (terms are fair, I reviewed)
- Sponsor bank conversation — Pillar Bank needs to approve the card relationship
- Capital allocation: $400k for the first year (platform + per-swipe at projected volume)

## What I'd need to staff

- Marcus's team: 2 engineers, 10 weeks for backend integration
- Nadia's team: 1 engineer, 6 weeks for card management UX
- Lin: design support, 3 weeks across both
- Renee: product spec, legal/disclosures, customer comms
- Compliance: integration into BSA/AML monitoring

Total roughly 0.5 engineer-quarters. Realistic.

## Risks

- **Card programs are regulated.** Mistakes are expensive. Lithic abstracts much of this but we still own user-facing behavior.
- **Fraud.** Real cost. Our fraud team is currently... me, sometimes. Need to hire or partner before launch.
- **Card delivery delays.** Physical cards take 5-10 business days. Set expectations clearly in UX.

## What I'm explicit about

Card issuing is a useful feature but it's not a defensible moat. The moat is the investing flywheel. The card is a hook into that flywheel. We build the hook quickly with a vendor and spend our engineering hours on the flywheel.

## Decision needed by

End of May. Investing feature ships Q3 and the card story is part of the Series B narrative.
