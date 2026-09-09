# Tech Lead Expectations

**Author:** Maya
**Status:** Written down so Marcus, Nadia, Devon all have the same framing
**Date:** 2026-02-20

## Context

I have three tech leads. They were natural picks: most senior in their pods, trusted by their teammates, took ownership early. None of them had the title "tech lead" anywhere before Stencil. We've been figuring it out together.

This doc is what I've come to expect from a TL at Stencil. They've all seen draft versions and pushed back where it didn't match their reality. This is the final shape.

## The TL role at our stage

A TL is:
- The most senior IC in their pod (not their manager)
- Responsible for technical direction
- Responsible for code quality bar
- Responsible for sprint scope and load balancing
- Responsible for being the person on the team junior engineers ask questions

A TL is NOT:
- A manager. Engineers report to me, not to TLs.
- A full-time architect. They still write code.
- A scrum master. We don't do that.

The role inversion from manager-track to IC-with-leadership is intentional. Engineers grow into TLs without giving up being engineers.

## What I expect on technical direction

- Owns the pod's architecture. ADRs originate from the TL (with input) or get written by a TL.
- Owns the dependencies between pods. They negotiate.
- Owns the technical debt list. They prioritize alongside features.
- Owns the bar for code review. Their pod's reviews represent their judgment.

## What I expect on code quality

- They write code. At least 40% of their time. Probably more.
- Their PRs set the standard.
- They are the bar-raiser on hard reviews — when an engineer is shipping something risky, the TL signs off.
- They can say "this needs to be redone" without flinching.

## What I expect on team operations

- Sprint scope is real. They negotiate it with Renee and me.
- If someone's overloaded, they redistribute or escalate.
- Status check-ins with me weekly (1:1) plus async update in #eng channel.
- If a teammate is struggling, they tell me. Early.

## What I expect on growth

- They mentor mid-level engineers.
- They participate in hiring loops.
- They give honest feedback in 1:1s with their pod members.
- They tell me what their pod members want (more responsibility? Less? Different work?)

## What I will not ask of a TL

- Performance reviews. That's me, for now. (VPE later.)
- Comp decisions. Same.
- Hiring decisions in isolation. We loop.
- Career-track decisions for their reports. Sensitive; me.

## How a TL fails (from what I've seen)

- **Drifting away from code.** Easy to become a meeting-attender. Hard to recover from.
- **Avoiding the hard PR review.** "Lgtm" on something they have concerns about. Trust evaporates.
- **Not surfacing team problems.** Engineers struggling, dynamics off, no signal to me. I find out when it's bad.
- **Overcommitting the pod.** Sprint scope blown, team frustrated, TL absorbing the stress alone.

## How a TL grows beyond TL

The career step from TL is either:
- **Staff engineer** (deeper IC) — broader architectural ownership across pods
- **Engineering manager** (people path) — own a pod's career growth, then a department

Both are valid. We talk about it in 1:1s. No rush.

## On Marcus, Nadia, Devon specifically

(Not sharing this externally; this is my private reflection on each.)

- **Marcus** is closest to staff engineer. He thinks in systems, architects naturally, and is uninterested in management. I'd promote him to staff in 6 months if we had the slot.
- **Nadia** could go either way. She's a strong manager in disguise; her pod adores her. I'd push her toward EM if she wants it. She hasn't said either way.
- **Devon** is the most IC-pure of the three. Wants to do ML, not lead. I keep his pod small intentionally.

The mistake would be pushing them all toward the same path. Different shapes, different growth.

## Open question

When we add a fourth pod (Infra/Platform), the TL for that pod is a hire, not a promotion. That changes the dynamic. I'll think about that when we get there.
