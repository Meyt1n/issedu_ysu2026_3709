# HCT-405: Core E2E Scenarios and Safe Degradation

- Issue: [#70](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/70)
- Requirements: FR-01 through FR-10; NFR-01, NFR-02, NFR-03, NFR-04, NFR-06, NFR-07
- Status: In progress. Backend API scenarios are automated; final cross-team R3 acceptance is pending.
- Owner: Shen-huang-123 (backend increment) and jin-123-zip (existing frontend increment)
- Reviewer: Meyt1n or another independently assigned reviewer (R3; owners cannot self-review)
- Risk: R3
- Dependencies: HCT-207, HCT-307, HCT-308, HCT-401, HCT-403, and HCT-404; the backend files and migrations accidentally removed by PR #128 must first be restored by #132/PR #133.
- Allowed changes: focused knowledge/assistant API fixes, focused unit tests, `tests/e2e/`, `tests/browser/`, `playwright.config.ts`, `.github/workflows/ci.yml`, the existing frontend API/test files, this Story, and the requirement traceability matrix.

## Value and Scope

This increment creates a repeatable, synthetic-data E2E regression baseline for the backend APIs. It exercises the owner and caregiver authorization boundary through event projection, risk evidence, plan actions, revocation, cross-household denial, local knowledge retrieval, vision four-state safety, manual correction, deletion propagation, and model-binding rollback.

It also verifies structured Ollama outage and unsafe-output degradation at the HTTP boundary. CI records focused API JUnit evidence and Playwright JUnit/failure artifacts. The client keeps authorization, purpose, and idempotency metadata at the API boundary; it does not call databases, rules, models, or Ollama directly.

## Explicitly Out of Scope

- Synthetic signed adapter output verifies the API contract only; it is not presented as real OCR/barcode/model accuracy.
- Injected Ollama responses verify outage and safety behavior only; they are not presented as a released LLM or medical-answer quality evidence.
- A synthetic V1/V2 binding drill verifies comparison and rollback state transitions only; it is not a released model evaluation.
- Knowledge and consent/export deletion propagation do not represent full household, object-store, backup, or disaster-recovery erasure.
- No real household data, images, weights, secrets, logs, or networked health content is used.

## Scenario Coverage

| Scenario | Evidence in this increment | Status |
| --- | --- | --- |
| Registration, household, member, and caregiver authorization | `test_hct405_core_flows.py` | Automated |
| Image quality, multi-evidence fusion, and manual correction | `test_hct405_failure_degradation.py`; `test_hct405_vision_review_release.py` | Automated with synthetic bytes/adapter evidence |
| MATCHED still requires confirmation; UNKNOWN and CONFLICT do not create facts | `test_hct405_vision_review_release.py` | Automated |
| Confirmed event updates timeline and projection | `test_hct405_core_flows.py` | Automated |
| Rule result returns desensitized risk evidence | `test_hct405_core_flows.py` | Automated |
| Plan confirmation, deferral, skip, and authorized care actions | `test_hct405_core_flows.py`; `client.test.ts` | Automated |
| Knowledge evidence, no-authorized-evidence degradation, unsafe-output refusal, and Ollama outage | `test_hct405_failure_degradation.py` | Automated at API boundary; live tool-call citation remains pending |
| Revocation takes effect immediately | `test_hct405_core_flows.py` | Automated |
| Knowledge deletion and hard-sample consent/export invalidation | Both new HCT-405 E2E files | Automated for available stores; full household erasure remains pending |
| Local egress restriction, network outage, and weather field minimization | HCT-004 safety tests; assistant outage E2E | Automated by focused safety/API tests; deployment drill remains pending |
| No purchase, consultation, or advertising entry point | Existing HCT-004 redirect scan; `tests/browser/hct405-visible-workflows.spec.ts` | Automated (synthetic browser boundary) |
| V2 fixed-set comparison and rollback | `test_hct405_vision_review_release.py` | Automated state-transition drill; released-model evaluation remains blocked |

`tests/e2e/hct405_scenarios.json` is the machine-readable source for all twelve scenarios. Each entry records preconditions, roles, steps, expected states, permission boundary, audit evidence, cleanup, coverage tags, automated tests, and explicit limitations. `test_hct405_scenario_manifest.py` prevents missing fields, missing evidence files, or accidental loss of the required failure/four-state cases.

The browser evidence is `tests/browser/hct405-visible-workflows.spec.ts`. It covers an owner creating and revoking a synthetic caregiver grant, API-unavailable rendering without a household or health summary, and the local-only/no-promotion boundary. CI now runs it and retains JUnit plus screenshots, traces, and video on failure. These three tests still use synthetic API responses.

`tests/browser/hct405-real-api.spec.ts` adds real-API browser coverage: it drives the Vue frontend through the Vite proxy against a locally running FastAPI backend with no route mocks. It verifies (1) an owner grant create/revoke round trip whose state survives a full page reload and is locatable in the `authorization-audits` API trail, (2) a caregiver seeing only the granted member scope and losing household visibility after revocation, (3) a confirmed manual event reaching the dashboard projection, timeline, and a real rules-engine evaluation, and (4) an unknown identity receiving no household or health data. The file is gated by `REAL_API_E2E=1` and skips otherwise, so the default suite stays runnable without a backend; all identifiers are synthetic and namespaced per run. It does not represent live visual recognition, RAG, model release, deletion propagation, or deployment acceptance.

## Given / When / Then

- Given a caregiver has a valid read/write grant, when confirmed synthetic allergy and medication events are appended, then the caregiver can read the authorized timeline and desensitized risk evidence only.
- Given an event is unconfirmed, when the timeline and member state are requested, then it does not appear as a confirmed fact or update the projection.
- Given a caregiver has the required write grant, when the caregiver confirms, defers, or skips a plan, then the API records a confirmed append-only plan event.
- Given a grant is revoked or belongs to another household, when the caregiver requests events or a timeline, then the API returns no resource.
- Given a synthetic image fails the local quality gate, when a task is attempted, then no vision task or health fact is created.
- Given signed synthetic evidence produces MATCHED, CONFLICT, or UNKNOWN, when fusion is requested, then the result records versions and still forbids automatic health-event creation.
- Given a pending review task, when the owner submits a manual correction, then exactly one confirmed append-only event records the review evidence.
- Given a private knowledge document, when another actor retrieves or deletes it, then no resource or chunk is disclosed; when the owner deletes it, retrieval and chunks are removed.
- Given Ollama is unreachable or returns prohibited medical/external-link output, when the assistant endpoint is called, then it returns a structured low-confidence degradation without unsafe text or untrusted sources.
- Given an approved hard sample is exported with consent, when the sample is deleted, then active consent is revoked and the export manifest is invalidated.
- Given synthetic V2 is activated after V1, when V2 is rolled back, then V2 is revoked and V1 becomes active again.

## Verification

- `npm.cmd run test:web`
- `npm.cmd run test:e2e:web` (uses Playwright Chromium; on this Windows host it uses the installed Edge executable)
- `npm.cmd run check:web`
- `uv run pytest tests/e2e/test_hct405_core_flows.py tests/e2e/test_hct405_failure_degradation.py tests/e2e/test_hct405_scenario_manifest.py tests/e2e/test_hct405_vision_review_release.py`
- `uv run pytest`
- `npm.cmd run build:web`
- `git diff --check`

Real-API browser coverage (Windows, Python 3.11 venv with the `pyproject.toml` runtime dependencies plus `httpx`):

```powershell
$env:DATABASE_URL = "sqlite+pysqlite:///./homecare-e2e.sqlite3"
.\.venv\Scripts\alembic.exe upgrade head
$env:PYTHONPATH = "src/api;src;scripts"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000   # keep running
$env:REAL_API_E2E = "1"; npx playwright test tests/browser/hct405-real-api.spec.ts --config playwright.config.ts
```

The sqlite file and `.venv` are gitignored; the run is disposable and contains only synthetic identifiers.

CI uploads `hct405-api-evidence` and `hct405-browser-evidence` for 14 days. The API artifact contains focused JUnit plus `hct405-environment.json` with the commit SHA, environment, synthetic-data policy, reproduction commands, and artifact paths; the browser artifact contains JUnit and retained failure screenshots, traces, and video without real health data.

## Acceptance Remaining

Browser coverage against a real local API is now automated by `tests/browser/hct405-real-api.spec.ts` (local run; CI does not start the backend for browser jobs, so the spec is env-gated and skipped there).

Final HCT-405 acceptance still requires live assistant tool-call citation validation, automatic vision-to-review task wiring, true concurrent event/review writes, full household/object/backup deletion evidence, a deployment restart/offline drill, released-model fixed-set evidence, and project-lead/two-group-lead R3 review. Until those facts exist, this Story remains `In progress` and Issue #70 must not be closed.

## Rollback

Revert the focused knowledge/assistant fixes, CI evidence steps, and E2E files. All test inputs are generated in temporary stores; the increment has no migration, persistent fixture, external health-data dependency, or production health-data effect.
