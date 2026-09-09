# Build vs Buy Framework

**Author:** Maya
**Status:** Decision-making framework, used across the team
**Date:** 2026-03-30

## Why this exists

We've made the build/buy call enough times that I want a written framework. New engineers ask. Old engineers default to "build." I want to be explicit about when we go which way.

## The default

**Buy** until proven we should build.

This is the opposite of what most engineers want to hear. Build is more fun. Build feels like ownership. Build is what we got into engineering to do.

Build is also where startups die. Building a custom version of something a vendor solves better takes engineering hours that should be on the product.

## When to buy

You should choose buy if any of these are true:

- **There's a well-funded vendor solving exactly this problem.** Their R&D budget exceeds your team. You can't catch up.
- **The capability is necessary but not differentiating.** Authentication, observability, payments processing, KYC. All necessary. None differentiating. Buy them.
- **Regulatory complexity is high.** Identity proofing, card issuing, brokerage. The compliance moat is the vendor's, not yours.
- **You can swap vendors later.** Vendor lock-in is a real risk but with abstraction layers, switching cost is manageable. Optionality matters more than incumbent loyalty.
- **The vendor's pricing scales reasonably.** Pricing that punishes growth is a buy red flag. Run the math at projected scale before committing.

## When to build

You should consider building if all of these are true:

- **The capability is core to your product differentiation.** Stencil's auto-savings algorithm. ToE's matching algorithm. Things customers are paying for.
- **No vendor exists that solves your specific shape of the problem.** Not "no vendor is good enough" — "no vendor exists." Different bar.
- **The maintenance cost is something you can sustain.** Building is the easy part. Maintaining over 5 years is the hard part. Will you?
- **Building doesn't take you away from something more important.** Opportunity cost is real.

## The "build a thin layer over buy" pattern

This is what we usually do. Buy the underlying capability. Build a thin abstraction that:
- Adds vendor-independence (you can swap)
- Adds product-specific semantics (you can express your domain)
- Adds observability (you control logging, errors, metrics)

This pattern shows up in:
- KYC: buying Alloy, thin wrapper for our internal usage
- Push notifications: buying Branch + Customer.io, abstraction in front of both
- Card issuing: buying Lithic, internal API in front of it
- Brokerage: buying DriveWealth, dedicated service in front of it

In each case, we own the seam. Vendor owns the heavy lifting.

## When the framework fails

The framework gets noisy when:
- The vendor doesn't quite fit (build a missing piece around their offering, or wait?)
- The vendor's pricing flips on us (renegotiate vs. switch)
- A capability that wasn't core becomes core (we underestimated)

In those cases, escalate the call to me or to Aleks. Don't make a unilateral build decision without explicit conversation.

## What I've seen go wrong

- **Building because "we can do it better."** Usually you can. Doesn't mean you should.
- **Building because the vendor is annoying.** Vendor frustration is real but rarely worth the build cost.
- **Buying because "everyone uses it."** Trust the framework over the social proof. Some "everyone uses it" tools are bad fits for our specific case.
- **Buying without abstracting.** Direct vendor calls scattered through the code. Becomes a nightmare when you need to switch.

## Recent calls and their reasoning

- **Alloy over Persona for KYC** — buy decision, switched vendors because pricing punished growth
- **Lithic for card issuing** — buy decision, no realistic build option at our stage
- **DriveWealth for brokerage** — buy decision, regulatory complexity is enormous
- **In-house ACH pipeline** — build decision, money movement is core, vendors don't fit our shape
- **In-house auto-savings algorithm** — build decision, this is our product
- **In-house feature serving (ADR-030)** — build decision, but using Postgres (we already buy)
- **Branch + Customer.io for notifications** — buy decision, two vendors because needs differ

## How I want the team to use this

Before any "should we build X" conversation, run through the framework. If the answer points to buy, that's the conversation we're having. If it points to build, we're having a longer conversation about whether the build is really worth it.

## Personal note

I came up at Stripe where "build it ourselves" was often the right answer. Stripe had the team to support it. We don't. Different stage, different defaults. I have to remind myself of this regularly.
