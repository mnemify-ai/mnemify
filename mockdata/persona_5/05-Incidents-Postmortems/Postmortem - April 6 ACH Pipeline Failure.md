# Postmortem — April 6 ACH Pipeline Failure

**Incident:** April 6, 2026 (Sunday)
**Severity:** P0 (customer money movement delay, no actual financial loss)
**Author:** Maya
**Reviewed by:** Marcus, Aleks
**Status:** Closed, action items in flight

## What happened

On Sunday April 6 between 4 PM and 11 PM PT, our ACH origination pipeline stalled. The Sunday afternoon submission batch — containing 2,138 user auto-deposits totaling $147k — failed to submit to Pillar Bank before the 6 PM NACHA cutoff. Affected users saw their deposits delayed by 3 business days (Monday-Wednesday April 7-9).

No funds were lost. No regulatory violation occurred (cutoff missed, not regulatory deadline). Customer trust took a hit.

## Timeline

- **April 6, 4:14 PM PT** — Sidekiq workers begin processing the Sunday batch. Normal.
- **4:38 PM** — Worker throughput drops to ~10% of expected. Devon's dashboard shows the anomaly. He pings Marcus on Slack.
- **4:45 PM** — Marcus investigates. Sees Redis memory pressure and worker stalls. Initial hypothesis: Redis OOM.
- **5:10 PM** — Marcus restarts Sidekiq workers. Throughput recovers briefly, then stalls again. Hypothesis: not Redis.
- **5:34 PM** — Marcus identifies the actual issue: NACHA file generation is hung on a large batch (~800 transactions). The serialization step is O(n²) on a previously-uncommon code path.
- **5:48 PM** — Marcus deploys a fix bypassing the bug. Workers resume.
- **6:00 PM** — NACHA submission deadline passes. The repaired batch is too late to submit.
- **6:12 PM** — I'm paged. Maya joins the war room (Marcus, Aleks, Renee).
- **6:30 PM** — Decision: file for Monday submission. Affected users will see funds Wednesday.
- **7:45 PM** — Customer comms drafted. Sent to email + push by 9 PM.
- **11:00 PM** — All 2,138 users notified. Compensation plan (credit) approved.
- **April 7-9** — Repaired batch submits Monday, settles Wednesday. Affected users receive deposits.

## Root cause

The serialization step for the NACHA file format had a hot path and a cold path. The hot path was tested. The cold path triggered on batches with certain mixes of transaction types — specifically, when more than 30% of the batch was Pillar Bank's "modified ACH" return-on-failure type.

The cold path was O(n²) in batch size. For most batches (< 200 transactions of this type), it completed quickly enough to go unnoticed. The April 6 batch happened to be 35% modified-ACH (above the threshold) and 800+ transactions total. The serialization took multiple minutes per transaction.

Sidekiq workers timed out, retried, failed again. Cascade.

## Contributing factors

- **Untested code path.** The cold path had been written 14 months earlier for a different reason and was rarely exercised. Tests didn't cover it.
- **No batch-size monitoring.** We had no alert on individual batch size. The 800+ batch was anomalous; we should have caught it.
- **Sidekiq's at-least-once semantics.** Retries amplified the problem, didn't help.
- **Sunday staffing.** Devon caught the anomaly because he happened to be checking dashboards. We don't pay engineers to monitor dashboards on Sundays. Pure luck.
- **No automated fallback to next-day submission.** When NACHA cutoff was missed, we didn't have a clean path to "submit Monday morning instead." Manual decision under pressure.

## What we did well

- Engineers detected the issue within 25 minutes of onset.
- Marcus diagnosed the root cause within an hour.
- Customer comms were honest and out within 5 hours.
- Compensation issued proactively.
- No regulatory exposure.
- Aleks and I were aligned on the response.

## What we did poorly

- Should have caught the anomalous batch size before processing began.
- Should not have had an untested O(n²) code path in money movement.
- Sidekiq architecture for ACH was fragile and known. Knew it. Didn't prioritize.
- Customer compensation was reactive, not proactive (we should have had a "if cutoff missed, do X" runbook).

## Action items

- **[DONE] Hotfix the O(n²) serialization** — done April 7
- **[DONE] Add batch-size alerts** — done April 8
- **[DONE] Customer comms playbook for ACH delays** — done April 10
- **[IN PROGRESS] ADR-024: Move ACH off Sidekiq to dedicated pipeline** — Phase 1 shadow mode live, cut-over June
- **[IN PROGRESS] Sunday on-call protocol update** — primary + secondary signal-on Sundays
- **[DONE] Customer comp plan codified** — $25 credit per affected user for any "delay caused by our error"
- **[OPEN] Pillar Bank coordination on missed-cutoff protocol** — meeting June 4
- **[OPEN] Annual review of "cold path" code in money movement** — Q3 owner: Marcus

## Lessons

1. **Money movement code paths must be tested or removed.** Period. Cold paths that exist "in case" are a liability.
2. **Architectural fragility known but not prioritized compounds fast.** I knew Sidekiq for ACH was wrong. I should have prioritized the fix.
3. **Monitoring is not detection.** Devon caught this manually. We need automated detection at the boundaries.
4. **Customer comms speed matters more than message polish.** Our customers respected the speed; they would not have respected silence.

## Personal note from Maya

This is the worst engineering day of my Stencil tenure. The team handled it well. The architecture I let stand caused it. The board took my honest assessment well; the team took my honest assessment harder. The right response is the architecture rebuild, not a louder apology.

If a similar failure happens after the ACH pipeline rebuild ships, the issue is no longer infrastructure. It's me. That's the frame I want to hold myself to.
