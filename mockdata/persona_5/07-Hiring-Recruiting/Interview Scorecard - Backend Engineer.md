# Interview Scorecard — Backend Engineer

**Author:** Maya
**Status:** Standard scorecard
**Date:** 2026-04-15 (last revised)

## Purpose

Calibration. Every interviewer fills this out within 24 hours of their interview. We compare scorecards in the hiring debrief.

Without this, we drift. The candidate who interviewed best on Wednesday gets compared favorably to the candidate from three weeks ago whose interview we half-remember.

## Scale

For each dimension, score 1-5:

- **5 — Exceeds bar significantly.** This person would raise the team's level.
- **4 — Solid bar.** Clear hire signal in this dimension.
- **3 — Borderline.** Could go either way. Need other dimensions to push.
- **2 — Below bar.** Concerns worth raising in debrief.
- **1 — Far below bar.** Strong no-hire signal in this dimension.

We do not allow "3.5" or any half-scores. Pick a side.

## Dimensions

### Technical depth

Does this person know their stuff? Can they answer follow-up questions about how something they built actually worked? Did the system design conversation reveal real experience or shallow buzzwords?

Specific things to look for:
- Can articulate trade-offs in past architectural decisions
- Understands what they don't know and says so
- Doesn't overclaim familiarity with technologies
- Can debug a problem with no prep

### Code quality

For the pair-programming round especially. Did they write code I'd be comfortable with in our codebase? Did they think about edge cases? Did they write tests when appropriate?

Specific things to look for:
- Names variables and functions clearly
- Handles errors thoughtfully
- Writes code that would survive review
- Considers performance and correctness simultaneously

### Communication

How well does this person explain their thinking? Do they listen? Can they push back when they disagree without being defensive?

Specific things to look for:
- Asks clarifying questions before diving in
- Explains decisions in clear language
- Receives feedback well
- Disagrees professionally when they do

### Ownership

Would this person own a system end-to-end? Do they think about consequences beyond their immediate task?

Specific things to look for:
- Asks about deployment, monitoring, on-call when describing past work
- Stories about debugging in production, not just writing in dev
- Awareness of how their decisions affect downstream teams

### Fintech / money-domain awareness

Optional dimension, scored only if the candidate has fintech background. Do they understand the regulatory environment? Do they care about correctness in money systems?

Specific things to look for:
- Knows the difference between "the test passed" and "the money moved correctly"
- Has shipped to production with money on the line
- Understands compliance is a partner, not an obstacle

### Cultural fit (not "personality fit")

Does this person work well in our style? Direct communication, async-first, ownership-heavy?

Specific things NOT to confuse with this:
- Background. We don't filter on schools or pedigree.
- Personality type. We have introverts and extroverts.
- Communication style preference. Some engineers are quiet. Doesn't matter.

What we look for:
- Comfortable with ambiguity
- Doesn't need formal process to function
- Will speak up when something's wrong
- Is generous with information

## Overall recommendation

After scoring dimensions, give an overall recommendation:

- **Strong hire** — would actively bring this person on, push hard for the offer
- **Hire** — solid candidate, would hire if offer extended
- **No hire** — would not hire, concerns outweigh strengths
- **Strong no hire** — would actively block this hire

We weight "strong" recommendations more in the debrief. A single "strong no hire" can veto.

## Required: 2-3 specific stories

Every scorecard must include 2-3 specific moments from the interview. Vague recommendations don't help.

Example:
- "When asked about the Sidekiq architecture they'd built, they immediately mentioned the failure mode (worker stalls under high load) and how they fixed it. Showed real production thinking." (Strong technical depth signal)
- "When I pushed back on their proposed solution, they paused, asked me a clarifying question, then explained their reasoning more carefully without getting defensive." (Strong communication signal)

## Anti-patterns to watch in scorecards

- **"Smart but I don't know"** — if you don't know, that's a no
- **"I'd hire them for a different role"** — that's a no for this role
- **"They were nervous so I'm being generous"** — calibrate the same regardless of nerves
- **"They reminded me of [former colleague]"** — anchoring bias; ignore the comparison

## Debrief expectations

- Scorecards reviewed in hiring debrief (max 30 min)
- Hiring manager makes the final call
- Disagreements get hashed out in the room, not after
- Decisions documented (offer / no offer / continue conversation)

## What I tell new interviewers

The scorecard is not a checklist. It's a forcing function. If you can't fill it out specifically, you weren't paying enough attention during the interview.
