# Engineering Org Design — Post Series B

**Author:** Maya
**Status:** Planning, not yet shared with team
**Date:** 2026-05-12

## Context

We close Series B in Q4 (planned). I want to be ready to scale engineering from 14 to 25 within 6 months of close. That doesn't happen if I'm designing the org during fundraising. Drafting now.

## Current state (May 2026)

- 14 engineers, 1 designer, 1 PM, 1 me
- Three tech leads (Marcus, Nadia, Devon) each running a small pod
- Everyone reports to me, including Lin (designer) and Renee (product head)
- Eng skip-levels: zero. Every engineer is at most one hop from me.

## What's working

- Velocity. We ship fast.
- Pod ownership is clear. Marcus owns backend, Nadia owns mobile, Devon owns data/ML.
- I know every engineer by name and their last 3 PRs.
- Hiring bar is consistent because I'm in every loop.

## What's breaking

- I'm the bottleneck on 1:1s. 14 people, monthly each, plus the tech leads weekly. That's ~30 hours/month in 1:1s alone.
- Architecture decisions: I'm involved in too many. ADRs sit waiting for me.
- Hiring: I'm in every loop. Doesn't scale.
- Onboarding: new engineers come to me for everything because there's no middle layer.

The team has been telling me this politely for months.

## Post-Series B target

- ~25 engineers, organized in 3-4 pods
- Each pod has a tech lead (already in place) and a senior engineer who can run sprint planning
- Hire a VP Engineering between me and the tech leads
- I keep direct reports: VPE, Devon (data is special enough to stay close), Lin, Renee
- Tech leads report to VPE

## Why a VP Engineering, not more managers

I considered both. A few VP Engineering vs. multiple line-manager arguments:

- **Strategic alignment.** A VPE owns "how engineering operates" — process, hiring, growth tracks. Line managers don't.
- **Hiring leverage.** A great VPE brings their network. We need senior hires.
- **Skip-level health.** With a VPE, I get to skip-level into pods regularly without being in every conversation.
- **My time back.** I get hours per week back for architecture, board, and strategic hiring.

Line managers will come later (2027) when pods are 6+ engineers.

## VP Engineering profile

I've been thinking about what I want:

- Series A/B fintech experience. Won't take someone whose only background is bigco.
- IC engineer before manager. I won't hire a "career manager" who hasn't shipped code.
- Has built and led teams 10-30 engineers. We don't need someone who's run a 200-person org.
- Strong on hiring. They'll close the hiring problem.
- Direct communicator. Has to match my style or this won't work.

Search: not yet. Will kick off after Series B close so the comp story is solid.

## Pod restructuring

Post-VPE, pods will be:

**Money Movement Pod** (Marcus + 5 engineers)
- ACH, card transactions, brokerage integration
- The pod with the highest blast-radius
- Marcus stays as TL

**Mobile Pod** (Nadia + 5 engineers)
- iOS, Android, mobile-side state
- Nadia stays as TL
- Hire a second senior iOS engineer

**Data + ML Pod** (Devon + 3 engineers)
- Smaller but still its own pod
- Devon TL
- Direct to me, not VPE — data is too central to delegate fully

**Infra + Platform Pod** (new — needs a TL hire)
- Currently distributed across pods
- Need someone owning AWS, observability, CI/CD, security infra
- This is the most important hire of the year

## Hiring sequence

1. VPE (Q4 2026, post Series B)
2. Infra/Platform TL (Q4 2026)
3. Backend senior x2 (Q1 2027)
4. Mobile senior iOS (Q1 2027)
5. Data Scientist (Q1 2027)
6. Backend mid-level x3 (Q2 2027)

## Risks

- **VPE doesn't fit.** Worst-case scenario. Founder/VPE chemistry takes 90 days to surface. I'm budgeting that risk.
- **Pod TLs feel demoted.** They're not — they keep their pods. But I need to be explicit about that.
- **Hiring market.** Tight. Plans are aggressive. Adjust if needed.

## What I'm telling myself

The instinct to keep everyone reporting to me is wrong. I have to delegate or this scales badly. The VPE hire is the unlock for everything else.
