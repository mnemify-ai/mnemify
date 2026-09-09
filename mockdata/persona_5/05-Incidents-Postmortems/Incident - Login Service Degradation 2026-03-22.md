# Incident — Login Service Degradation 2026-03-22

**Date:** 2026-03-22 (Saturday)
**Severity:** P1 (degraded, not down)
**Duration:** 2 hours 14 minutes
**Author:** Nadia, with Maya review

## What happened

For roughly 2 hours and 14 minutes on Saturday morning, login times spiked from a p95 of 800ms to 5-8 seconds for iOS users. Android and web were unaffected. About 18% of iOS users who attempted login during this window either gave up or saw the loading spinner for an uncomfortably long time.

No data loss. No money movement impact. User retention impact unclear.

## Timeline

- **March 22, 8:42 AM PT** — Synthetic monitoring alerts on iOS login latency
- **8:45 AM** — Nadia is paged (on-call)
- **8:52 AM** — Initial assessment: backend `/auth/session` endpoint is fine. iOS client is slow.
- **9:14 AM** — Identifies cause: new biometric re-prompt logic added in iOS 0.42.3 (released March 20) triggers a chained call to the device's Secure Enclave that's slow on older iPhones (iPhone XR and earlier)
- **9:30 AM** — Confirms: ~18% of iOS users are on iPhone XR or earlier. Matches degradation rate.
- **9:45 AM** — Options considered:
  - Rollback 0.42.3 (forces reinstall)
  - Hotfix that conditionally skips biometric re-prompt on older devices
  - Server-side feature flag the new behavior off
- **10:02 AM** — Decision: server-side flag off the biometric re-prompt for all users immediately, ship a 0.42.4 hotfix early next week
- **10:08 AM** — Flag flipped. Login latency returns to normal within ~5 minutes (cache propagation)
- **10:56 AM** — Resolution confirmed via synthetic monitoring

## Root cause

The biometric re-prompt logic in 0.42.3 was added to satisfy a security review recommendation (re-prompt for biometric every 30 days). The implementation chained an unnecessary Secure Enclave call on older devices. The performance characteristics of Secure Enclave on iPhone XR-era hardware were not tested.

## Contributing factors

- **Limited device coverage in testing.** Our iOS test matrix doesn't include older devices. Nadia's been asking for budget for a device farm; this incident makes the case.
- **Security review recommendation implemented without performance testing.** A security improvement caused a usability regression. We should have anticipated.
- **Synthetic monitoring caught it.** Good. But it caught it after 30 minutes of customer impact. Faster detection desired.

## What we did well

- Nadia identified root cause within 30 minutes
- Server-side flag let us mitigate without forcing reinstall
- Communication to customer support team was prompt
- 0.42.4 hotfix shipped within 4 business days

## What we did poorly

- Older-device testing gap was known and unprioritized
- Security improvement was rolled out without measuring impact
- No automated rollback trigger when latency spikes — Nadia had to manually decide and execute

## Action items

- **[DONE] Server-side flag in place** — done March 22
- **[DONE] 0.42.4 hotfix** — shipped March 25
- **[OPEN] Older-device test coverage** — Nadia owns; physical device set ordered, integrating into CI
- **[OPEN] Performance test before security-related releases** — adding to the release checklist
- **[OPEN] Automated mitigation triggers** — when iOS latency exceeds threshold, auto-disable feature flag. Q3 work.

## Lessons

1. **Security and UX trade-offs need explicit performance budgets.** "Improve security" without a "without degrading X" constraint invites incidents like this.
2. **Older devices aren't optional in our market.** Our user base skews not-latest-iPhone. We have to test against what users actually run.
3. **Server-side feature flags for client code paid for themselves on this incident.** Worth the engineering cost.

## Severity classification debate

Internal debate: was this really P1 or should it have been P2? My take: P1. 18% of iOS users degraded for 2+ hours is a real customer impact, even if no money was lost. Calibration matters; downgrading this to P2 sets a precedent.

## Personal note

Nadia handled this very well solo. Her instinct to ship a server-side mitigation before a hotfix was right. This is the kind of judgment that gets engineers promoted.
