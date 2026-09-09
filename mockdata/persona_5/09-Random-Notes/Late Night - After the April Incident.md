# Late Night — After the April Incident

**Date:** 2026-04-09 (around midnight)
**Format:** Journal entry

## What I'm thinking about

It's been three days since the ACH incident. The funds finally settled tonight. The affected users got their deposits, plus the apology credit. The customer support team handled it well — I'm proud of how Renee's team rallied.

I should feel better than I do.

## What's eating me

I knew the Sidekiq architecture was wrong. I knew it in November. I had budget to fix it in February. I prioritized investing scoping instead. That trade-off was wrong and the consequence landed on 2,138 customers.

The board took my explanation well. Aleks was supportive. Marcus didn't blame me. The team rallied. None of that changes the fact that I made the call.

The honest version of the postmortem is: I was making infrastructure trade-offs based on the wrong mental model of when those bills come due. I thought we had until 200k MAU before that pipeline would fail. We failed at 120k. The model was wrong because I hadn't stress-tested it under realistic Sunday peak. I looked at average load, not peak load.

## What this tells me about how I'm running engineering

I'm making decisions on intuition. Sometimes intuition is right and feels right. Sometimes intuition is wrong and still feels right until it isn't. The Sidekiq call felt right in February. It was wrong then. I didn't have a process to catch it.

What I should do: when an architectural decision is "we can live with this for now," I should write down what "for now" means in concrete metrics. What's the trigger to revisit? When I don't do that, the decision lingers past its real expiration.

If I'd written that down in November, I would have caught the expiration. The act of writing it down would have forced rigor.

## What I'm going to do differently

- Every "we can live with this" gets a written trigger metric
- Trigger metrics get reviewed quarterly (not "as needed" — actually quarterly)
- I commit to revisiting one major architectural decision per quarter
- If I miss a trigger, that's a process failure I track

## What I'm not going to do

Beat myself up endlessly. I've been doing that for three days. It doesn't help. The team needs me sharp, not drowning in self-criticism.

The right response is the architecture rebuild. The right response is the process change. The wrong response is performative guilt.

## What I'm telling myself

You made a call with the information you had. The information wasn't complete. You're going to make more calls with incomplete information for the rest of your career. The skill isn't avoiding bad calls. The skill is recognizing them faster, being honest about them, and not making the same call twice.

You learned something this week. The team learned something. The architecture is going to be better. Customers got their money. Series B isn't dead.

Go to sleep, Maya.

## Tomorrow

- 7 AM: gym
- 9 AM: Marcus and I walk through the ADR-024 implementation plan in detail
- 11 AM: customer support follow-up meeting with Renee
- 1 PM: Aleks check-in
- 3 PM: take a walk

This isn't the worst week. It's a week I'll learn from. That's a thing.

## A thing my sister said

I called my sister last night. She's a doctor in Boston. She listened to me explain the incident, then said: "So nobody died and nobody lost their job. You're going to be fine."

She's right. Engineering bugs aren't medical errors. The proportions matter. I'm catastrophizing. The customers got their money. The team is intact. The company is intact.

Get some perspective. Go to sleep.
