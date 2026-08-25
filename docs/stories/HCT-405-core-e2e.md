# HCT-405: Core E2E Scenarios and Safe Degradation

- Issue: [#70](https://github.com/Meyt1n/issedu_ysu2026_3709/issues/70)
- Requirements: FR-01 through FR-10; NFR-01, NFR-02, NFR-03, NFR-04, NFR-06, NFR-07
- Status: In progress. Backend API scenarios are automated; final cross-team R3 acceptance is pending.
- Owner: Shen-huang-123 (backend increment) and jin-123-zip (existing frontend increment)
- Reviewer: Meyt1n or another independently assigned reviewer (R3; owners cannot self-review)
- Risk: R3
- Dependencies: HCT-207, HCT-307, HCT-308, HCT-401, HCT-403, and HCT-404; the backend files and migrations accidentally removed by PR #128 must first be restored by #132/PR #133.
- Allowed changes: focused knowledge/assistant API fixes; vision/review routing, schemas, application helpers and migration; household/member erasure helpers, tombstone columns, cleanup-task API and migration; `scripts/backup.ps1` skip-marker copy; focused unit/contract/integration tests; `tests/e2e/`; `tests/browser/`; `playwright.config.ts`; `.github/workflows/ci.yml`; the existing frontend API/test files; this Story; the API specification; and the requirement traceability matrix.

## Value and Scope

This increment creates a repeatable, synthetic-data E2E regression baseline for the backend APIs. It exercises the owner and caregiver authorization boundary through event projection, risk evidence, plan actions, revocation, cross-household denial, local knowledge retrieval, vision four-state safety, manual correction, deletion propagation, and model-binding rollback.

It also verifies structured Ollama outage and unsafe-output degradation at the HTTP boundary. The assistant executes whitelisted read-only tools against the caller's authorized knowledge scope and only returns citations that match retrieved `document_id`/`version`/`chunk_id` tuples. Owner household erasure returns a cleanup task covering database tombstones, files, household-scoped vectors, cache, hard samples, and backup skip markers; confirmed health events remain physically immutable and are only hidden. The backend wiring increment binds every accepted vision task to a real household member, creates one pending `ReviewTask` after fusion, fingerprints the complete fusion and transition inputs, and uses a versioned conditional database update so concurrent confirm/correct requests cannot create duplicate health events or outbox rows. CI runs the migration against SQLite and MySQL 8.4, records focused API JUnit evidence, and retains Playwright JUnit/failure artifacts. The client keeps authorization, purpose, version, and idempotency metadata at the API boundary; it does not call databases, rules, models, or Ollama directly.

## Explicitly Out of Scope

- Synthetic signed adapter output verifies the API contract only; it is not presented as real OCR/barcode/model accuracy.
- Injected Ollama responses verify outage and safety behavior only; they are not presented as a released LLM or medical-answer quality evidence.
- A synthetic V1/V2 binding drill verifies comparison and rollback state transitions only; it is not a released model evaluation.
- Knowledge, hard-sample, household, object-store, cache, vector, and backup-skip deletion are automated for the local controlled stores. Rewriting or destroying already-shipped production disaster-recovery backups is out of scope.
- No real household data, images, weights, secrets, logs, or networked health content is used.

## Scenario Coverage

| Scenario | Evidence in this increment | Status |
| --- | --- | --- |
| Registration, household, member, and caregiver authorization | `test_hct405_core_flows.py` | Automated |
| Image quality, multi-evidence fusion, automatic unique review creation, and manual correction | `test_hct405_failure_degradation.py`; `test_hct405_vision_review_release.py` | Automated with synthetic bytes/adapter evidence |
| MATCHED still requires confirmation; UNKNOWN and CONFLICT do not create facts | `test_hct405_vision_review_release.py` | Automated |
| Member-scoped vision/review authorization and concurrent confirmation/correction | `test_hct202_quality_api.py`; `test_hct405_vision_review_release.py` | Automated with cross-household denial and two-thread/two-session event/outbox assertions |
| Confirmed event updates timeline and projection | `test_hct405_core_flows.py` | Automated |
| Rule result returns desensitized risk evidence | `test_hct405_core_flows.py` | Automated |
| Plan confirmation, deferral, skip, and authorized care actions | `test_hct405_core_flows.py`; `client.test.ts` | Automated |
| Knowledge evidence, no-authorized-evidence degradation, unsafe-output refusal, and Ollama outage | `test_hct405_failure_degradation.py` | Automated at API boundary, including live tool-call citation checks against retrieved chunks |
| Revocation takes effect immediately | `test_hct405_core_flows.py` | Automated |
| Knowledge, hard-sample, household, object-store, cache, vector, and backup-skip deletion | `test_hct405_failure_degradation.py`; `test_hct405_vision_review_release.py`; `test_hct405_deletion_propagation.py` | Automated for local stores; production backup rewrite remains out of scope |
| Local egress restriction, network outage, and weather field minimization | HCT-004 safety tests; assistant outage E2E | Automated by focused safety/API tests; deployment drill remains pending |
| No purchase, consultation, or advertising entry point | Existing HCT-004 redirect scan; `tests/browser/hct405-visible-workflows.spec.ts` | Automated (synthetic browser boundary) |
| V2 fixed-set comparison and rollback | `test_hct405_vision_review_release.py` | Automated state-transition drill; released-model evaluation remains blocked |

The browser evidence added by this increment is `tests/browser/hct405-visible-workflows.spec.ts` and `tests/browser/hct405-real-api.spec.ts` (real-API, env-gated). It covers an owner creating and revoking a synthetic caregiver grant, API-unavailable rendering without a household or health summary, and the local-only/no-promotion boundary. **2026-08-25 门户连续演示**：`tests/e2e/test_hct405_portal_continuous.py` 将 HCT-439 双门户权限与 HCT-206/207 复核桥接串联（成员提交 → 管理员确认 → 成员只看已确认时间线）；`hct405-real-api.spec.ts` 已对齐当前中文门户 UI。

**2026-08-25 A2 规则提醒闭环**：`tests/e2e/test_hct405_member_risk_loop.py` 覆盖「管理员确认过敏/药品 → 规则引擎 → 成员 `listMemberRisks`」；成员前台用 `src/web/src/ui/memberRisk.ts` 包装生活化文案，不展示 `rule_id`/`SEVERE`。 Visible-workflow assertions target `.view-stage h2.hero-greeting` and `aside.sidebar button.nav-item` so they stay unique after the topbar title and lazy-loaded views share the same page names. The tests use synthetic API responses only; they do not represent visual recognition, RAG, model release, deletion propagation, or deployment acceptance.

## Given / When / Then

- Given a caregiver has a valid read/write grant, when confirmed synthetic allergy and medication events are appended, then the caregiver can read the authorized timeline and desensitized risk evidence only.
- Given an event is unconfirmed, when the timeline and member state are requested, then it does not appear as a confirmed fact or update the projection.
- Given a caregiver has the required write grant, when the caregiver confirms, defers, or skips a plan, then the API records a confirmed append-only plan event.
- Given a grant is revoked or belongs to another household, when the caregiver requests events, a timeline, or vision task read/fusion/cancel operations, then the API returns no resource.
- Given a synthetic image fails the local quality gate, when a task is attempted, then no vision task or health fact is created.
- Given signed synthetic evidence produces MATCHED, CONFLICT, UNKNOWN, or REVIEW, when fusion is repeated with the same thresholds, weights, and versions, then it returns the same unique pending review task and still forbids automatic health-event creation; changed fusion configuration returns a conflict.
- Given a vision task references a member outside the actor's authorized scope, when task creation is requested, then the API hides the resource and creates no task.
- Given two sessions concurrently submit confirm/correct transitions for version 1, when the database conditionally changes the pending review, then only one request succeeds and exactly one confirmed event plus one outbox row exists; reusing its idempotency key with a changed payload is rejected.
- Given a pending review task, when an owner or caregiver with current read/write authorization submits a manual correction with its expected version, then exactly one confirmed append-only event records the review evidence and the explainable fusion context.
- Given a private knowledge document, when another actor retrieves or deletes it, then no resource or chunk is disclosed; when the owner deletes it, retrieval and chunks are removed.
- Given Ollama is unreachable or returns prohibited medical/external-link output, when the assistant endpoint is called, then it returns a structured low-confidence degradation without unsafe text or untrusted sources.
- Given the local assistant issues a whitelisted `retrieve_knowledge` tool call, when the backend executes it in the caller's authorized scope, then the final answer may only cite `document_id`/`version`/`chunk_id` tuples returned by that tool; fabricated sources degrade with `CITATION_NOT_FOUND`, and unauthorized actors receive `NO_AUTHORISED_DOCUMENTS`.
- Given an approved hard sample is exported with consent, when the sample is deleted, then active consent is revoked and the export manifest is invalidated.
- Given an owner requests household erasure, when the cleanup task completes, then the household, members, files, household-scoped knowledge chunks, cache entries, and hard samples are hidden or removed, a backup skip marker is recorded without payload or display names, confirmed health-event rows remain physically immutable, and other households are unchanged.
- Given synthetic V2 is activated after V1, when V2 is rolled back, then V2 is revoked and V1 becomes active again.

## Verification

- `npm.cmd run test:web`
- `npm.cmd run test:e2e:web` (uses Playwright Chromium; on this Windows host it uses the installed Edge executable)
- `npm.cmd run check:web`
- `uv run pytest tests/e2e/test_hct405_core_flows.py tests/e2e/test_hct405_failure_degradation.py tests/e2e/test_hct405_scenario_manifest.py tests/e2e/test_hct405_vision_review_release.py tests/e2e/test_hct405_deletion_propagation.py tests/e2e/test_hct405_portal_continuous.py tests/e2e/test_hct405_member_risk_loop.py tests/e2e/test_hct405_family_login.py`
- `uv run pytest tests/integration/test_hct405_review_migration.py tests/integration/test_hct405_erasure_migration.py tests/unit/test_hct207_review.py tests/unit/test_hct405_erasure.py tests/contract/test_hct202_quality_api.py tests/contract/test_hct205_evidence_api.py`
- `HCT405_MYSQL_TEST_URL=<disposable-mysql-8.4-url> uv run pytest tests/integration/test_hct405_review_migration.py::test_review_wiring_upgrade_and_downgrade_on_mysql` (automated in CI)
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

Final HCT-405 acceptance still requires a deployment restart/offline drill, released-model fixed-set evidence, and project-lead/two-group-lead R3 review. Household erasure now returns a cleanup task covering database tombstones, files, vectors, cache, hard samples, and backup skip markers; confirmed events remain physically immutable and are only hidden. Until the remaining facts exist, this Story remains `In progress` and Issue #70 must not be closed.

2026-08-22 新增 `scripts/hct405_acceptance_gate.py`，将成员上下文、扫描人工确认、规则提醒、助手解释和离线重启纳入一条
可复现 trace；仍强制检查批准发布模型、部署演练和跨组 R3，合成 E2E 不能单独关闭本 Story。

2026-08-24 新增 `scripts/hct405_local_evidence.py`，可读取 API/Web/数据库健康状态并执行核心合成回归，输出到被 Git 忽略的
`artifacts/hct405-local-evidence.json`。本地 API、数据库、能力接口和 Web 健康检查均已通过，合成回归也已通过；报告决策固定为
`LOCAL_EVIDENCE_COLLECTED_NOT_ACCEPTANCE`，不会把真实动态人脸、批准发布模型、重启/断网演练或跨组 R3 误记为通过。

## Rollback

Revert the focused API/application/test changes, then downgrade `0011_hct405_erasure` only when no `erasure_task` rows exist; the migration refuses to discard erasure audit. Downgrade `0010_hct405_review_wiring` only when no new review audit context/fingerprints/version transitions and no `REVIEW` rows exist. On upgrade, the review-wiring migration repairs historical vision-task household IDs from their assigned members and cancels active legacy tasks with no valid member scope; these safety corrections are intentionally not reversed. The erasure migration adds nullable `deleted_at` tombstones and the cleanup-task table. All test inputs are generated in temporary stores, with no external health-data dependency.
