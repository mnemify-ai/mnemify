# Code Review Standards

**Author:** Maya
**Status:** Living doc, in #eng-handbook
**Date:** 2026-03-08

## Why this doc

Code review at Stencil has been inconsistent. Some PRs get rigorous review, some get rubber-stamped. We're a money-movement company. The cost of an under-reviewed PR can be six figures.

This doc sets a baseline. It is not a checklist. It's a frame.

## What every PR gets

- One reviewer minimum
- Reviewer is in the same pod or has context on the area
- Approval from at least one senior engineer (E3+) or a TL

## What money-movement PRs get

- Two reviewers
- One must be a TL
- Tests for the new code path are required, not optional
- Rollout plan in the PR description (feature flag? Backfill? Migration?)

## What touches user financial data gets

- Two reviewers, one of whom is a TL
- Explicit consideration of: idempotency, error handling, audit logging, PII exposure
- Notes on what happens when the operation partially fails

## What architecture changes get

- ADR before the PR
- Two reviewers including the TL of the affected pod
- Discussion in #eng-architecture before merge

## What I expect from a reviewer

- Read the entire diff. Not just the parts that catch your eye.
- Ask "what's the failure mode?" for every non-trivial change.
- If something is unclear, ask. Don't approve unclear code.
- If something is wrong, say so. Don't soften feedback into ambiguity.
- Approve when you'd be comfortable owning the code yourself.

## What I expect from an author

- PR description is meaningful. Not "fixes bug." What broke, what changed, why this way.
- Self-review your diff before requesting review. Catch the dumb stuff yourself.
- Engage with feedback. Don't dismiss it.
- If the reviewer is wrong, push back with reasons.
- Don't merge until concerns are addressed, not just acknowledged.

## What kills code review at startups

- **Drive-by approval.** "Lgtm" on PRs the reviewer didn't read.
- **Author pressure.** "I need to merge this today." Sometimes legitimate, often not.
- **Reviewer drift.** Same person approves everything from a teammate.
- **Bikeshedding.** Reviewer spends 50 comments on a variable name, misses the bug.

If you see any of these, name them. Including upward.

## Specific patterns we encourage

- **Small PRs.** Easier to review well. Most PRs should be < 400 lines of net change.
- **Linked context.** If a PR implements a decision from an ADR or a customer issue, link it.
- **Honest test coverage.** "Tests pass" isn't enough. Tests test what we care about.
- **Rollback considerations.** What happens if we revert this? If unclear, fix the PR.

## Specific anti-patterns we don't tolerate

- **"While I'm here" refactors.** Separate PR. Reviewer can't review two changes at once.
- **Hidden config changes.** Production config changes in code PRs without callout.
- **Magic numbers without comments.** What is `0.025`? Comment or name it.
- **Long-living branches.** If a branch is > 2 weeks old, either merge it or kill it.

## On AI-assisted code

- AI-generated code is fine. You own it.
- If the AI did something you don't understand, don't merge it. Understand first.
- Comment AI-generated complex logic with the same rigor as human-written. Reviewers shouldn't have to guess.

## On urgent changes

- Sometimes we need to ship fast. Acceptable.
- "Fast" still means a reviewer reads the diff.
- Post-merge review (within 24h) is acceptable in true emergencies, not for "I want to ship before standup."

## What I do as CTO

- I review PRs in money-movement and architecture areas regularly. Less than I should.
- I do not approve drive-by. If I'm in a PR, I read it.
- I escalate review-quality issues in 1:1s with TLs.

## Review cadence

This doc gets revised when we hit on-the-ground problems that this doc doesn't cover. If the team finds a gap, file a PR against this doc.

## Open question

We've been kicking around requiring "code owners" approval for critical paths via Github's CODEOWNERS file. I'm in favor. Setting it up requires care so people don't get pinged on every PR. Marcus is sketching.
