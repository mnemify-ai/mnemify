# Board Update — May 2026

**To:** Stencil Board
**From:** Aleks (CEO), Maya (CTO)
**Date:** 2026-05-25
**Last update:** April board meeting + April monthly

## TL;DR

Strong quarter. MAU up 22% QoQ. Subscription ARR at $4.1M, on track for $5.5M by end of Q3. Investing feature on schedule for Q3 launch. April ACH incident resolved, root cause fixed, infrastructure rebuild underway. Series B prep beginning, target close Q4.

## Metrics

- **MAU:** 120k (up from 98k end of Q1)
- **MTU (monthly transacting):** 78k (65%, up from 61%)
- **Subscription ARR:** $4.1M (up from $3.4M)
- **CAC (blended):** $24 (down from $31)
- **LTV/CAC:** 4.2 (up from 3.6)
- **Net retention:** 108%
- **Burn:** $480k/month (versus $520k plan)
- **Runway:** 19 months at current burn, before Series B

The CAC drop is real and we're cautious about reading too much into it — Kavi's growth team made meaningful improvements to onboarding conversion. Holding for one more month before declaring trend.

## Product update (Maya)

### Shipped this quarter

- Goals-based savings (multi-bucket) — 38% adoption among MTU
- Round-up multiplier (2x, 5x) — 22% adoption
- Bank linking via Plaid Layer (new) — reduced abandonment by 12pp
- Notification system rebuild (foundation for behavioral campaigns)

### Shipping this quarter (Q3)

- **Investing feature** — ETF investing through DriveWealth, Q3 launch. On track.
- **Card issuing** — Lithic partnership selected. Decision deck attached. Building Q3, soft launch Q4.
- **KYC vendor migration** — Persona → Alloy. Reduces COGS by $120k/year. Migration starts June.
- **Mobile architecture refactor** — incremental, doesn't block features.

## Engineering & infrastructure (Maya)

### April incident summary

ACH file processing failure on April 6 caused 2k users to experience 3-day delays on auto-deposits. Root cause: Sidekiq worker stall under peak Sunday load. Customer comms went out within 4 hours. No regulatory exposure. Compensation issued ($25 credit per affected user, $50k total). Full postmortem published internally and shared with Pillar Bank.

Architectural response: ACH processing moves to a dedicated, durable pipeline (Go service + Postgres outbox + SQS FIFO). Phase 1 shadow mode live now. Cut-over planned for June. This eliminates the class of failure that caused the incident.

### Team

- 14 engineers + 1 designer + 1 PM
- 2 senior engineer hires closed (start dates June)
- VP Engineering search opens after Series B close
- No attrition this quarter

### Compliance & security

- BSA/AML audit scheduled June 8
- SOC2 Type 2 audit window open
- Pen test results from Q1 remediated
- KYC vendor migration improves our overall compliance posture

## Series B prep (Aleks + Maya)

- Targeting close in Q4. Q3 will be quiet on the company-news front to avoid signaling
- Pitch deck v0.4 reviewed with Bessemer (Lead, Series A); incorporated their feedback
- Targets:
  - $40M raise, $200M-$240M post-money
  - Lead: in conversation with two top-tier funds
  - Existing investors (Bessemer, Ribbit) will participate
- Diligence room being built now. Maya owns engineering/compliance sections.

## Asks of the board

1. **VPE introductions.** When we open the search post-Series B, board introductions to candidates accelerate the process by months. Start thinking now.
2. **Series B intro warmth.** Aleks will send a list of target funds in the next 2 weeks. Vouches required.
3. **Compensation philosophy review.** Bringing senior hires (VPE, infra TL) requires comp updates. Board call needed.

## Risks

- **Investing feature slips.** Series B narrative weakens. Mitigation: cut MVP scope further if Q3 ship is in doubt.
- **CAC creeps back up.** Conversion improvement may be ceiling-bound. Mitigation: Kavi has three more experiments queued.
- **Regulatory surprise.** Fintech regulatory landscape is volatile. Mitigation: counsel meetings monthly with our outside firm.

## Personal note from Maya

The April incident shook me. Two days where I doubted whether we'd built the company on solid ground. Looking back, the right things happened — we caught it fast, comms went out clean, the architectural response is right. But I want the board to know I take it seriously and the rebuilt pipeline is the most important engineering project of the year.

## Next board meeting

Scheduled for July 28. Pre-read 5 days prior. We'll have investing feature launch readiness assessment and Series B pre-marketing update.
