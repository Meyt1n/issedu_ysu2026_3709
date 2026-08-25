<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'

import { ApiClientError, apiClient } from '../api/client'
import type {
  AccessAudit,
  Authorization,
  AuthorizationAction,
  CreateAuthorizationInput,
  UpdateAuthorizationInput,
} from '../api/types'
import {
  AUTHORIZATION_TEMPLATES,
  PURPOSE_OPTIONS,
  PURPOSE_PATTERN,
  applyTemplate,
  auditActionLabel,
  auditOperationLabel,
  auditOutcomeLabel,
  auditReasonLabel,
  buildHandoffText,
  daysUntilExpiry,
  isExpiringSoon,
  purposeLabel,
  type AuthorizationTemplate,
} from '../authorization/authorizationTemplates'
import {
  isAuthorizationActive,
} from '../authorization/authorizationView'
import AppIcon from '../components/AppIcon.vue'
import {
  createIdempotencyKey,
  formatError,
  memberNames,
  pushToast,
  requestOptions,
  session,
} from '../store'
import { askConfirm } from '../ui/confirm'
import { formatDateTime, memberRoleLabel } from '../ui/labels'

const FIELD_OPTIONS = [
  { value: 'health_events', label: '已确认健康事件' },
  { value: 'risk_alerts', label: '风险确认回执' },
] as const

const ACTION_OPTIONS: Array<{ value: AuthorizationAction; label: string }> = [
  { value: 'READ_EVENTS', label: '查看已确认事件' },
  { value: 'WRITE_EVENTS', label: '追加已确认事件' },
  { value: 'ACK_RISK', label: '确认风险已知晓' },
]

const CUSTOM_PURPOSE = '__custom__'
const RENEW_DAYS = 30

const authorizations = ref<Authorization[]>([])
const audits = ref<AccessAudit[]>([])
const loading = ref(false)
const loadError = ref('')
const saving = ref(false)
const formError = ref('')
const selectedAuthorizationId = ref<string | null>(null)
const showAudits = ref(false)
const appliedTemplateId = ref<string | null>(null)
const purposeChoice = ref<string>('family-care')
const lastGrant = ref<{ authorization: Authorization; handoffText: string } | null>(null)
const handoffTextarea = ref<HTMLTextAreaElement | null>(null)

const draft = reactive({
  memberId: '',
  granteeActorId: '',
  dataFields: ['health_events'] as string[],
  actions: ['READ_EVENTS'] as AuthorizationAction[],
  purpose: 'family-care',
  validUntil: localDateTimeInput(7),
})

const selectedAuthorization = computed(
  () => authorizations.value.find(item => item.id === selectedAuthorizationId.value) ?? null,
)

const canSave = computed(
  () =>
    draft.memberId.length > 0 &&
    draft.granteeActorId.trim().length > 0 &&
    draft.dataFields.length > 0 &&
    draft.actions.length > 0 &&
    PURPOSE_PATTERN.test(draft.purpose) &&
    isFutureDate(draft.validUntil),
)

/** 家庭里已绑定账号的成员，作为「照护者账号」的选择建议；仍允许手工输入其它账号。 */
const caregiverSuggestions = computed(() =>
  session.members
    .filter(member => member.actor_id && member.actor_id !== session.actorId)
    .map(member => ({
      actorId: member.actor_id as string,
      displayName: member.display_name,
      role: memberRoleLabel(member.role),
    })),
)

function fieldLabel(value: string): string {
  return FIELD_OPTIONS.find(item => item.value === value)?.label ?? value
}

function actionLabel(value: string): string {
  return ACTION_OPTIONS.find(item => item.value === value)?.label ?? value
}

function describePurpose(purpose: string): string {
  const label = purposeLabel(purpose)
  return label === purpose ? purpose : `${label}（${purpose}）`
}

function localDateTimeInput(daysFromNow: number): string {
  const date = new Date()
  date.setDate(date.getDate() + daysFromNow)
  date.setSeconds(0, 0)
  const timezoneOffset = date.getTimezoneOffset() * 60_000
  return new Date(date.getTime() - timezoneOffset).toISOString().slice(0, 16)
}

function toLocalDateTimeInput(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return localDateTimeInput(7)
  const timezoneOffset = date.getTimezoneOffset() * 60_000
  return new Date(date.getTime() - timezoneOffset).toISOString().slice(0, 16)
}

