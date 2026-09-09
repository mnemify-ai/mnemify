# Vendor Risk Register

**Author:** Maya
**Status:** Living doc, reviewed quarterly
**Date:** 2026-05-05

## What this is

Every critical vendor we depend on, the risk profile, and our mitigation. Maintained because Series B diligence will ask, BSA/AML auditor will ask, and because vendor failures will absolutely happen.

## Tier 1 — Existential

These are vendors whose failure causes us to stop operating.

### Pillar Bank (sponsor bank, BaaS)

**Risk profile:** Catastrophic. Without Pillar we have no ability to hold customer money or send ACH.

**Concentration:** Single sponsor bank. No backup.

**Mitigation:** None viable. Sponsor bank relationships take 12-18 months to establish. Backup sponsor would be that long to onboard.

**Watch items:** Pillar's financial health (we monitor), regulatory actions (none currently), management changes.

**Contingency:** If Pillar shut down, we'd have 30-60 days of notice typically and would need to scramble to onboard a replacement. Real existential risk.

**What I'm doing:** Maintaining executive relationship at Pillar (Aleks owns). Watching for early warning signs.

### Plaid (account connectivity)

**Risk profile:** Catastrophic if extended outage. High dependence on their uptime.

**Concentration:** No realistic alternative at our scale. MX is the alternative; lower coverage.

**Mitigation:** Caching strategy reduces direct dependence for read operations. We can serve users for hours without Plaid. Account linking is the failure point — if Plaid is down, new signups break.

**Contingency:** Have MX integration designed but not built. Would take 4-6 weeks to deploy.

**Watch items:** Plaid's uptime history (good but imperfect), pricing changes (renegotiated in 2025), policy changes (their data access rules evolve).

## Tier 2 — Major Impact

These are vendors whose failure causes degradation or significant operational issues.

### AWS

**Risk profile:** High but well-understood. Multi-region failover not built.

**Mitigation:** Within-region multi-AZ redundancy.

**Contingency:** Multi-region planned for 2027.

### DriveWealth (investing — pending integration)

**Risk profile:** High once investing is live. Sole brokerage relationship.

**Mitigation:** Same pattern as Pillar — abstraction layer, but realistically not portable.

**Contingency:** None for the foreseeable future. We're choosing a brokerage relationship knowing it's a major dependency.

### Alloy (KYC — pending migration)

**Risk profile:** Medium. Alloy's orchestration layer means we can swap downstream providers, but Alloy itself is in critical signup path.

**Mitigation:** Alloy is well-funded and stable. Their architecture means downstream provider issues are absorbed by them.

**Contingency:** Could migrate to direct provider integration in emergency, ~3 months.

### Customer.io + Branch (notifications)

**Risk profile:** Low for marketing (can delay campaigns), High for transactional (security alerts must deliver).

**Mitigation:** Abstraction layer enables vendor swap. Fallback to direct APNs/FCM for transactional in emergency.

## Tier 3 — Operational

These are vendors whose failure causes inconvenience or internal disruption.

### Datadog (observability)
Risk: Operational. We can run blind for hours. Not catastrophic.
Contingency: Switching to alternatives (NewRelic, etc.) is non-trivial but possible.

### Snowflake (data warehouse)
Risk: Operational. Analytics and ML training affected, not customer-facing.
Contingency: BigQuery is the obvious alternative. Months to migrate.

### GitHub (source control + CI/CD)
Risk: Operational. Development stops if extended outage.
Contingency: Could migrate to GitLab in weeks if needed.

### Persona (KYC — phasing out)
Risk: Reducing. Migration to Alloy in progress.

### Sidekiq Pro
Risk: Reducing. Most critical use case being moved off (ADR-024).

## What this tells me

- **Pillar Bank is our biggest existential risk.** Real and unmitigatable in the short term.
- **Plaid is second.** Mitigatable but not yet mitigated.
- **DriveWealth becomes #2 after investing launch.** Acceptable risk for product reasons.
- **Everything else is manageable.**

## What I do quarterly

- Review this register
- Confirm financial health where applicable
- Update mitigations as situations change
- Re-evaluate concentration risks

## What I do annually

- Full risk assessment with our outside compliance counsel
- Update the vendor risk presentation for board

## Open questions

- Should we add a backup sponsor bank in 2027? Probably yes. Aleks's call to make.
- Should we build the MX backup for Plaid before we need it? Maybe. Cost vs. risk tradeoff.
- DriveWealth alternative when we need one? Apex Clearing or similar. Years away.

## Personal note

I sleep better having this written down. The risks don't disappear by being documented but they become manageable instead of vague.
