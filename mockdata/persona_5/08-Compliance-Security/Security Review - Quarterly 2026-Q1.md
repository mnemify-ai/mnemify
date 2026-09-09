# Security Review — Q1 2026

**Author:** Maya
**Status:** Closed; document for record
**Date:** 2026-04-10

## What this review covered

Quarterly security review. Internal. Looks at:
- Recent security events
- Vulnerability scan results
- Access controls and audit
- Pen test status
- SOC2 progress
- Vendor security posture

## Recent security events

### One minor incident (Q1)

A former contract designer's GitHub access wasn't revoked for 11 days after their engagement ended. Discovered during a routine access review. No evidence of access during that window. Process gap, not exploitation.

Remediation: automated offboarding workflow for contractors. Linked to contract end date in our HR system. Implemented before end of Q1.

### Zero customer-facing security incidents

No reportable security events affecting customers in Q1. Zero data breaches, zero fraud incidents involving our systems (some user-side phishing, not us).

## Vulnerability scans

Running Snyk on dependencies, Aikido for repo-wide scanning, AWS GuardDuty for infrastructure.

Q1 findings:
- 4 high-severity dependency CVEs identified and patched
- 0 critical findings
- 12 medium-severity findings, all triaged (8 patched, 4 accepted with mitigation)
- 47 low-severity findings (typical noise level)

Trend: stable. No spikes.

## Access controls

### Audit performed in March

- All employee access reviewed
- Findings: 3 stale access tokens (former contractors), 1 over-permissive IAM role
- All remediated within 7 days
- Process: implementing automated quarterly access review for all systems

### Production access

- Engineers with direct production database access: 4 (down from 7)
- Production deploy permissions: gated through CI/CD, only 3 humans can bypass
- Customer data access (PII): only 2 engineers + compliance team

This is tight. I want to keep it tight as the team grows.

## Pen test status

Q1 pen test (external firm) completed February. Findings:

- 1 high-severity (now fixed): rate limiting bypass on one API endpoint that could enable enumeration
- 4 medium-severity (3 fixed, 1 accepted with compensating control)
- 9 low-severity (all noted for tracking)

Re-test scheduled for Q3 with focus on investing feature (post-launch).

## SOC2 progress

- SOC2 Type 1: completed Q4 2025
- SOC2 Type 2: window open, audit in Q3 2026
- Evidence collection: in progress, on track
- Outside auditor engaged, all systems green

## Vendor security posture

Quarterly check on critical vendors. All have:
- Current SOC2 reports
- Acceptable security questionnaire responses
- DPA/BAA in place where applicable

One concern: a smaller vendor (analytics tool) hasn't refreshed their SOC2 in 14 months. Either get a fresh report or replace. Action item.

## What I'm watching for Q2

- Investing feature launch will introduce new attack surface (brokerage integration, position data)
- Card issuing planning will introduce yet another (Lithic integration, card data, fraud monitoring)
- BSA/AML audit may surface security-adjacent findings
- Series B prep means more eyes on our security posture from outside

## What I'm investing in this year

- Automated offboarding workflow (done Q1)
- Quarterly access reviews (in process)
- Better dependency monitoring (Snyk Pro upgrade)
- Security champion program — one engineer per pod takes on security ownership in addition to their regular role. Compensated.
- Tabletop exercises — quarterly drills on incident response. Q2 starting next month.

## What I'm NOT doing

- **Building a security team yet.** Too early. Spread security across engineering culture, hire when 30+ engineers.
- **Buying every security tool on the market.** Vendor proliferation is a risk in itself.
- **Pretending security is a separate concern from engineering.** It isn't.

## Personal note

Security feels manageable right now. We're small enough that everyone knows how systems work. As we scale that changes. The framework I'm building this year is the one that has to survive 3x growth.
