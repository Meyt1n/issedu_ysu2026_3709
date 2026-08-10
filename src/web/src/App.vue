<script setup lang="ts">
import { computed, reactive, ref } from 'vue'

import {
  buildAuthorizationPreview,
  isAuthorizationActive,
} from './authorization/authorizationView'
import { ApiClientError, apiClient } from './api/client'
import { riskLevelLabel, toRiskCardModel } from './risk/riskView'
import type {
  Authorization,
  AuthorizationAction,
  CapabilityResponse,
  CreateAuthorizationInput,
  HealthEvent,
  Household,
  MemberState,
  Member,
  RequestOptions,
  RiskAlert,
  RiskDetailResponse,
  RiskListResponse,
  UpdateAuthorizationInput,
} from './api/types'

const FIELD_OPTIONS = [
  { value: 'health_events', label: 'Confirmed health events' },
] as const

const ACTION_OPTIONS: Array<{ value: AuthorizationAction; label: string }> = [
  { value: 'READ_EVENTS', label: 'View confirmed events' },
  { value: 'WRITE_EVENTS', label: 'Add confirmed events' },
]

const purposePattern = /^[A-Za-z0-9._:-]{1,64}$/

const actorId = ref('')
const accessPurpose = ref('family-care')
const households = ref<Household[]>([])
const members = ref<Member[]>([])
const authorizations = ref<Authorization[]>([])
const selectedHouseholdId = ref('')
const selectedAuthorizationId = ref<string | null>(null)
const previewActorId = ref('')
const isOwnerView = ref(false)
const loadingHouseholds = ref(false)
const loadingScope = ref(false)
const saving = ref(false)
const message = ref('Enter a development identity to load its households.')
const error = ref('')
const formError = ref('')
const riskMemberId = ref('')
const riskList = ref<RiskListResponse | null>(null)
const riskDetails = ref<Record<string, RiskDetailResponse>>({})
const loadingRisks = ref(false)
const riskError = ref('')
const expandedRiskId = ref<string | null>(null)
const dashboardMemberId = ref('')
const dashboardTimeline = ref<HealthEvent[]>([])
const dashboardState = ref<MemberState | null>(null)
const capabilities = ref<CapabilityResponse | null>(null)
const loadingDashboard = ref(false)
const dashboardError = ref('')

const draft = reactive({
  memberId: '',
  granteeActorId: '',
  dataFields: ['health_events'] as string[],
  actions: ['READ_EVENTS'] as AuthorizationAction[],
  purpose: 'family-care',
  validUntil: localDateTimeInput(7),
})

const requestOptions = computed<RequestOptions>(() => ({
  actorId: actorId.value.trim() || undefined,
  accessPurpose: accessPurpose.value.trim() || undefined,
}))

const selectedAuthorization = computed(
  () => authorizations.value.find(item => item.id === selectedAuthorizationId.value) ?? null,
)

const memberNames = computed(() => new Map(members.value.map(member => [member.id, member.display_name])))
const dashboardMemberName = computed(
  () => memberNames.value.get(dashboardMemberId.value) ?? 'Selected member',
)
const recentTimeline = computed(() => dashboardTimeline.value.slice(0, 4))
const privacyScopeLabel = computed(
  () => isOwnerView.value ? 'Owner-managed household scope' : 'API-filtered caregiver scope',
)

const authorizationPreview = computed(() => {
  const previewActor = previewActorId.value.trim()
  if (!previewActor) return []

  return buildAuthorizationPreview(authorizations.value, previewActor).map(scope => ({
    ...scope,
    memberName: memberNames.value.get(scope.memberId) ?? 'Authorized member',
  }))
})

const canSave = computed(
  () =>
    draft.memberId.length > 0 &&
    draft.granteeActorId.trim().length > 0 &&
    draft.dataFields.length > 0 &&
    draft.actions.length > 0 &&
    purposePattern.test(draft.purpose) &&
    isFutureDate(draft.validUntil),
)

