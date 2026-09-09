# Engineering Culture — Operating Principles

**Author:** Maya
**Status:** Living doc, shared with team
**Date:** 2026-03-15 (last revised); originally 2025

## Why this exists

When the team was 4 people, culture was whatever we did. At 14, it's what we say it is, and people start to notice when we drift from it. At 30, it's the most important thing I work on.

These are the principles I want the engineering team operating on. Not laminated values. Concrete behaviors.

## Ship the work

We're a startup. Velocity matters. A merged PR that solves 80% of the problem is worth more than an open PR that solves 100%.

This does not mean cut corners on safety. Money movement and KYC code is held to a different bar. But on the 90% of code where we have room to iterate, we ship and improve.

## Own your blast radius

If your code breaks something, you're on the hook. Not in a punitive sense. In a "you're the person who knows enough to fix it" sense. When something goes wrong, the engineer who shipped the change is in the room.

Corollary: if you're the most senior person who saw the change, you also own outcomes. Reviewing is a commitment.

## We don't do hero culture

Long hours don't get celebrated here. Pulling all-nighters to ship something is a sign of bad planning or bad scope, not heroism. If someone needs to work weekends, something's broken upstream — we fix the upstream thing.

On-call is on-call. Show up for your week, hand off cleanly. If you're carrying load between weeks, tell me.

## Disagree well

Disagreement is healthy. We disagree in writing where possible (in PRs, ADRs, comments) and in person where it matters. We do not avoid disagreement to keep things pleasant. Pleasant disagreement-avoidance is how you get to a bad architecture nobody believed in.

Once a decision is made, the disagreement ends. Disagree and commit. Re-litigating decided things wastes everyone's time.

## Audit trails matter

We're regulated. We're handling people's money. Every meaningful state change is auditable. Every decision has an ADR or a postmortem. Every prod incident gets written up, even small ones.

This is a competitive moat, not a bureaucratic burden.

## Mentorship is mandatory

Senior engineers mentor mid-level engineers. Mid-level engineers mentor juniors. If you're not mentoring, you're not growing. Skip-level on this is on me to check.

I don't care about formal mentorship programs. I care that someone less experienced than you trusts you enough to ask a dumb question.

## Don't optimize for "looking senior"

Some engineers spend cycles polishing things to seem impressive. Don't. Spend cycles solving real problems for real users. The team rewards impact, not theater.

Specifically: I don't care if your PR description is beautiful. I care if your code works and your test coverage is real.

## Read the room

You're a small team. You see everyone every day. If a teammate is struggling, notice. If a teammate is shipping consistently, say so. If something feels off in a meeting, name it.

This is the soft skill that compounds. Engineers who only optimize for individual output plateau.

## On the use of AI

Use it. We pay for it. Claude, Cursor, whatever helps you ship faster. The only rule: you own the code that lands in main. If you ship something you don't understand, that's on you.

I'm allergic to "the AI did it" excuses.

## On meetings

We have too many. I'm working on it. In the meantime: if you're in a meeting where you don't contribute and don't learn, leave. Politely if possible. Just leave. Time is the most expensive resource here.

## How I judge myself against these

If I'm the bottleneck on shipping work, I'm failing at "ship the work."
If I'm not in the room when things break, I'm failing at "own your blast radius."
If I'm celebrating hero hours, I'm failing at "no hero culture."
If I'm avoiding hard conversations, I'm failing at "disagree well."

I expect the team to call this out if they see it. Several have.

## Review cadence

Annually. These will evolve. The shape is more important than the words.