function isFutureDate(value: string): boolean {
  const timestamp = Date.parse(value)
  return Number.isFinite(timestamp) && timestamp > Date.now()
}

function syncPurposeChoice(purpose: string): void {
  purposeChoice.value = PURPOSE_OPTIONS.some(option => option.code === purpose)
    ? purpose
    : CUSTOM_PURPOSE
}

function onPurposeChoiceChange(): void {
  if (purposeChoice.value !== CUSTOM_PURPOSE) {
    draft.purpose = purposeChoice.value
  } else if (PURPOSE_OPTIONS.some(option => option.code === draft.purpose)) {
    draft.purpose = ''
  }
}

function resetDraft(): void {
  selectedAuthorizationId.value = null
  formError.value = ''
  appliedTemplateId.value = null
  draft.memberId = session.members[0]?.id ?? ''
  draft.granteeActorId = ''
  draft.dataFields = ['health_events']
  draft.actions = ['READ_EVENTS']
  draft.purpose = 'family-care'
  draft.validUntil = localDateTimeInput(7)
  syncPurposeChoice(draft.purpose)
}

function useTemplate(template: AuthorizationTemplate): void {
  if (selectedAuthorization.value) return
  const applied = applyTemplate(template)
  draft.dataFields = applied.dataFields
  draft.actions = applied.actions
  draft.purpose = applied.purpose
  draft.validUntil = toLocalDateTimeInput(applied.validUntil)
  appliedTemplateId.value = template.id
  formError.value = ''
  lastGrant.value = null
  syncPurposeChoice(draft.purpose)
}

async function loadAuthorizations(): Promise<void> {
  const householdId = session.selectedHouseholdId
  if (!householdId || !session.isOwnerView) return

  loading.value = true
  loadError.value = ''
  try {
    authorizations.value = await apiClient.listAuthorizations(householdId, requestOptions.value)
    resetDraft()
  } catch (cause) {
    if (cause instanceof ApiClientError && cause.status === 404) {
      authorizations.value = []
    } else {
      loadError.value = formatError(cause)
    }
  } finally {
    loading.value = false
  }
}

async function loadAudits(): Promise<void> {
  const householdId = session.selectedHouseholdId
  if (!householdId) return
  try {
    audits.value = await apiClient.listAuthorizationAudits(householdId, requestOptions.value)
  } catch {
    audits.value = []
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
  appliedTemplateId.value = null
  lastGrant.value = null
  syncPurposeChoice(draft.purpose)
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

function buildGrantHandoff(authorization: Authorization): string {
  return buildHandoffText({
    granteeActorId: authorization.grantee_actor_id,
    memberName: memberNames.value.get(authorization.member_id) ?? '家庭成员',
    fieldLabels: authorization.data_fields.map(fieldLabel),
    actionLabels: authorization.actions.map(actionLabel),
    purposeCode: authorization.purpose,
    validUntilText: formatDateTime(authorization.valid_until),
  })
}

async function copyHandoff(): Promise<void> {
  const grant = lastGrant.value
  if (!grant) return
  try {
    await navigator.clipboard.writeText(grant.handoffText)
    pushToast('success', '交接说明已复制，可以发给对方了。')
  } catch {
    const textarea = handoffTextarea.value
    if (textarea) {
      textarea.focus()
      textarea.select()
      pushToast('info', '已选中说明文本，请按 Ctrl+C 复制。')
    } else {
      pushToast('error', '复制失败，请手动全选文本复制。')
    }
  }
}

async function saveAuthorization(): Promise<void> {
  if (!session.selectedHouseholdId || !canSave.value) {
    formError.value = '请完整选择成员、照护者账号、可见内容与允许操作，选择授权用途，并设置一个未来的到期时间。'
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
        session.selectedHouseholdId,
        existing.id,
        input,
        { ...requestOptions.value, idempotencyKey: createIdempotencyKey() },
      )
      authorizations.value = authorizations.value.map(item => (item.id === updated.id ? updated : item))
      pushToast('success', '授权已更新，照护者可见范围立即生效。')
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
        session.selectedHouseholdId,
        input,
        { ...requestOptions.value, idempotencyKey: createIdempotencyKey() },
      )
      authorizations.value = [...authorizations.value, created]
      lastGrant.value = { authorization: created, handoffText: buildGrantHandoff(created) }
      pushToast('success', '授权已创建，默认遵循最小权限原则。')
    }
    resetDraft()
    void loadAudits()
  } catch (cause) {
    formError.value = formatError(cause)
  } finally {
    saving.value = false
  }
}