function localDateTimeInput(daysFromNow: number): string {
  const date = new Date()
  date.setDate(date.getDate() + daysFromNow)
  date.setSeconds(0, 0)
  const timezoneOffset = date.getTimezoneOffset() * 60_000
  return new Date(date.getTime() - timezoneOffset).toISOString().slice(0, 16)
}

function isFutureDate(value: string): boolean {
  const timestamp = Date.parse(value)
  return Number.isFinite(timestamp) && timestamp > Date.now()
}

function createIdempotencyKey(): string {
  return globalThis.crypto?.randomUUID?.() ?? `web-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function formatError(cause: unknown): string {
  if (cause instanceof ApiClientError) {
    if (cause.code === 'DEPENDENCY_UNAVAILABLE') return 'The local API is unavailable. No data was changed.'
    if (cause.status === 401) return 'Sign in is required before this request can continue.'
    if (cause.status === 404) return 'This resource is unavailable for the current identity.'
    if (cause.status === 409) return 'The authorization changed elsewhere. Reload before trying again.'
  }
  return 'The request could not be completed. No health data is shown from this page.'
}

function clearScope(): void {
  selectedHouseholdId.value = ''
  members.value = []
  authorizations.value = []
  selectedAuthorizationId.value = null
  previewActorId.value = ''
  isOwnerView.value = false
  riskMemberId.value = ''
  riskList.value = null
  riskDetails.value = {}
  riskError.value = ''
  expandedRiskId.value = null
  dashboardMemberId.value = ''
  dashboardTimeline.value = []
  dashboardState.value = null
  capabilities.value = null
  dashboardError.value = ''
  resetDraft()
}

function resetDraft(): void {
  selectedAuthorizationId.value = null
  formError.value = ''
  draft.memberId = members.value[0]?.id ?? ''
  draft.granteeActorId = ''
  draft.dataFields = ['health_events']
  draft.actions = ['READ_EVENTS']
  draft.purpose = 'family-care'
  draft.validUntil = localDateTimeInput(7)
}

async function loadHouseholds(): Promise<void> {
  const currentActor = actorId.value.trim()
  if (!currentActor) {
    clearScope()
    error.value = 'Enter a development identity before loading households.'
    return
  }

  loadingHouseholds.value = true
  error.value = ''
  clearScope()
  try {
    households.value = await apiClient.listHouseholds(requestOptions.value)
    if (households.value.length === 0) {
      message.value = 'No household is visible to this identity.'
      return
    }
    selectedHouseholdId.value = households.value[0]?.id ?? ''
    await loadSelectedHousehold()
  } catch (cause) {
    households.value = []
    error.value = formatError(cause)
  } finally {
    loadingHouseholds.value = false
  }
}

async function loadSelectedHousehold(): Promise<void> {
  const householdId = selectedHouseholdId.value
  if (!householdId) return

  loadingScope.value = true
  error.value = ''
  members.value = []
  authorizations.value = []
  selectedAuthorizationId.value = null
  previewActorId.value = ''
  riskMemberId.value = ''
  riskList.value = null
  riskDetails.value = {}
  riskError.value = ''
  expandedRiskId.value = null
  dashboardMemberId.value = ''
  dashboardTimeline.value = []
  dashboardState.value = null
  capabilities.value = null
  dashboardError.value = ''
  try {
    members.value = await apiClient.listMembers(householdId, requestOptions.value)
    draft.memberId = members.value[0]?.id ?? ''
    riskMemberId.value = members.value[0]?.id ?? ''
    dashboardMemberId.value = members.value[0]?.id ?? ''

    try {
      authorizations.value = await apiClient.listAuthorizations(householdId, requestOptions.value)
      isOwnerView.value = true
      message.value = 'Owner view: manage grants and preview a caregiver scope.'
    } catch (cause) {
      if (cause instanceof ApiClientError && cause.status === 404) {
        isOwnerView.value = false
        message.value = 'Caregiver view: the API has already filtered this identity to the granted member scope.'
        await loadDashboard()
        return
      }
      throw cause
    }
    await loadDashboard()
  } catch (cause) {
    members.value = []
    authorizations.value = []
    isOwnerView.value = false
    error.value = formatError(cause)
  } finally {
    loadingScope.value = false
  }
}

async function loadDashboard(): Promise<void> {
  const householdId = selectedHouseholdId.value
  const memberId = dashboardMemberId.value
  if (!householdId || !memberId) return

  loadingDashboard.value = true
  dashboardError.value = ''
  riskMemberId.value = memberId
  try {
    const [timelineResult, stateResult, capabilityResult] = await Promise.allSettled([
      apiClient.listMemberTimeline(householdId, memberId, requestOptions.value),
      apiClient.getMemberState(householdId, memberId, requestOptions.value),
      apiClient.getCapabilities(requestOptions.value),
    ])
    if (timelineResult.status === 'fulfilled') dashboardTimeline.value = timelineResult.value
    else dashboardTimeline.value = []
    if (stateResult.status === 'fulfilled') dashboardState.value = stateResult.value
    else dashboardState.value = null
    if (capabilityResult.status === 'fulfilled') capabilities.value = capabilityResult.value
    else capabilities.value = null

    await loadMemberRisks()
    if (timelineResult.status === 'rejected' || stateResult.status === 'rejected') {
      dashboardError.value = 'Some permitted dashboard data is currently unavailable. No hidden data is inferred.'
    }
  } finally {
    loadingDashboard.value = false
  }
}

async function loadMemberRisks(): Promise<void> {
  const householdId = selectedHouseholdId.value
  const memberId = riskMemberId.value
  if (!householdId || !memberId) {
    riskList.value = null
    return
  }

  loadingRisks.value = true
  riskError.value = ''
  expandedRiskId.value = null
  try {
    riskList.value = await apiClient.listMemberRisks(householdId, memberId, requestOptions.value)
    riskDetails.value = {}
  } catch (cause) {
    riskList.value = null
    riskError.value = formatError(cause)
  } finally {
    loadingRisks.value = false
  }
}

async function toggleRiskDetail(alert: RiskAlert): Promise<void> {
  if (expandedRiskId.value === alert.rule_id) {
    expandedRiskId.value = null
    return
  }

  expandedRiskId.value = alert.rule_id
  if (riskDetails.value[alert.rule_id]) return

  try {
    const detail = await apiClient.getRiskDetail(
      selectedHouseholdId.value,
      riskMemberId.value,
      alert.rule_id,
      requestOptions.value,
    )
    riskDetails.value = { ...riskDetails.value, [alert.rule_id]: detail }
  } catch (cause) {
    expandedRiskId.value = null
    riskError.value = formatError(cause)
  }
}

function editAuthorization(authorization: Authorization): void {
  selectedAuthorizationId.value = authorization.id
  draft.memberId = authorization.member_id
  draft.granteeActorId = authorization.grantee_actor_id
  draft.dataFields = [...authorization.data_fields]
  draft.actions = [...authorization.actions]
  draft.purpose = authorization.purpose
  draft.validUntil = toLocalDateTimeInput(authorization.valid_until)
  formError.value = ''
}

function toLocalDateTimeInput(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return localDateTimeInput(7)
  const timezoneOffset = date.getTimezoneOffset() * 60_000
  return new Date(date.getTime() - timezoneOffset).toISOString().slice(0, 16)
}

function updateSelectedFields(value: string, checked: boolean): void {
  draft.dataFields = checked
    ? [...new Set([...draft.dataFields, value])]
    : draft.dataFields.filter(field => field !== value)
}

function updateSelectedActions(value: AuthorizationAction, checked: boolean): void {
  draft.actions = checked
    ? [...new Set([...draft.actions, value])]
    : draft.actions.filter(action => action !== value)
}

async function saveAuthorization(): Promise<void> {
  if (!selectedHouseholdId.value || !canSave.value) {
    formError.value = 'Choose a member, a caregiver identity, at least one field and action, a valid purpose code, and a future expiry.'
    return
  }

  const validUntil = new Date(draft.validUntil).toISOString()
  saving.value = true
  formError.value = ''
  try {
    const existing = selectedAuthorization.value
    if (existing) {
      const input: UpdateAuthorizationInput = {
        expected_version: existing.version,
        data_fields: [...draft.dataFields],
        actions: [...draft.actions],
        purpose: draft.purpose,
        valid_until: validUntil,
      }
      const updated = await apiClient.updateAuthorization(
        selectedHouseholdId.value,
        existing.id,
        input,
        { ...requestOptions.value, idempotencyKey: createIdempotencyKey() },
      )
      authorizations.value = authorizations.value.map(item => (item.id === updated.id ? updated : item))
      message.value = 'Authorization updated. The preview now reflects the new active scope.'
    } else {
      const input: CreateAuthorizationInput = {
        member_id: draft.memberId,
        grantee_actor_id: draft.granteeActorId.trim(),
        data_fields: [...draft.dataFields],
        actions: [...draft.actions],
        purpose: draft.purpose,
        valid_until: validUntil,
      }
      const created = await apiClient.createAuthorization(
        selectedHouseholdId.value,
        input,
        { ...requestOptions.value, idempotencyKey: createIdempotencyKey() },
      )
      authorizations.value = [...authorizations.value, created]
      message.value = 'Authorization created. The preview now reflects the new active scope.'
    }
    resetDraft()
  } catch (cause) {
    formError.value = formatError(cause)
  } finally {
    saving.value = false
  }
}

async function revokeAuthorization(authorization: Authorization): Promise<void> {
  if (!selectedHouseholdId.value || !isAuthorizationActive(authorization)) return

  saving.value = true
  error.value = ''
  try {
    const revoked = await apiClient.revokeAuthorization(
      selectedHouseholdId.value,
      authorization.id,
      authorization.version,
      { ...requestOptions.value, idempotencyKey: createIdempotencyKey() },
    )
    authorizations.value = authorizations.value.map(item => (item.id === revoked.id ? revoked : item))
    if (selectedAuthorizationId.value === authorization.id) resetDraft()
    message.value = 'Authorization revoked. It is removed from the caregiver preview immediately.'
  } catch (cause) {
    error.value = formatError(cause)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <main class="workspace">
    <header class="topbar">
      <div>
        <p class="eyebrow">HomeCare Twin</p>
        <h1>Household overview</h1>
        <p class="subtitle">Local household operations, bounded by member, purpose, and current API authorization.</p>
      </div>
      <p class="privacy-badge">Local-only health data</p>
    </header>

    <section class="identity-bar" aria-label="Development session">
      <label>
        Development identity
        <input v-model="actorId" autocomplete="off" placeholder="Actor ID" @change="clearScope" />
      </label>
      <label>
        Access purpose code
        <input v-model="accessPurpose" autocomplete="off" placeholder="family-care" @change="clearScope" />
      </label>
      <button type="button" :disabled="loadingHouseholds" @click="loadHouseholds">
        {{ loadingHouseholds ? 'Loading' : 'Load households' }}
      </button>
    </section>

    <p v-if="error" class="notice error" role="alert">{{ error }}</p>
    <p v-else class="notice" role="status">{{ message }}</p>

    <section v-if="households.length > 0" class="household-bar" aria-label="Household selection">
      <label>
        Household
        <select v-model="selectedHouseholdId" :disabled="loadingScope" @change="loadSelectedHousehold">
          <option v-for="household in households" :key="household.id" :value="household.id">
            {{ household.name }}
          </option>
        </select>
      </label>
      <span class="view-status">{{ isOwnerView ? 'Owner management view' : 'Caregiver filtered view' }}</span>
    </section>

    <section v-if="loadingScope" class="state-panel" aria-live="polite">Loading the permitted household scope.</section>

    <section v-if="selectedHouseholdId && dashboardMemberId" class="dashboard-overview" aria-labelledby="overview-title">
      <div class="dashboard-heading">
        <div>
          <p class="section-label">Daily view</p>
          <h2 id="overview-title">{{ dashboardMemberName }}</h2>
        </div>
        <label class="dashboard-member-select">
          Member
          <select v-model="dashboardMemberId" :disabled="loadingDashboard" @change="loadDashboard">
            <option v-for="member in members" :key="member.id" :value="member.id">{{ member.display_name }}</option>
          </select>
        </label>
      </div>

      <p v-if="dashboardError" class="notice error" role="alert">{{ dashboardError }}</p>
      <div class="overview-grid">
        <section class="overview-item">
          <p class="section-label">Visible scope</p>
          <strong>{{ privacyScopeLabel }}</strong>
          <span>Identity: {{ actorId || 'Not set' }}</span>
          <span>Purpose: {{ accessPurpose || 'Not set' }}</span>
        </section>
        <section class="overview-item">
          <p class="section-label">Local status</p>
          <strong>{{ capabilities ? 'API connected' : 'API status unavailable' }}</strong>
          <span>{{ capabilities?.available.length ?? 0 }} local capabilities reported</span>
          <span>Network egress remains policy-controlled</span>
        </section>
        <section class="overview-item">
          <p class="section-label">Event projection</p>
          <strong>{{ dashboardState?.state.events_count ?? 0 }} confirmed events</strong>
          <span>{{ dashboardState?.last_event_id ? 'Current projection available' : 'No projected event yet' }}</span>
          <span>Event details remain API-authorized</span>
        </section>
        <section class="overview-item">
          <p class="section-label">Risk signals</p>
          <strong>{{ riskList?.total ?? 0 }} active signals</strong>
          <span>{{ riskList?.severe_count ?? 0 }} severe · {{ riskList?.warning_count ?? 0 }} warning</span>
          <span>{{ riskError ? 'Risk dependency unavailable' : 'Desensitized evidence only' }}</span>
        </section>
      </div>

      <div class="dashboard-columns">
        <section class="dashboard-section" aria-labelledby="timeline-title">
          <div class="panel-heading">
            <div>
              <p class="section-label">Recent activity</p>
              <h2 id="timeline-title">Event timeline</h2>
            </div>
            <span class="section-status">{{ loadingDashboard ? 'Loading' : `${dashboardTimeline.length} visible` }}</span>
          </div>
          <p v-if="!loadingDashboard && recentTimeline.length === 0" class="empty-state">No confirmed event summary is available for this member.</p>
          <ul v-else class="timeline-list">
            <li v-for="event in recentTimeline" :key="event.id">
              <strong>{{ event.event_type }}</strong>
              <span>{{ event.confirmation_status }}</span>
              <span>{{ new Date(event.created_at).toLocaleString() }}</span>
            </li>
          </ul>
        </section>
        <section class="dashboard-section" aria-labelledby="reminder-title">
          <div class="panel-heading">
            <div>
              <p class="section-label">Care actions</p>
              <h2 id="reminder-title">Tasks and reminders</h2>
            </div>
            <span class="section-status">API dependency</span>
          </div>
          <p class="empty-state">No read-only task or reminder summary is available from the current API contract. This page does not infer planned care actions.</p>
        </section>
      </div>
    </section>

    <section v-if="selectedHouseholdId && isOwnerView" class="owner-layout">
      <section class="panel grant-editor" aria-labelledby="editor-title">
        <div class="panel-heading">
          <div>
            <p class="section-label">Authorization editor</p>
            <h2 id="editor-title">{{ selectedAuthorization ? 'Edit grant' : 'Create grant' }}</h2>
          </div>
          <button v-if="selectedAuthorization" type="button" class="quiet-button" @click="resetDraft">New grant</button>
        </div>

        <form @submit.prevent="saveAuthorization">
          <label>
            Caregiver identity
            <input v-model="draft.granteeActorId" autocomplete="off" required placeholder="Caregiver actor ID" />
          </label>
          <label>
            Household member
            <select v-model="draft.memberId" required>
              <option v-for="member in members" :key="member.id" :value="member.id">{{ member.display_name }}</option>
            </select>
          </label>
          <fieldset>
            <legend>Data fields</legend>
            <label v-for="field in FIELD_OPTIONS" :key="field.value" class="check-row">
              <input
                type="checkbox"
                :checked="draft.dataFields.includes(field.value)"
                @change="updateSelectedFields(field.value, ($event.target as HTMLInputElement).checked)"
              />
              {{ field.label }}
            </label>
          </fieldset>
          <fieldset>
            <legend>Allowed actions</legend>
            <label v-for="action in ACTION_OPTIONS" :key="action.value" class="check-row">
              <input
                type="checkbox"
                :checked="draft.actions.includes(action.value)"
                @change="updateSelectedActions(action.value, ($event.target as HTMLInputElement).checked)"
              />
              {{ action.label }}
            </label>
          </fieldset>
          <label>
            Purpose code
            <input v-model="draft.purpose" pattern="[A-Za-z0-9._:-]{1,64}" required placeholder="family-care" />
            <small>ASCII code, 1-64 characters: letters, digits, period, underscore, colon, or hyphen.</small>
          </label>
          <label>
            Expiry
            <input v-model="draft.validUntil" type="datetime-local" required />
          </label>
          <p v-if="formError" class="form-error" role="alert">{{ formError }}</p>
          <button type="submit" :disabled="saving || !canSave">{{ saving ? 'Saving' : selectedAuthorization ? 'Save changes' : 'Create grant' }}</button>
        </form>
      </section>

      <section class="panel grants-panel" aria-labelledby="grants-title">
        <div class="panel-heading">
          <div>
            <p class="section-label">Current scope</p>
            <h2 id="grants-title">Active grants</h2>
          </div>
          <button type="button" class="quiet-button" :disabled="loadingScope" @click="loadSelectedHousehold">Refresh</button>
        </div>

        <p v-if="authorizations.length === 0" class="empty-state">No caregiver grant has been created for this household.</p>
        <ul v-else class="grant-list">
          <li v-for="authorization in authorizations" :key="authorization.id" class="grant-row">
            <div>
              <p class="grant-title">{{ memberNames.get(authorization.member_id) ?? 'Authorized member' }}</p>
              <p class="grant-meta">{{ authorization.grantee_actor_id }} | {{ authorization.purpose }} | version {{ authorization.version }}</p>
              <p class="grant-meta">{{ authorization.data_fields.join(', ') }} | {{ authorization.actions.join(', ') }}</p>
              <p class="grant-meta">{{ isAuthorizationActive(authorization) ? `Expires ${new Date(authorization.valid_until).toLocaleString()}` : authorization.revoked_at ? 'Revoked' : 'Expired' }}</p>
            </div>
            <div class="row-actions">
              <button type="button" class="quiet-button" :disabled="saving || !isAuthorizationActive(authorization)" @click="editAuthorization(authorization)">Edit</button>
              <button type="button" class="danger-button" :disabled="saving || !isAuthorizationActive(authorization)" @click="revokeAuthorization(authorization)">Revoke</button>
            </div>
          </li>
        </ul>
      </section>

      <section class="panel preview-panel" aria-labelledby="preview-title">
        <div class="panel-heading">
          <div>
            <p class="section-label">Caregiver preview</p>
            <h2 id="preview-title">Visible scope only</h2>
          </div>
        </div>
        <label>
          Preview caregiver identity
          <input v-model="previewActorId" autocomplete="off" placeholder="Caregiver actor ID" />
        </label>
        <p class="preview-note">This preview uses grant metadata only. It never loads health event content; the API remains responsible for field filtering on a caregiver request.</p>
        <p v-if="previewActorId && authorizationPreview.length === 0" class="empty-state">No active fields are granted to this caregiver.</p>
        <ul v-else-if="authorizationPreview.length > 0" class="preview-list">
          <li v-for="scope in authorizationPreview" :key="scope.authorizationId">
            <strong>{{ scope.memberName }}</strong>
            <span>{{ scope.fields.join(', ') }}</span>
            <span>{{ scope.actions.join(', ') }}</span>
            <span>{{ scope.purpose }} until {{ new Date(scope.validUntil).toLocaleString() }}</span>
          </li>
        </ul>
      </section>
    </section>

    <section v-else-if="selectedHouseholdId" class="panel caregiver-panel" aria-labelledby="caregiver-title">
      <p class="section-label">Filtered caregiver scope</p>
      <h2 id="caregiver-title">Members available to this identity</h2>
      <p class="preview-note">Only the API decides whether a member or event is returned. This view does not infer or reveal ungranted fields.</p>
      <p v-if="members.length === 0" class="empty-state">No member is available for the current identity and purpose code.</p>
      <ul v-else class="member-list">
        <li v-for="member in members" :key="member.id">{{ member.display_name }}</li>
      </ul>
    </section>

    <section v-if="selectedHouseholdId && riskMemberId" class="panel risk-panel" aria-labelledby="risk-title">
      <div class="panel-heading">
        <div>
          <p class="section-label">Confirmed evidence</p>
          <h2 id="risk-title">Risk signals</h2>
        </div>
        <label class="risk-member-select">
          Member
          <select v-model="riskMemberId" :disabled="loadingRisks" @change="loadMemberRisks">
            <option v-for="member in members" :key="member.id" :value="member.id">{{ member.display_name }}</option>
          </select>
        </label>
      </div>

      <p v-if="loadingRisks" class="state-panel" aria-live="polite">Loading permitted risk signals.</p>
      <p v-else-if="riskError" class="notice error" role="alert">{{ riskError }}</p>
      <p v-else-if="riskList && riskList.alerts.length === 0" class="empty-state">No active risk signals were returned for this member.</p>
      <template v-else-if="riskList">
        <p class="risk-summary">{{ riskList.total }} signals · {{ riskList.severe_count }} severe · {{ riskList.warning_count }} warning</p>
        <ul class="risk-list">
          <li v-for="alert in riskList.alerts" :key="alert.rule_id" class="risk-card">
            <button type="button" class="risk-card-toggle" :aria-expanded="expandedRiskId === alert.rule_id" @click="toggleRiskDetail(alert)">
              <span class="risk-level" :data-level="alert.level">{{ riskLevelLabel(alert.level) }}</span>
              <span class="risk-message">{{ alert.message }}</span>
              <span class="risk-source-count">{{ toRiskCardModel(alert).sourceCount }} source events</span>
              <span aria-hidden="true">{{ expandedRiskId === alert.rule_id ? 'Hide' : 'View evidence' }}</span>
            </button>
            <div v-if="expandedRiskId === alert.rule_id" class="risk-detail">
              <p class="preview-note">Evidence is limited to the API's desensitized summary. This page never loads health event payloads.</p>
              <p v-if="riskDetails[alert.rule_id]?.source_events.length === 0" class="empty-state">Evidence is unavailable for this signal.</p>
              <ul v-else class="source-list">
                <li v-for="source in riskDetails[alert.rule_id]?.source_events ?? []" :key="source.id">
                  <strong>{{ source.event_type }}</strong>
                  <span>{{ source.confirmation_status }}</span>
                  <span>{{ source.created_at ? new Date(source.created_at).toLocaleString() : 'Time unavailable' }}</span>
                </li>
              </ul>
            </div>
          </li>
        </ul>
      </template>
    </section>

    <footer>Teaching demonstration only. This page does not diagnose, prescribe, or make medication decisions.</footer>
  </main>
</template>
