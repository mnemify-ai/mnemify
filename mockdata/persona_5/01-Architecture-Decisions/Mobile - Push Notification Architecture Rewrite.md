# Mobile — Push Notification Architecture Rewrite

**Author:** Maya
**Status:** Approved (Nadia's project, my sign-off)
**Date:** 2026-04-21

## Context

Our current push notification system is held together with duct tape. We send to APNs and FCM directly from a Rails background job, batched on Sidekiq, with no retry handling, no delivery confirmation, no per-user rate limiting. When Kavi's growth team wants to send a campaign, they ping Marcus who runs it manually. Nadia raised this. She's right.

The growth team wants to do behavioral push notifications ("you haven't deposited in 7 days") which means we'd be sending 100k+ pushes per campaign. We can't do that safely today.

## Decision

Move to a dedicated push notification service (Customer.io for marketing, Branch for transactional). Build a thin in-house abstraction layer that lets product and growth teams trigger notifications without engineering involvement.

## Why two providers, not one

- **Transactional** (account events, security alerts, deposit confirmations): time-sensitive, regulatory-adjacent, must deliver. Branch is built for this. We pay for reliability.
- **Marketing** (re-engagement, feature announcements, campaigns): high volume, batch-friendly, A/B test friendly. Customer.io is built for this. Cheaper per-message at scale.

Trying to use one platform for both is a recipe for either expensive transactional or unreliable marketing. Pick the right tool per job.

## The abstraction layer

Thin Go service in front of both providers. Application code calls `notification.send(user_id, template_key, params)`. The service decides:
- Which provider (based on template_key)
- Rate limiting per user (max 3 marketing per day, no limit on transactional)
- Delivery tracking
- A/B variant routing
- Localization

Marcus's team builds it. ~6 weeks of work.

## Rate limiting deserves its own callout

Today, nothing prevents Kavi from sending a user 10 notifications in an hour. That's a fast track to uninstalls. The abstraction layer enforces:
- Max 3 marketing pushes per user per day
- Max 1 transactional push per event type per user per minute (debounce)
- Quiet hours: 9 PM – 7 AM in user's timezone (transactional bypasses this)
- Per-user opt-out respected globally

If the growth team wants to push these limits, they argue with me, not the engineer trying to add a feature.

## Why not just send via FCM/APNs directly

We already do that. The problems aren't solved by writing more code on the same architecture — they're solved by buying delivery reliability and growth tooling we don't want to build ourselves.

## Migration plan

- May–early June: build abstraction layer with provider stubs
- June: integrate Branch for transactional, migrate transactional flows
- July: integrate Customer.io for marketing, migrate marketing flows
- August: deprecate direct FCM/APNs code paths

## Risks

- **Delivery rate during migration.** Parallel paths during cutover. We measure delivery rate on both, switch only when new path matches or beats.
- **Cost.** Customer.io scales linearly with sends. At 100k campaigns we're looking at maybe $4-6k/month. Acceptable.
- **Vendor lock-in.** The abstraction layer is the mitigation. We can swap providers behind the abstraction with manageable work.

## What I want from this

Growth team self-serves notification campaigns. Transactional pushes never miss. Engineering touches the notification layer maybe 4 times a year instead of 4 times a month.

## What this isn't

Not a "real-time messaging platform." Not Intercom. Not a chat widget. Push notifications only. If anyone tries to expand scope, push back.
