# Stencil 3-Year Technical Vision

**Author:** Maya
**Status:** Personal working doc, may share with leadership eventually
**Date:** 2026-05-10

## What this is

The 3-year picture of what Stencil's technology looks like if we execute. Not a commitment. A direction. I write it down because if I can't articulate it, I can't lead toward it.

## Where Stencil is in 3 years (early 2029)

- **5M+ MAU** across our consumer products
- **Multi-product:** savings + investing + card + (possibly) credit
- **Multi-region** infrastructure (US-first, but capable of expansion)
- **Series C** closed (or independent and profitable)
- **70-100 engineers** organized into product pods, infrastructure team, and a small platform team
- **Bank charter** — we're either applying or seriously considering it (depends on Series C strategy)

## What our tech stack looks like

Most of what we have today, refined:

- **Backend:** Go (more services than today) + Postgres (sharded, mostly horizontally)
- **Mobile:** SwiftUI (TCA) on iOS, Jetpack Compose on Android, deeply native both platforms
- **Data:** Snowflake + dbt for analytics, Postgres for real-time features, separate ML training infrastructure
- **Infrastructure:** AWS, Kubernetes, ArgoCD for deployments, Terraform for everything
- **Observability:** Datadog + structured logging + our own customer-facing dashboards

The stack isn't exotic. It's well-trodden. That's deliberate. Our innovation is in the product, not in the underlying technology.

## What capabilities we have that we don't today

- **Real-time fraud detection.** ML model in the transaction path. Customer protection that's invisible when working.
- **Personalization that compounds.** Every interaction makes the next one better. Not just "show me a recommendation" — actually shape the product to the user.
- **Banking-grade reliability.** Five nines on money movement, automated failover, no Sunday incidents.
- **Self-service for ops.** Customer support resolves 80% of issues without engineering. Internal tools matter.
- **Investing maturity.** Beyond ETFs — fractional individual stocks, scheduled investments, tax loss harvesting where appropriate.
- **Card-and-investing integration.** Round-up-to-invest works seamlessly. Subscription-pause investing during slow months works.

## What our team looks like

- **CTO** (me) — running architecture, board, hiring, strategic relationships
- **VP Engineering** — running engineering operations
- **5-6 directors** — running product pods (mobile, money movement, investing, growth/personalization, infrastructure, data)
- **Tech leads** — running pod technical direction
- **Engineers** — distributed across pods, 6-10 per pod
- **A real platform team** — 4-6 engineers owning shared infrastructure
- **A real security/compliance engineering team** — 2-3 engineers

The org tilts toward delegation. I'm not in every architectural conversation. I'm in the strategic ones.

## What our culture is

Stronger version of what it is today. Same values, more scaffolding.

- We still ship the work
- We still own our blast radius
- Mentorship is more structured (real growth paths)
- Hiring is more bar-raiser-driven
- Performance reviews are calibrated across pods
- The bar is higher because the team is bigger

If the culture doesn't survive scaling, none of the rest matters.

## What I'm NOT building toward

- **A platform we sell to other companies.** Stencil is a consumer product, not a B2B fintech platform.
- **Crypto.** Will not get into it.
- **A neobank with checking + savings + everything.** We're focused on the savings-to-investing-to-growth-wealth flywheel. Not Chase.
- **International expansion before US dominance.** Different game.

## What worries me about this vision

- **Hiring at this pace.** 4-5x team growth requires a hiring engine I haven't built yet. VPE has to fix this.
- **Maintaining quality.** Easy to lose at scale. Process won't save us — only culture and rigorous hiring will.
- **Regulatory shifts.** Fintech regulations evolve fast. A wrong-footed move with a regulator costs years.
- **Vendor concentration.** Pillar, Plaid, DriveWealth, AWS — single points of failure that grow as we grow.
- **My own scaling.** I have to grow as a leader as the company grows. That's not automatic.

## What I'm doing now to enable this vision

- **Architectural choices** that don't paint us into corners (Postgres-first, abstraction layers, monolith with carve-outs)
- **Hiring** for the next stage, not just the current need
- **Operating principles** that scale (the culture doc, the on-call doc, the meeting cadence)
- **Vendor relationships** that grow with us (good terms with Pillar, exploratory with backup providers)
- **Compliance as architecture** so it doesn't become a bottleneck

## Review cadence

Annually. Doc gets revised. Strategy that doesn't get revised dies.

## Personal note

Writing this is a way to remember what I'm working toward when the day-to-day is firefighting. The 18-month strategy is the operational version. This is the aspirational version. Both matter.