async function renewAuthorization(authorization: Authorization): Promise<void> {
  if (!session.selectedHouseholdId || !isAuthorizationActive(authorization)) return

  const base = Math.max(Date.parse(authorization.valid_until), Date.now())
  const nextValidUntil = new Date(base + RENEW_DAYS * 86_400_000)
  const accepted = await askConfirm({
    title: `续期 ${RENEW_DAYS} 天？`,
    message: `「${memberNames.value.get(authorization.member_id) ?? '该成员'}」给 ${authorization.grantee_actor_id} 的授权将延长到 ${formatDateTime(nextValidUntil.toISOString())}，权限范围不变。`,
    confirmText: '确认续期',
  })
  if (!accepted) return

  saving.value = true
  try {
    const updated = await apiClient.updateAuthorization(
      session.selectedHouseholdId,
      authorization.id,
      { expected_version: authorization.version, valid_until: nextValidUntil.toISOString() },
      { ...requestOptions.value, idempotencyKey: createIdempotencyKey() },
    )
    authorizations.value = authorizations.value.map(item => (item.id === updated.id ? updated : item))
    pushToast('success', `授权已续期到 ${formatDateTime(updated.valid_until)}。`)
    void loadAudits()
  } catch (cause) {
    pushToast('error', formatError(cause))
  } finally {
    saving.value = false
  }
}

async function revokeAuthorization(authorization: Authorization): Promise<void> {
  if (!session.selectedHouseholdId || !isAuthorizationActive(authorization)) return

  const accepted = await askConfirm({
    title: '撤回这条授权？',
    message: `照护者 ${authorization.grantee_actor_id} 将立即失去对「${memberNames.value.get(authorization.member_id) ?? '该成员'}」相应字段的访问权限，撤回动作会写入审计记录。`,
    confirmText: '撤回授权',
  })
  if (!accepted) return

  saving.value = true
  try {
    const revoked = await apiClient.revokeAuthorization(
      session.selectedHouseholdId,
      authorization.id,
      authorization.version,
      { ...requestOptions.value, idempotencyKey: createIdempotencyKey() },
    )
    authorizations.value = authorizations.value.map(item => (item.id === revoked.id ? revoked : item))
    if (selectedAuthorizationId.value === authorization.id) resetDraft()
    if (lastGrant.value?.authorization.id === authorization.id) lastGrant.value = null
    pushToast('success', '授权已撤回，对应照护者立即失去访问权限。')
    void loadAudits()
  } catch (cause) {
    pushToast('error', formatError(cause))
  } finally {
    saving.value = false
  }
}

function grantStatus(authorization: Authorization): { label: string; tone: string } {
  if (isAuthorizationActive(authorization)) {
    if (isExpiringSoon(authorization)) {
      const days = daysUntilExpiry(authorization.valid_until)
      return { label: `即将到期 · 剩 ${days} 天`, tone: 'gold' }
    }
    return { label: `有效至 ${formatDateTime(authorization.valid_until)}`, tone: 'pine' }
  }
  if (authorization.revoked_at) return { label: '已撤回', tone: 'rose' }
  return { label: '已过期', tone: 'plain' }
}

watch(
  () => session.selectedHouseholdId,
  () => {
    lastGrant.value = null
    void loadAuthorizations()
    void loadAudits()
  },
)

onMounted(() => {
  void loadAuthorizations()
  void loadAudits()
})
</script>

