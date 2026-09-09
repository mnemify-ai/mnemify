# Near Miss — Plaid Token Refresh Bug

**Date discovered:** 2026-04-25
**Severity:** Near miss (would have been P0)
**Author:** Marcus, with Maya review

## What happened

While doing performance work on the bank-linking flow, Marcus discovered that our Plaid access token refresh logic had a subtle bug: in roughly 0.3% of cases, when a token was refreshed, the new token was written but the old token wasn't invalidated. The old token continued to work because Plaid's token store doesn't actively revoke. This meant that for a small percentage of users, multiple valid tokens existed simultaneously.

This had been live in production for approximately 4 months without surfacing.

## Why this is a near miss

The actual impact was zero. Both tokens worked. No security incident. No user reported anything. Plaid wasn't going to invalidate the old tokens.

But: if Plaid had ever decided to enforce one-token-per-user (which they reserve the right to do under our agreement), we would have had a sudden auth failure cascade across that 0.3% of users with no clear way to recover. That'd have been a customer-facing P0 within minutes.

This is the kind of bug that lives in your codebase silently and then bites during an unrelated change. The category we call "loaded gun" bugs.

## How Marcus found it

Performance work — he was tracing why some users had slower Plaid sync. Found that a small subset of users had multiple recent token refreshes in our audit logs. Investigated. Found the bug.

## Root cause

The token refresh code had a `try/finally` block that wrote the new token unconditionally but only invalidated the old token if the new token write succeeded. There was a third path — when the new token write succeeded but a downstream call to log the refresh failed — where the old token invalidation never ran.

The downstream logging failure was caused by an unrelated bug we'd fixed in February. After that fix, the third path stopped triggering. But the old leaked tokens from the prior 4 months were still in the database.

## Why this took so long to detect

- Both tokens worked. No customer impact.
- No metric tracked "users with multiple valid tokens." We had no signal.
- The bug only triggered when an unrelated bug also triggered. Compound rare conditions are hard to detect.

## What we did

- **Audit:** identified all users with multiple valid tokens (471 users out of ~120k)
- **Cleanup:** revoked the older tokens for those users
- **Code fix:** moved the invalidation to before the new token write (atomic database transaction). Old behavior: write-new, then invalidate-old. New behavior: invalidate-old, write-new, in one transaction.
- **Monitoring:** added a metric that alerts if any user has > 1 valid Plaid token
- **Plaid notification:** informed Plaid's account team out of caution. They were appreciative; no concern.

## Lessons

1. **Compound rare conditions are real.** A single rare condition won't surface in production at our scale. Two rare conditions combining is even rarer but doesn't go away. Our test coverage has to handle this class.

2. **"It works" isn't the same as "it's correct."** The system was producing the right user-facing outcome through a wrong internal state. Wrong internal state always finds a way to bite eventually.

3. **Audit logs saved us.** Without the token refresh history in our audit logs, we couldn't have detected or cleaned up the bad state. Audit logs are infrastructure, not paperwork.

4. **Performance investigations find correctness bugs.** Marcus wasn't looking for a security issue. Performance work is a useful side door to correctness review.

## Action items

- **[DONE] Code fix shipped** — 2026-04-26
- **[DONE] Audit + cleanup of 471 affected users** — 2026-04-27
- **[DONE] Monitoring alert added** — 2026-04-28
- **[OPEN] Review all token/credential management code for similar patterns** — Marcus's pod, due May 30
- **[OPEN] Add this to the "code review patterns to watch for" doc** — Marcus

## What I told the team

I sent a Slack note to engineering. Highlighted Marcus's discovery. Framed as: "this is what good engineering looks like — finding bugs that aren't causing pain yet." The cultural message matters: I want engineers digging for these.

## Personal note

If we'd shipped Series B six months ago, this would have been a "what's in your codebase" question I couldn't have answered. Marcus's instinct to dig saved us from a future explanation we didn't want to give.
