# Series B Pitch — Engineering Section Draft

**Author:** Maya
**Status:** Draft 3, shared with Aleks for narrative review
**Date:** 2026-05-19

## Section purpose

This is the engineering/technology slide(s) in the Series B deck. The audience: top-tier consumer fintech investors. The narrative: we've built infrastructure that lets us scale to 1M users without re-architecting, we have the team to extend it, and our compliance posture is investor-grade.

## What goes on the slide(s)

### Slide: "How we built it"

Visual: simplified architecture diagram. Three layers.
- Mobile (iOS, Android, native)
- Backend services (monolith + critical pipelines as services)
- Money movement layer (ACH, card, brokerage)

One line per layer explaining the choice.

Talking points:
- "We chose Postgres as system of record, not because we're naive, but because we're focused"
- "The money movement layer is its own thing because money movement is its own problem"
- "We treat compliance as an engineering function, not a paperwork function"

### Slide: "Scale headroom"

Visual: simple chart. Current scale, projected scale, infrastructure capacity.

Talking points:
- 120k MAU today, infrastructure tested to 800k MAU
- Specific bottlenecks identified and have plans
- "We are not the company that will need to rewrite at 500k. We've done the work to delay that"

Need to be careful here. Don't oversell. Don't make claims I can't defend if a technical due diligence rep digs in.

### Slide: "The team"

Visual: photos + names + prior companies of the eng leadership team.

Talking points:
- Marcus (former AWS), Nadia (former Square), Devon (former Robinhood), Lin (former Cash App)
- Three years working together (most of them)
- VPE search starting post-close

### Slide: "Compliance as an asset"

Visual: timeline of compliance milestones already achieved + roadmap.

Talking points:
- BSA/AML program in place since Series A
- SOC2 Type 1 closed, Type 2 in progress
- Sponsor bank relationship is mature (Pillar Bank since 2024)
- DriveWealth integration in flight for investing
- "We're not retrofitting compliance. It's in the architecture"

This slide matters. Several Series B firms have publicly said they're prioritizing fintechs with strong compliance discipline after the 2024-2025 BaaS shakeout.

## What I'm NOT putting on the slides

- Specific tech stack details. Investors don't care about Go vs. Node.
- Headcount plans. Save for the diligence call.
- Vendor names (mostly). Lithic, Plaid, Pillar Bank can come up in Q&A.
- Code metrics, LOC, etc. Vanity.

## How Aleks and I split the narrative

He owns: market opportunity, business model, growth metrics, vision.
I own: how we built it, why it scales, why the team can build the rest.

Engineering should not dominate the deck. Two slides max. The story is the company, not the infrastructure.

## Technical due diligence prep

Once we have a term sheet, TDD reps will dig in. What I need to have ready:

- Architecture deep-dive doc (15-20 pages)
- Security questionnaire (boilerplate)
- Compliance binder (already exists in OneTrust)
- Incident history (April write-up + the few smaller ones)
- Hiring plan + comp bands
- Vendor risk assessments (already mostly done)

I want this ready before we send the deck. Diligence rooms that come together quickly signal a well-run company.

## What's risky in the engineering narrative

- **The April incident.** Investors will ask. The answer is: here's what happened, here's the fix, here's how we know it won't repeat. The fix is real. Don't be defensive.
- **The monolith.** Some investors are allergic to "monolith." The answer is: we have a monolith for the parts where coupling is cheap, and we've carved out services where coupling is dangerous. The pattern is intentional.
- **No VPE yet.** Will come up. Answer: search starts post-close. The TLs are running their pods well.

## What I want investors to walk away believing

- The team has shipped a working consumer fintech product without a compliance incident
- The infrastructure can scale to Series C without a re-architecture
- The leadership team is honest about what works and what doesn't
- Investing into Stencil at Series B is funding execution, not science projects

## Open question

Do we put numbers in the deck (LOC, infrastructure cost as % revenue, etc.)? Aleks wants some. I'm cautious. Numbers without context invite the wrong questions.