<template>
  <section class="page-hero">
    <div class="card-heading" style="margin-bottom: 0">
      <div>
        <h2 class="hero-greeting">授权管理</h2>
        <p class="hero-sub">
          决定家里谁能看到哪些健康内容、能做什么、什么时候到期；撤回立即生效。
        </p>
        <p v-if="session.isOwnerView" class="hero-sub review-session-meta">
          登录 <strong>{{ session.actorId }}</strong>
          · 用途 <strong>{{ purposeLabel(session.accessPurpose) }}</strong>（{{ session.accessPurpose || '未填' }}）
          · <span class="pill pine" style="display: inline-flex; margin-left: 4px">可管授权</span>
        </p>
      </div>
    </div>
  </section>

  <template v-if="!session.isOwnerView">
    <section class="card">
      <div class="card-heading">
        <div>
          <p class="eyebrow">当前会话</p>
          <h3 class="card-title">你的权限范围</h3>
        </div>
        <span class="pill sky">仅授权可见</span>
      </div>
      <p class="card-note" style="margin-top: -2px">
        登录 <strong>{{ session.actorId }}</strong>
        · 用途 <strong>{{ purposeLabel(session.accessPurpose) }}</strong>
        （{{ session.accessPurpose || '未填' }}）。服务端只返回已授权内容。
      </p>
      <ul class="list-plain" style="margin-top: 12px">
        <li v-for="member in session.members" :key="member.id" class="row-card">
          <span class="row-title">
            <AppIcon name="members" :size="17" style="color: var(--pine)" />
            {{ member.display_name }}
            <span class="pill sage">{{ memberRoleLabel(member.role) }}</span>
          </span>
          <p class="row-meta" style="margin: 4px 0 0">
            可见内容由家庭管理员配置；用途不一致时读不到字段。
          </p>
        </li>
      </ul>
      <div v-if="session.members.length === 0" class="empty-state">
        <AppIcon class="empty-art" name="lock" :size="32" />
        <strong>当前身份与用途下没有可见成员</strong>
        <p>请与家庭管理员确认授权是否匹配。</p>
      </div>
    </section>
  </template>

  <template v-else>
    <p v-if="loadError" class="notice error" role="alert">
      <AppIcon name="alert" :size="16" />
      {{ loadError }}
    </p>

    <div class="grid-main-side">
      <div class="section-stack">
        <section class="card">
          <div class="card-heading">
            <div>
              <p class="eyebrow">当前范围</p>
              <h3 class="card-title">已配置的授权</h3>
            </div>
            <div class="heading-actions">
              <button type="button" class="btn btn-ghost btn-small" :disabled="loading" @click="loadAuthorizations">
                <AppIcon name="refresh" :size="15" />
                刷新
              </button>
            </div>
          </div>

          <div v-if="loading" class="inline-loading">
            <span class="loading-dots"><span /><span /><span /></span>
            正在读取授权
          </div>
          <div v-else-if="authorizations.length === 0" class="empty-state auth-empty-state">
            <AppIcon class="empty-art" name="key" :size="32" />
            <strong>还没有为照护者创建授权</strong>
            <p>从一个常见场景开始，权限默认最小、随时可撤回：</p>
            <div class="auth-empty-templates">
              <button
                v-for="template in AUTHORIZATION_TEMPLATES"
                :key="template.id"
                type="button"
                class="btn btn-ghost btn-small"
                @click="useTemplate(template)"
              >
                {{ template.name }}
              </button>
            </div>
            <p class="text-faint" style="font-size: 12px; margin: 8px 0 0">
              点击后右侧表单会自动填好，可再逐项调整。
            </p>
          </div>
          <ul v-else class="list-plain">
            <li
              v-for="authorization in authorizations"
              :key="authorization.id"
              class="row-card auth-grant-card"
              :class="{ selected: selectedAuthorizationId === authorization.id }"
              @click="editAuthorization(authorization)"
            >
              <div class="row-top">
                <span class="row-title">
                  <span class="auth-grant-pair">
                    {{ memberNames.get(authorization.member_id) ?? '已授权成员' }}
                    <AppIcon name="arrow-right" :size="14" style="color: var(--ink-faint)" />
                    <code class="auth-actor-id">{{ authorization.grantee_actor_id }}</code>
                  </span>
                </span>
                <span class="pill" :class="grantStatus(authorization).tone">{{ grantStatus(authorization).label }}</span>
              </div>
              <p class="row-meta" style="margin: 0">
                能看：{{ authorization.data_fields.map(fieldLabel).join('、') }} ·
                能做：{{ authorization.actions.map(actionLabel).join('、') }}<br />
                用途：{{ describePurpose(authorization.purpose) }} · 版本 v{{ authorization.version }}
              </p>
              <div class="row-actions" @click.stop>
                <button
                  type="button"
                  class="btn btn-ghost btn-small"
                  :disabled="saving || !isAuthorizationActive(authorization)"
                  @click="editAuthorization(authorization)"
                >
                  编辑
                </button>
                <button
                  type="button"
                  class="btn btn-ghost btn-small"
                  :disabled="saving || !isAuthorizationActive(authorization)"
                  @click="renewAuthorization(authorization)"
                >
                  续期 30 天
                </button>
                <button
                  type="button"
                  class="btn btn-danger btn-small"
                  :disabled="saving || !isAuthorizationActive(authorization)"
                  @click="revokeAuthorization(authorization)"
                >
                  撤回授权
                </button>
              </div>
            </li>
          </ul>
        </section>

        <section class="card">
          <div class="card-heading">
            <div>
              <p class="eyebrow">审计留痕</p>
              <h3 class="card-title">授权与访问记录</h3>
            </div>
            <button type="button" class="btn btn-ghost btn-small" @click="showAudits = !showAudits; if (showAudits) loadAudits()">
              {{ showAudits ? '收起' : `展开（${audits.length}）` }}
            </button>
          </div>
          <template v-if="showAudits">
            <p v-if="audits.length === 0" class="card-note">暂无审计记录。</p>
            <ul v-else class="timeline">
              <li v-for="audit in audits.slice(0, 20)" :key="audit.id" class="timeline-row">
                <span class="timeline-dot" :class="audit.outcome === 'SUCCESS' || audit.outcome === 'ALLOWED' ? 'pine' : 'rose'" />
                <div class="timeline-body">
                  <div class="timeline-title-row">
                    <span class="timeline-event">
                      {{ auditOperationLabel(audit.operation) }} · {{ auditActionLabel(audit.action) }}
                    </span>
                    <span class="pill" :class="audit.outcome === 'SUCCESS' || audit.outcome === 'ALLOWED' ? 'pine' : 'rose'">
                      {{ auditOutcomeLabel(audit.outcome) }}
                    </span>
                  </div>
                  <span class="timeline-meta" :title="audit.reason ?? undefined">
                    {{ audit.actor_id }} · {{ fieldLabel(audit.data_field) }}{{ audit.reason ? ` · ${auditReasonLabel(audit.reason)}` : '' }} ·
                    {{ formatDateTime(audit.created_at) }}
                  </span>
                </div>
              </li>
            </ul>
          </template>
          <p v-else class="card-note" style="margin: 0">
            谁在什么时候访问或修改了哪些授权内容、被允许还是被拒绝，都会留痕；点「展开」查看。
          </p>
        </section>
      </div>

      <section class="card" style="align-self: start">
        <div v-if="lastGrant" class="auth-success-panel" role="status">
          <div class="row-top" style="align-items: center">
            <span class="row-title">
              <AppIcon name="check" :size="17" style="color: var(--pine)" />
              授权已生效，接下来交给对方
            </span>
            <button type="button" class="btn btn-ghost btn-small" @click="lastGrant = null">关闭</button>
          </div>
          <ol class="auth-success-steps">
            <li>
              请对方用账号
              <code class="auth-actor-id">{{ lastGrant.authorization.grantee_actor_id }}</code>
              登录家健镜；
            </li>
            <li>
              登录页「访问用途代码」填
              <strong>{{ lastGrant.authorization.purpose }}</strong>
              （{{ purposeLabel(lastGrant.authorization.purpose) }}），必须一致才能看到内容；
            </li>
            <li>
              授权到 {{ formatDateTime(lastGrant.authorization.valid_until) }} 自动失效；
              随时可在左侧列表撤回或续期。
            </li>
          </ol>
          <textarea
            ref="handoffTextarea"
            class="auth-handoff-text"
            readonly
            rows="7"
            aria-label="授权交接说明"
            :value="lastGrant.handoffText"
          />
          <button type="button" class="btn btn-primary btn-small" @click="copyHandoff">
            复制说明发给对方
          </button>
        </div>

        <div class="card-heading">
          <div>
            <p class="eyebrow">授权编辑器</p>
            <h3 class="card-title">{{ selectedAuthorization ? '编辑授权' : '新建授权' }}</h3>
          </div>
          <button v-if="selectedAuthorization" type="button" class="btn btn-ghost btn-small" @click="resetDraft">
            改为新建
          </button>
        </div>

        <div v-if="selectedAuthorization" class="auth-selected-preview">
          <p class="eyebrow" style="margin: 0">对方能看到什么</p>
          <p class="card-note" style="margin: 6px 0 0">
            <code class="auth-actor-id">{{ selectedAuthorization.grantee_actor_id }}</code>
            可见：{{ selectedAuthorization.data_fields.map(fieldLabel).join('、') }}；
            可做：{{ selectedAuthorization.actions.map(actionLabel).join('、') }}；
            用途 {{ purposeLabel(selectedAuthorization.purpose) }}。
          </p>
        </div>

        <div v-if="!selectedAuthorization" class="auth-template-block">
          <p class="eyebrow" style="margin: 0 0 6px">按场景快速填写</p>
          <div class="auth-template-list">
            <button
              v-for="template in AUTHORIZATION_TEMPLATES"
              :key="template.id"
              type="button"
              class="auth-template-chip"
              :class="{ active: appliedTemplateId === template.id }"
              @click="useTemplate(template)"
            >
              <strong>{{ template.name }}</strong>
              <span>{{ template.description }}</span>
            </button>
          </div>
          <p class="text-faint" style="font-size: 12px; margin: 6px 0 0">
            模板只是起点：不包含「追加事件」等写权限，套用后仍可逐项调整。
          </p>
        </div>

        <form class="section-stack" @submit.prevent="saveAuthorization">
          <label class="field">
            照护者账号
            <input
              v-model="draft.granteeActorId"
              autocomplete="off"
              required
              placeholder="例如 child-1"
              list="caregiver-account-options"
              :disabled="Boolean(selectedAuthorization)"
            />
            <datalist id="caregiver-account-options">
              <option
                v-for="suggestion in caregiverSuggestions"
                :key="suggestion.actorId"
                :value="suggestion.actorId"
                :label="`${suggestion.displayName}（${suggestion.role}）`"
              />
            </datalist>
            <small>对方登录家健镜时使用的账号；家庭里已绑定账号的成员会出现在建议里。</small>
          </label>
          <label class="field">
            家庭成员
            <select v-model="draft.memberId" required :disabled="Boolean(selectedAuthorization)">
              <option v-for="member in session.members" :key="member.id" :value="member.id">
                {{ member.display_name }}
              </option>
            </select>
          </label>
          <fieldset>
            <legend>对方能看到的内容</legend>
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
            <legend>对方能做的操作</legend>
            <label v-for="action in ACTION_OPTIONS" :key="action.value" class="check-row">
              <input
                type="checkbox"
                :checked="draft.actions.includes(action.value)"
                @change="updateSelectedActions(action.value, ($event.target as HTMLInputElement).checked)"
              />
              {{ action.label }}
            </label>
          </fieldset>
          <label class="field">
            授权用途
            <select v-model="purposeChoice" required @change="onPurposeChoiceChange">
              <option v-for="option in PURPOSE_OPTIONS" :key="option.code" :value="option.code">
                {{ option.label }}（{{ option.code }}）
              </option>
              <option :value="CUSTOM_PURPOSE">自定义代码…</option>
            </select>
            <small v-if="purposeChoice !== CUSTOM_PURPOSE">
              {{ PURPOSE_OPTIONS.find(option => option.code === purposeChoice)?.description }}；
              对方登录时填写的用途代码必须与这里一致。
            </small>
          </label>
          <label v-if="purposeChoice === CUSTOM_PURPOSE" class="field">
            自定义用途代码
            <input
              v-model="draft.purpose"
              pattern="[A-Za-z0-9][A-Za-z0-9._:-]{0,63}"
              required
              placeholder="例如 rehab-support"
              autocomplete="off"
            />
            <small>字母或数字开头，可含点、下划线、冒号、连字符；对方访问时必须填写同一代码。</small>
          </label>
          <label class="field">
            到期时间
            <input v-model="draft.validUntil" type="datetime-local" required />
            <small>到期后对方自动看不到内容；可随时在左侧续期或撤回。</small>
          </label>
          <p v-if="formError" class="notice error" role="alert">
            <AppIcon name="alert" :size="16" />
            {{ formError }}
          </p>
          <button type="submit" class="btn btn-primary" :disabled="saving || !canSave">
            {{ saving ? '正在保存' : selectedAuthorization ? '保存修改' : '创建授权' }}
          </button>
          <p class="text-faint" style="font-size: 12px; line-height: 1.5; margin: 0">
            默认最小权限；撤回后对方立即看不到相应字段。
          </p>
        </form>
      </section>
    </div>
  </template>
</template>

<style scoped>
/* 图七：右侧授权表单更紧凑——勾选项两列排布、缩小纵向间距。 */
form.section-stack { gap: 10px; }

fieldset {
  column-gap: 12px;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
}

fieldset legend { padding: 0 4px; }

fieldset .check-row { margin: 5px 0; }

.auth-grant-card .row-actions { margin-top: 8px; }
</style>
