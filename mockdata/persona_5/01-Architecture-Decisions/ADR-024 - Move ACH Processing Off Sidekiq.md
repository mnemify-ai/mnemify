# ADR-024 — Move ACH Processing Off Sidekiq

**Author:** Maya
**Status:** Accepted
**Date:** 2026-04-19
**Supersedes:** ADR-009

## Context

Our ACH origination batches run through Sidekiq workers backed by Redis. Worked fine at 20k MAU. At 120k MAU it's a fire on Sundays — our highest-volume cadence day — and the April 6 incident proved it. Workers stalled, retries piled up, we missed the 6 PM PT NACHA submission window for one batch, 2k users had their auto-savings delayed three days.

I'm not interested in another postmortem with "we'll add monitoring." We're moving ACH processing onto a dedicated, durable, idempotent pipeline. Sidekiq stays for everything else.

## Decision

ACH origination and return processing move to a Go service backed by Postgres outbox + AWS SQS FIFO. Each ACH file becomes a row with a strict state machine: `pending → packaged → submitted → settled` (or `returned`). State transitions are idempotent. The submission cron is replaced by a leader-elected worker that drains the queue.

## Why not just throw more Sidekiq workers at it

Tried it. Doesn't fix the actual problem. The actual problem is: Sidekiq is at-least-once, retries are visible to the worker code, and ACH submission must be exactly-once against NACHA windows. Adding workers makes the race conditions worse, not better. Marcus and I went through this on a whiteboard. Hard no.

## Why Postgres outbox

We already run Postgres for the system of record. Adding an outbox table is a few-line migration. The outbox + SQS FIFO pattern gives us:
- Atomic writes — the ACH intent and the queue message commit together
- Exactly-once consumption on the worker side
- A replayable audit log that satisfies our BSA/AML obligations

I considered Kafka. Kafka is overkill for our volume and adds an operational surface we don't need yet. Revisit at 1M MAU.

## Why Go

Marcus's team owns this. They write Go. The Rails monolith stays in charge of user-facing APIs. Splitting along this seam is clean.

## What this isn't

This isn't a microservices migration. We're carving out one critical pipeline. Everything else stays in the monolith. Anyone who reads this ADR as a license to spin up six new services will hear from me.

## Rollout

Two phases. Phase 1: shadow mode. New pipeline runs alongside Sidekiq, writes to a parallel ledger, we diff outputs nightly. Two weeks minimum. Phase 2: cut over on a slow day (Tuesday), Sidekiq path stays dormant for rollback for 30 days, then we kill it.

Aleks signed off on the timeline. Pillar Bank's integrations team was looped in on April 17 — they're fine, the file format isn't changing.

## What I expect from this

Sunday peak throughput goes from "fingers crossed" to boring. We add a 6-hour cushion against the NACHA window. Returns processing latency drops because we're not waiting on Sidekiq retry storms. The audit trail tightens up enough that the BSA/AML auditor in June stops finding paper cuts.

If we miss another NACHA window after this ships, the problem isn't infrastructure — it's the team and that's a different conversation.

## Open questions

- Do we expose the state machine to support so they can answer "why is my deposit late" without paging on-call? Yes, post-launch. Renee owns the UX.
- Do we extend this pattern to card transactions eventually? Probably. Different ADR when the time comes.
- Pillar Bank's settlement file format is rumored to change in Q3. We'll handle it then. Not blocking.

## What I'm signing up for personally

I'll be on review for every PR in this pipeline until cut-over. Not because the team can't ship — because if this breaks again, it's on me to know exactly what's in the code.
