# HCT-306: Privacy Status, Authorization View, and Household Dashboard

- Issue: [#62](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/62)
- Requirements: FR-01, FR-09, NFR-02, NFR-07
- Status: Frontend implementation pending merge
- Owner: Yan Yuxin
- Reviewer: Assigned by the frontend lead
- Risk: R2; the dashboard must not infer or aggregate data outside the API-authorized scope
- Allowed changes: `src/web/src/`, focused frontend tests, and this Story

## Scope

The dashboard uses the shared API client for the currently authorized household and member:

- household/member scope and authorization view;
- member timeline and projection status;
- HCT-307 desensitized risk summary;
- capability response as the local/dependency status signal.

The API currently has no read-only task or reminder summary endpoint. The dashboard explicitly shows that dependency as unavailable rather than creating local task data or inferring care actions.

## Given / When / Then

- Given an identity selects an API-visible household and member; When the dashboard loads; Then the first view identifies the member, identity, purpose, visible scope, local API status, event projection, and desensitized risk counts.
- Given a member timeline is available; When recent activity renders; Then it shows only event type, confirmation state, and timestamp, never event payload or evidence content.
- Given a risk signal is available; When the dashboard renders; Then it reuses the API-filtered HCT-307 summary and evidence card.
- Given a dependency is offline, unavailable, revoked, or unauthorized; When a dashboard request fails; Then the relevant area displays an unavailable state and does not infer old, hidden, or aggregate data.
- Given the task/reminder read API is absent; When the dashboard renders; Then it clearly states that the summary is unavailable and offers no fabricated plan action.

## Verification

- `npm.cmd run test:web`: API client contracts and risk/authorization view behavior.
- `npm.cmd run check:web`: TypeScript type check.
- `npm.cmd run build:web`: production build.
- `git diff --check`: whitespace validation.

## Privacy and Rollback

- The backend is authoritative for household/member authorization, revocation, timeline filtering, and risk desensitization.
- The UI does not connect to databases, rules engines, models, or weather services directly.
- Rollback removes the dashboard presentation and timeline client helper only; it does not change backend facts, authorizations, risk results, or audit records.
