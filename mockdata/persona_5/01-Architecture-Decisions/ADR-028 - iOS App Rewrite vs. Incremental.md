# ADR-028 — iOS App Rewrite vs. Incremental

**Author:** Maya
**Status:** Accepted (with caveats)
**Date:** 2026-05-15

## Context

Nadia walked into my office on Tuesday and said the iOS codebase is going to bite us. She's not wrong. The app is 4 years old, started in Objective-C with Swift bridges, half-converted to SwiftUI mid-2024 by a contractor who left, and the navigation layer is three different architectures stitched together. New features take twice as long as they should. The investing module that ships in Q3 will be painful unless we fix this.

The question is: rewrite, or incremental refactor?

## Decision

**Incremental refactor**, with a hard timeline. Six months to clean architecture, no full rewrite.

## Why not full rewrite

Three reasons.

First, Joel Spolsky was right twenty years ago and he's still right. The most catastrophic mistake an early-stage company can make is a full rewrite. The current app works. It generates revenue. Throwing it away to build a "better" version that takes 9 months and ships with new bugs is how startups die.

Second, we have the investing feature to ship in Q3. A rewrite blocks that. Incremental doesn't.

Third, Nadia's team is 4 people. A rewrite needs 6+ engineers running full-time. We don't have them and we're not hiring them.

## Why incremental is the right call

The codebase isn't actually broken everywhere. The auth flow is fine. The home screen rendering is fine. The Plaid integration is fine. What's broken is the navigation layer, the state management, and three specific old screens (account, settings, deposits).

We carve out those three. We replace them with clean SwiftUI implementations using a unified state pattern (we're picking The Composable Architecture; Nadia's team likes it). We use feature flags to ship the new screens to a percentage of users. When confidence is high, we delete the old code paths.

For the navigation layer specifically — we adopt a coordinator pattern and migrate screen-by-screen. Six months feels generous.

## What this looks like in practice

- May–June: Settings screen rewrite. Lowest-risk. Validates the pattern.
- July: Account screen rewrite. Touches more state.
- August: Deposits screen rewrite. Highest-risk. Integrated with ACH pipeline that's also in flight.
- September: Navigation layer migration.
- October: Cleanup and old-code deletion.

Investing feature builds on the new architecture starting July. Nadia and Devon paired.

## Risks

- **We're doing this concurrent with investing feature development.** Real concurrency risk. Mitigation: separate engineers, separate PRs, weekly sync between the two threads.
- **Refactor scope creeps.** Inevitable. I'm holding the line on "three screens + nav layer." No "while we're here" additions without my sign-off.
- **The old code lingers.** Possible. The October cleanup task is non-negotiable. If we slip past then, we're carrying the old code into 2027 and that's worse.

## What I told Nadia

She wanted permission to do a rewrite. I said no but I'm giving her something better — explicit authority over the architecture choice (TCA), explicit cover from product pressure on the refactor scope, and explicit ownership of the October cleanup. She got more than she asked for in a different shape.

## What I'm watching for

Mobile engineers love to rewrite things. It's the most fun part of the job. I'll be checking PRs for scope creep weekly. If I see "while we're here" comments, I'm pushing back hard.

## What I'm not doing

I'm not learning Swift well enough to code-review this myself. Nadia owns the technical judgment. I own the timeline and scope.
