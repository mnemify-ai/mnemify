# On-Call Rotation Design

**Author:** Maya
**Status:** Live since 2025-Q3, revised after April incident
**Date:** 2026-04-15 (revision)

## What we run today

- Weekly on-call rotation, Monday 9 AM PT to Monday 9 AM PT
- 7 engineers in the rotation (all backend + senior data)
- Primary + secondary, both paged
- PagerDuty for routing
- Compensation: $200 stipend per week on-call, plus comp time for any page outside business hours

## What changed after April

The April 6 ACH incident exposed three problems:

1. **Mobile engineers weren't in the rotation.** When the issue surfaced as user-facing in the app, no one on the mobile team was paged.
2. **The secondary wasn't really secondary.** They got pages but assumed primary had it, no clear handoff.
3. **Sundays.** Highest-load day, lowest staffing. We rely on the on-call to be glued to their phone.

## What the rotation looks like now

- **Primary** rotates weekly, all senior engineers (8 in rotation including mobile)
- **Secondary** rotates weekly, all engineers (12 in rotation)
- **Sundays:** primary AND secondary both signal-on starting 4 PM PT through Monday 8 AM PT, since that's when ACH submission timing collides with end-of-weekend volume
- **Escalation path:** primary → secondary (15 min) → me (30 min) → Aleks (60 min if user-facing)

## Page severity definitions

- **P0** (page everyone): full system outage, money movement failure, security incident, regulatory exposure
- **P1** (page primary + secondary): partial outage, degraded performance affecting > 5% of users, single-customer money issue
- **P2** (page primary only): non-user-facing issue, internal tool broken, minor degradation
- **P3** (Slack alert, no page): observability anomaly, trend worth watching, fixable next business day

I'm explicit about these because P0/P1 inflation kills on-call.

## Stipend logic

$200 per week for primary. $100 per week for secondary. Plus PTO comp time for any page outside business hours (8 AM – 7 PM weekdays in their timezone).

Engineers also get a recovery day after any week with > 3 after-hours pages. Mandatory. I don't want anyone toughing it out.

## What I tell new engineers about on-call

- You're not expected to fix everything alone. Pull in whoever you need.
- If something pages you and you can't figure it out in 15 minutes, escalate. That's not failure, that's the system working.
- If you fix something during a page, write it up. Even small things. Future-you will be grateful.
- If you got woken up at 3 AM, take the morning. Tell your TL.

## What I expect from primaries

- Phone within reach at all times
- Acknowledge pages within 5 minutes
- Initial response (assessment, escalation, fix) within 30 minutes for P0/P1
- Write up the incident the same day or next business day

## Common failure modes I've seen

- **Page fatigue.** Too many P2s upgraded to P1s. Mitigation: weekly review of paged incidents, downgrade what should have been P2.
- **Hand-off gaps.** Primary changes mid-incident. Mitigation: written handoff protocol.
- **The "I'll just fix it" trap.** Engineers staying up until 2 AM solving a P2. Mitigation: explicit message — go to bed, fix tomorrow.

## What I'm tracking

- Pages per week (trending? noise issue?)
- Pages per engineer (load distribution?)
- Time-to-acknowledge (5 min target)
- Pages outside business hours (compounding stress signal)
- Recovery days taken (are people using them?)

Reviewed monthly in 1:1 with each TL.

## What I'm watching for

- Hero culture creeping in. We don't celebrate the engineer who's always on call.
- Burnout signals. Pages aren't free, regardless of stipend.
- Quiet underreporting. Engineers who don't write up incidents because "it was minor."

## Open questions

- When we hit 25 engineers, do we split into pod-specific rotations? Probably. Money movement on-call vs. mobile on-call vs. data on-call are different shapes.
- Do we add a "follow the sun" rotation when we have a remote engineer in another timezone? Yes, when we have 2+ remote in a single timezone.
- Do we hire dedicated SRE? Not yet. At 30+ engineers, maybe.

## Personal note

I rotate too. I'm not exempt. The team notices when leadership skips the unglamorous parts and I'm not going to be that person.
