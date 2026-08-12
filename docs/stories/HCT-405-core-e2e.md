# HCT-405: Core E2E Scenarios and Safe Degradation

- Issue: [#70](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/70)
- Requirements: FR-01 through FR-10; NFR-01, NFR-02, NFR-03, NFR-04, NFR-06, NFR-07
- Status: In progress. This Story does not claim final E2E acceptance.
- Owner: jin-123-zip
- Reviewer: Project lead or an independently assigned reviewer (R3; the owner cannot self-review)
- Risk: R3
- Dependencies: HCT-207, HCT-307, HCT-308, and HCT-403 are closed. Vision, RAG/LLM, and V2 release paths remain release blockers until their actual APIs and evidence are available.
- Allowed changes: `src/web/src/api/`, focused frontend tests, `tests/e2e/`, and this Story.

## Value and Scope

This increment creates a repeatable, synthetic-data E2E regression baseline for the APIs already on `master`. It exercises the owner and caregiver authorization boundary through event projection, risk evidence, plan actions, revocation, and cross-household denial.

It also adds frontend client methods for rule execution and plan confirmation, deferral, and skipping. The client keeps authorization, purpose, and idempotency metadata at the API boundary; it does not call databases, rules, models, or Ollama directly.

## Explicitly Out of Scope

- No mock visual result is presented as OCR, barcode, fusion, or manual-review completion.
- No RAG, LLM, medical-answer, V2 model, deletion propagation, or deployment capability is represented as passed.
- No real household data, images, weights, secrets, logs, or networked health content is used.

## Scenario Coverage

| Scenario | Evidence in this increment | Status |
| --- | --- | --- |
| Registration, household, member, and caregiver authorization | `test_hct405_core_flows.py` | Automated |
| Image/video quality, multi-evidence recognition, and manual review | No released API capability | Blocked |
| UNKNOWN and CONFLICT do not create facts | No released vision/fusion API capability | Blocked |
| Confirmed event updates timeline and projection | `test_hct405_core_flows.py` | Automated |
| Rule result returns desensitized risk evidence | `test_hct405_core_flows.py` | Automated |
| Plan confirmation, deferral, skip, and authorized care actions | `test_hct405_core_flows.py`; `client.test.ts` | Automated |
| Evidence assistant, refusal, and Ollama outage degradation | No released RAG/LLM API capability | Blocked |
| Revocation takes effect immediately | `test_hct405_core_flows.py` | Automated |
| Export and deletion propagation | No released export/deletion API capability | Blocked |
| Local egress restriction and weather field minimization | Existing HCT-004 safety tests; HCT-405 end-to-end runner pending | Pending integration |
| No purchase, consultation, or advertising entry point | Existing HCT-004 redirect scan; browser evidence pending | Pending integration |
| V2 fixed-set comparison and rollback | No released V2 model capability | Blocked |

## Given / When / Then

- Given a caregiver has a valid read/write grant, when confirmed synthetic allergy and medication events are appended, then the caregiver can read the authorized timeline and desensitized risk evidence only.
- Given an event is unconfirmed, when the timeline and member state are requested, then it does not appear as a confirmed fact or update the projection.
- Given a caregiver has the required write grant, when the caregiver confirms, defers, or skips a plan, then the API records a confirmed append-only plan event.
- Given a grant is revoked or belongs to another household, when the caregiver requests events or a timeline, then the API returns no resource.
- Given a dependency is not released, when capabilities are queried, then it remains explicit rather than being treated as a passed scenario.

## Verification

- `npm.cmd run test:web`
- `npm.cmd run check:web`
- `uv run pytest tests/e2e/test_hct405_core_flows.py`
- `uv run pytest`
- `npm.cmd run build:web`
- `git diff --check`

## Acceptance Remaining

Final HCT-405 acceptance still requires the blocked and pending scenarios above, Playwright browser evidence for the visible workflows, JUnit/screenshots or videos where applicable, failure-injection evidence, and independent R3 review. Until then, this Story remains `In progress` and Issue #70 must not be closed.

## Rollback

Revert the API client helpers and E2E test files. This increment has no migration, persistent fixture, remote dependency, or production health-data effect.
