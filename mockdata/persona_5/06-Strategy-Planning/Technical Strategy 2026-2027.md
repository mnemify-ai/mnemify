# Technical Strategy 2026-2027

**Author:** Maya
**Status:** Living doc, shared with leadership team
**Date:** 2026-04-30

## What this is

The 18-month technical strategy for Stencil. Not a roadmap. A frame for how we make decisions when the roadmap inevitably changes.

## The three things that have to be true in 18 months

1. **We can handle 1M MAU without re-architecting.** Not by over-building today. By making choices today that don't paint us into corners.
2. **We can launch a regulated financial product (investing, then card) without engineering becoming a compliance bottleneck.** Compliance as architecture, not paperwork.
3. **We can run with 25-30 engineers without me being a bottleneck on every decision.** Org and tooling support delegation.

If those three are true, we're set up for Series C. If any is false, the company has hit a real wall.

## What we won't do

- **Microservices everywhere.** Tempting. Wrong for our size. We carve out services where coupling is dangerous (money movement, brokerage integration) and keep the rest in the monolith.
- **Premature multi-region.** Single region (us-east-1) until we have customers outside the US. Adds complexity for negligible benefit today.
- **Build our own platforms.** No internal PaaS, no homegrown deployment system, no custom monitoring stack. We use vendors (AWS, GitHub Actions, Datadog) and accept the tax.
- **Adopt every new technology.** We will not be the first Stripe-scale company on the new database. Maturity matters.

## What we will do

- **Carve out critical pipelines as services.** ACH, brokerage, KYC all become independently-deployed services with strict interfaces. The monolith handles user-facing CRUD.
- **Postgres-first, until it isn't enough.** When Postgres stops being enough, we vertical-shard then move specific tables to specialized stores. Not before.
- **Compliance as code.** Audit logs, idempotency, error budgets are architectural concerns, not after-thoughts.
- **Build a real platform team.** Hire an infra lead. Own Kubernetes, observability, CI/CD as a function.
- **Invest in test infrastructure.** Money movement tests must hit a real database, real Plaid sandbox, real ACH simulator. Mocks are forbidden in this layer.

## Capability priorities

In order of importance to the business in the next 18 months:

1. **Reliable money movement.** This is the floor. If we can't move money reliably, nothing else matters.
2. **Investing infrastructure.** DriveWealth integration, position reconciliation, regulatory disclosures. Q3 2026 launch.
3. **Card issuing infrastructure.** Lithic integration, transaction processing, fraud monitoring. Q4 2026 launch.
4. **Personalization.** Better deposit amount, better timing, better cadence. Drives engagement.
5. **Internal tooling.** Customer support tools, ops dashboards, compliance reporting. Compounding investment.

Notice what's missing: nothing about "platform" or "abstraction layer" or "framework." We are not building horizontal infrastructure. We are building consumer fintech features.

## Team capability priorities

The team has to know:

- **Money movement engineering.** Concrete protocols (NACHA, ISO 20022), state machines, idempotency patterns
- **Mobile engineering.** iOS and Android both. Modern patterns. Performance discipline.
- **Data engineering.** Snowflake, dbt, real-time features
- **Security and compliance engineering.** Not as a separate role but as a skill set across the team
- **Operating on AWS at moderate scale.** Container orchestration, observability, cost management

We invest in these capabilities. We do not chase fashion.

## What I'm explicit about

- **Pace > polish.** We ship working software. We do not ship beautiful software at the cost of pace.
- **No big bangs.** Every major change is feature-flagged, shadow-deployed, gradually rolled out. We do not "cut over."
- **Vendors are not partners.** Pillar Bank, Plaid, DriveWealth, Lithic — they're suppliers. We treat them with respect but their delays are not our excuses.
- **Engineering capacity is finite.** Every "yes" to a project is a "no" to something else. We prioritize ruthlessly.

## How I'll know if this is working

In 18 months:
- 1M MAU served on infrastructure that scales (or has a clear path)
- Investing + card both live
- 25 engineers shipping at the same per-engineer velocity as 14 today
- No P0 incidents from architecture we already knew was wrong
- Zero compliance findings of "significance" in any audit
- A VPE running engineering operations, with me on architecture and strategy

## What I'm uncertain about

- The right time for the platform-team hire. Could be Q4, could be Q1.
- Whether to invest in a homegrown ML platform or stick with Postgres-for-features.
- The right pricing model for investing (covered separately).
- Whether we need a security engineer hire or can keep contracting.

These will be quarterly review topics.

## Review cadence

Quarterly. Doc gets revised. Strategy that doesn't get revised gets stale.
