# HCT-306: Privacy Status, Authorization View, and Household Dashboard

- Issue: [#62](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/62)
- Requirements: FR-01, FR-09, NFR-02, NFR-07
- Status: Dashboard summary enhancement pending merge
- Owner: Yan Yuxin
- Reviewer: Assigned by the frontend lead
- Risk: R2; the dashboard must not infer or aggregate data outside the API-authorized scope
- Allowed changes: `src/web/src/`, focused frontend tests, and this Story

## Scope

The dashboard uses the shared API client for the currently authorized household and member:

- household/member scope and authorization view;
- member timeline and projection status;
- HCT-307 desensitized risk summary;
- capability response as the local/dependency status signal;
- read-only plan workbench for today's or nearest confirmed medication plans;
- review-task candidates and accessible member-state summaries.

The dashboard reuses the existing read-only plan workbench and review-task APIs. If a dependency is unavailable, its card remains explicit about the degraded state rather than creating local task data or inferring care actions.

## Home summary extension

The first screen now groups the existing weather action card with four household-care summaries:

- today's weather and environment action cards;
- pending review, unacknowledged risk, and escalated medication items;
- today's confirmed medication plans, falling back to the nearest confirmed plans when no plan is scheduled today;
- recent medication-identification candidates, explicitly marked as candidates until human confirmation;
- member state availability and event counts without rendering hidden health payloads.

## Given / When / Then

- Given an identity selects an API-visible household and member; When the dashboard loads; Then the first view identifies the member, identity, purpose, visible scope, local API status, event projection, and desensitized risk counts.
- Given a member timeline is available; When recent activity renders; Then it shows only event type, confirmation state, and timestamp, never event payload or evidence content.
- Given a risk signal is available; When the dashboard renders; Then it reuses the API-filtered HCT-307 summary and evidence card.
- Given a dependency is offline, unavailable, revoked, or unauthorized; When a dashboard request fails; Then the relevant area displays an unavailable state and does not infer old, hidden, or aggregate data.
- Given a read-only plan workbench is available; When the dashboard renders; Then it shows the selected member's confirmed schedule and status without performing a medication action.
- Given a review task is available; When the dashboard renders; Then it shows the drug name only as an identification candidate and links to human review; it never treats the candidate as a confirmed fact.
- Given the dashboard is viewed on a narrow viewport; When the summary cards stack; Then the weather, pending items, plans, candidates, and member status remain accessible without horizontal overflow.

## Verification

- `npm.cmd run test:web`: API client contracts and risk/authorization view behavior.
- `npm.cmd run check:web`: TypeScript type check.
- `npm.cmd run build:web`: production build.
- `npm.cmd run test:e2e:web -- tests/browser/hct409-accessibility.spec.ts`: home summary, keyboard, responsive, and WCAG checks.
- `git diff --check`: whitespace validation.

## Privacy and Rollback

- The backend is authoritative for household/member authorization, revocation, timeline filtering, and risk desensitization.
- The UI does not connect to databases, rules engines, models, or weather services directly.
- Rollback removes the dashboard summary presentation and its read-only requests only; it does not change backend facts, plans, authorizations, review tasks, risk results, or audit records.
