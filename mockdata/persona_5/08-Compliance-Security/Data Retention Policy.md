# Data Retention Policy

**Author:** Maya, with outside counsel
**Status:** Live; reviewed annually
**Date:** 2026-02-15 (last revised)

## What this policy is

How long we keep different categories of data, and why. Required for regulatory compliance, privacy law compliance, and operational sanity.

## Principles

- **Default minimum.** We keep the least data for the shortest time consistent with operations and regulation. Hoarding data is a liability.
- **Regulatory-driven where applicable.** BSA/AML, FINRA, IRS rules dictate retention for specific categories.
- **Customer rights respected.** Customers can request deletion (CCPA, etc.). We honor within regulatory constraints.

## Retention categories

### Tier 1: BSA/AML required data — 5+ years from termination

- KYC documents (identity proofing artifacts)
- Customer due diligence records
- Suspicious activity records (10 years for SAR-related)
- Transaction monitoring alerts

These are non-negotiable. BSA requires it.

### Tier 2: FINRA/SEC required data — 6+ years (varies by record type)

- Brokerage account opening records
- Order and execution records
- Customer communications related to trading
- Tax documents (1099-B, etc.)

DriveWealth handles primary retention. We mirror some categories for customer access.

### Tier 3: Operational data — 3 years

- Transaction history
- Account balances over time
- Login history
- Customer support interactions
- Cash management records

Retained for customer service and operational analysis.

### Tier 4: Engineering data — 90 days to 1 year

- Application logs (90 days, longer if compliance-relevant)
- Error tracking (1 year)
- Performance metrics (1 year)
- Customer document hashes (5 years, but hash only, no content)

Specifically: we never log customer document content.

### Tier 5: Derived analytical data — Indefinite (with PII removal at 2 years)

- Aggregated metrics
- Cohort analyses
- Personalization model training data (PII removed after 2 years)

After 2 years, customer data in analytical stores is de-identified or removed.

## Customer-requested deletion

When a customer requests deletion:
- We delete what we can delete (operational and engineering data within Tier 3-5)
- We retain what we must retain (Tier 1-2 regulatory data)
- We explain clearly what is retained and why

The retention isn't punitive. It's regulatory.

## Hard delete vs. soft delete

- **Hard delete is the default.** Data marked for deletion is physically removed from primary stores.
- **Backups follow the same lifecycle.** Backups age out per category retention rules.
- **Snapshots created for compliance freeze are exceptions.** Documented.

## What we never retain

- Customer authentication credentials (passwords are hashed; we cannot recover them)
- Customer plaintext credit card numbers (never stored, only tokens)
- Customer SSN (stored encrypted, never displayed in logs)
- Biometric data (not collected by us — handled by mobile OS)

## Backup retention

- Daily backups: 30 days
- Weekly backups: 12 weeks
- Monthly backups: 12 months
- Annual backup: 7 years (compliance archive)

Annual backup is in cold storage, encrypted, separate from operational systems.

## Vendor data handling

Each vendor's contract specifies retention rules. We require:
- No retention beyond what's necessary for service
- Deletion on contract termination
- Right to verify deletion (audit clause)

If a vendor's terms don't meet this, we negotiate or move on.

## Process for retention enforcement

- Automated jobs delete expired data daily
- Quarterly audit confirms retention is enforced correctly
- Annual third-party review (part of SOC2)

## What happens when a regulator requests data

- Legal hold immediately stops automated deletion for affected data
- Records gathered per request scope
- Documented as part of regulatory response
- After resolution, normal retention resumes

We have a written legal hold procedure.

## Recent changes

- 2026-02: Reduced application log retention from 1 year to 90 days. Operational change; legal review confirmed compliant.
- 2025-12: Added biometric explicit exclusion clause after security review.
- 2025-08: Reduced customer support transcript retention from 5 years to 3 years.

Each change documented in our policy change log.

## What I review annually

- Are we still aligned with current regulation? (Yes, last reviewed January)
- Are we retaining anything we shouldn't be? (Quarterly audit catches this)
- Is the policy understood by the team? (Training in onboarding)

## Personal note

The instinct in tech is to keep everything "just in case." Wrong instinct for a financial services company. Every byte we retain is a byte that could be compromised. Discipline matters.
