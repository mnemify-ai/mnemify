# ADR-030 — Snowflake to Postgres for ML Features

**Author:** Maya
**Status:** Accepted
**Date:** 2026-05-20

## Context

Devon's data team computes user features for our churn model and the personalized-deposit-amount model in Snowflake via dbt, then exports them nightly to Postgres for application-side serving. The export job is brittle, latency is 24 hours, and Devon has been asking for real-time features for the personalization model.

The "real" answer in a bigger company is a feature store (Feast, Tecton). We're not buying one. Wrong stage.

## Decision

Move feature computation that matters for real-time serving to Postgres. Snowflake stays for analytics and offline ML training. Clean boundary.

## What stays in Snowflake

- All raw event data
- All analytical dashboards
- Offline model training pipelines
- Anything finance, ops, or growth touches

## What moves to Postgres

- User-level features the personalization model needs (last deposit amount, days since last deposit, current balance, savings cadence, ~30 features per user)
- Computed in Postgres triggered by application writes (debounced where needed)
- Served from Postgres with sub-100ms latency

## Why this works at our stage

- Postgres is already our system of record
- ~3.6M rows in a feature table — trivial for Postgres
- Real-time means real-time, not "synced from Snowflake"
- We control consistency end-to-end

## Why not a feature store

- Tecton is $200k+/year
- Feast is open-source but adds operational surface (Redis online, S3 offline)
- Both designed for teams with feature platform engineers
- Devon is the data team AND the ML team. Not adding a feature platform on top of that.

## Cost comparison

- Snowflake export + Postgres serving: roughly $0 incremental
- Tecton: $200k/year
- Half a senior engineer: $200k/year

Revisit at 1M users. Not today.

## Migration

- Phase 1 (June): top 10 features the personalization model uses. Parallel Postgres path.
- Phase 2 (July): cut model to Postgres-only serving. Compare to baseline.
- Phase 3 (August): expand to remaining features. Deprecate Snowflake export.

## What I'm explicit about

This is not "let's build our own feature store." This is "use Postgres for what it's good at." If anyone says the word "platform" in a PR, I'm bouncing it.

## Risks

- **Feature drift between stores.** Real. Nightly comparison job flags > 1% discrepancies. Same job catches Snowflake bugs we have today.
- **Postgres write load increases.** Modest. Calculated. Not a problem.
- **ML model degrades during migration.** That's why we run parallel for 4+ weeks.

## What this enables

- Personalization model gets real-time features. Drops 24-hour staleness.
- Devon stops fighting the export job.
- One tool instead of two.

## What I'm not doing

- Not buying Tecton, Feast, or anything else.
- Not moving analytics out of Snowflake.
- Not letting this become a quarter-long project. Three months. Done.
