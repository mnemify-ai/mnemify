# Postgres Sharding Strategy (Not Yet, But Planning)

**Author:** Maya
**Status:** Pre-decision; document for when we need it
**Date:** 2026-04-30

## Why this doc exists

Sometime in the next 18 months, our primary Postgres will hit a wall. Either compute, IO, or table size. I want a plan written down before the fire so we're not making architecture decisions under load.

We are NOT sharding today. The primary is comfortably handling 120k MAU on a db.r6i.4xlarge. We've got headroom. But headroom isn't a strategy.

## When we shard

Triggers (any of):
- p99 query latency exceeds 100ms for 7+ days running
- Replica lag exceeds 30s under normal load
- We exceed 4TB on the primary
- We exceed 60% sustained CPU
- A specific table exceeds 500GB and we can't partition it

Today: we're at ~800GB total, 25% CPU peak, 40ms p99, lag in seconds.

## The plan when we do

### Phase 0 — Buy time (do all of these first)

- Move read traffic to read replicas where consistency allows (90% of dashboard queries)
- Aggressive query optimization on top 20 slow queries
- Partition the events table by month (largest table by far)
- Move event-derived data to a separate Postgres cluster (already planned)

If those four buy us 12 months, we win.

### Phase 1 — Vertical shard (cheap, easy, big wins)

- Carve out high-volume tables to their own Postgres instances
- Likely candidates: `transactions`, `events`, `notifications`
- Each carve-out is a multi-week project but doesn't require sharding logic
- Estimated gain: 50-70% load reduction on primary

### Phase 2 — Horizontal shard (only if Phase 1 isn't enough)

- Shard by user_id
- Use Citus or roll our own (probably Citus — proven, supported)
- This is the expensive option. 6 months of engineering. Major architectural surgery.

## Why not Citus or sharding from day one

People love to talk about sharding architectures. Almost no one needs them at our stage. Premature sharding is one of the more expensive engineering mistakes. The complexity tax is enormous and you pay it forever, not just at shard time.

Vertical sharding alone gets most fintech-scale companies to 5M+ users. We're at 120k.

## What I want the team to internalize

- Postgres at our scale is not the bottleneck. Our query patterns sometimes are.
- Before architectural changes, exhaust query optimization. Most "we need to shard" conversations end with "actually we need to add an index."
- Schema choices today affect shardability later. We're already laying out tables with user_id as the natural partition key. Stick to that.

## What we're doing today to prepare

- All new tables include `user_id` if they're user-scoped. No exceptions.
- We avoid cross-user joins where possible. They survive shard-friendly migrations.
- Foreign keys to `users` are intentional. Cross-table foreign keys we keep minimal.
- Events go to a separate cluster from day one of the next migration.

## What we're NOT doing today

- Citus deployment
- Distributed transaction logic
- Sharded primary key generation
- Anything that adds operational complexity before we need it

## Open questions for future-Maya

- Will we hit Phase 1 trigger first or Phase 0 exhaustion?
- Does Series B funding accelerate this (more headroom to over-build)?
- Does the investing feature change the load profile significantly?

## When to revisit this doc

- Quarterly review against the trigger metrics
- Whenever Marcus says "we have a problem"
- Before any Series B narrative that requires explaining infrastructure scale

## What I'm explicit about

The right answer at our stage is "not yet, here's the plan." If anyone tries to make this an immediate project, they're solving a problem we don't have at the cost of problems we do.
