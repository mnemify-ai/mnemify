# Incident — Snowflake Cost Spike February 2026

**Date:** 2026-02-12 (discovered)
**Severity:** P2 (cost, not customer-facing)
**Author:** Devon, with Maya review

## What happened

Our Snowflake monthly bill jumped from ~$8k/month to a projected $28k for February. Discovered February 12 when AWS billing alerts triggered (Snowflake bills through our AWS account).

If left unaddressed for the full month, would have added $20k in unplanned costs. Not catastrophic but real.

## Root cause

A new dashboard for the growth team was running a query every 5 minutes against the events table. The query joined three large tables and didn't have an index hint. Each execution was burning ~$0.40 in compute. At 5-minute intervals, that's $115/day, $3.5k/month for a single dashboard.

Kavi requested the dashboard. Devon built it. Neither of us noticed the cost profile because we don't have per-dashboard cost monitoring.

## Why this happened

- **No cost monitoring at the dashboard level.** We have aggregate Snowflake spend metrics but no breakdown.
- **No "is this query expensive" check at dashboard creation.** Devon built the dashboard, it worked, he shipped.
- **The 5-minute refresh interval was excessive.** A dashboard the growth team checks twice a day doesn't need 5-minute freshness. Default settings.
- **Snowflake compute pricing is opaque.** It's hard to predict the cost of a query without running it.

## What we did

- **Immediate:** changed the dashboard refresh interval to 1 hour (kept all the other functionality). Cost dropped from $115/day to $9/day.
- **Short-term:** Devon added a query hint that uses an aggregation table we already maintain. Cost dropped further to ~$2/day.
- **Medium-term:** added per-warehouse spend monitoring in Snowflake. Daily Slack digest of top 5 most expensive queries.
- **Long-term:** dashboard creation now requires a "estimated daily cost" field that the creator has to fill in.

## Impact

- February bill came in at $11k (vs. $8k baseline) instead of $28k
- One-time saved: ~$17k
- Ongoing process savings: probably another $30-50k/year as we catch similar issues

## What we did well

- Caught it within 12 days of the spike starting
- Devon's instinct to optimize the query before throwing more compute at it was right
- The longer-term process changes were proportional to the issue (didn't overcorrect)

## What we did poorly

- Should have had per-query cost monitoring earlier
- Devon should have validated the query plan before shipping
- I should have asked about cost when reviewing the dashboard request

## Lessons

1. **Cloud costs at our scale are real money.** A 3x bill spike in one month is meaningful. We can't operate like a Series D company at our spend.
2. **Dashboards are software.** They get deployed, they consume resources, they need monitoring. We've been treating them as one-time queries.
3. **The growth team needs cost-aware tooling.** Kavi isn't going to be the gatekeeper on cost. The tooling has to make expensive choices visible.

## Action items

- **[DONE] Dashboard refresh interval fix** — 2026-02-13
- **[DONE] Query optimization** — 2026-02-14
- **[DONE] Per-warehouse spend monitoring** — 2026-02-20
- **[DONE] Dashboard cost estimation field** — 2026-03-01
- **[OPEN] Monthly Snowflake spend review** — Devon owns, in 1:1 with Maya

## What this isn't

This isn't a "we need to move off Snowflake" moment. The tool is fine. Our usage was wrong. The lesson is internal, not vendor-flip-able.

## Personal note from Maya

This is the kind of operational issue that doesn't make headlines but compounds quietly. I should be reviewing cloud spend monthly with Devon and Marcus. Adding to my regular cadence.
