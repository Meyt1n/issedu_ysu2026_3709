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
  buildAuthorizationPreview,
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

const purposePattern = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/

const authorizations = ref<Authorization[]>([])
const audits = ref<AccessAudit[]>([])
const loading = ref(false)
const loadError = ref('')
const saving = ref(false)
const formError = ref('')
const selectedAuthorizationId = ref<string | null>(null)
const previewActorId = ref('')
const showAudits = ref(false)

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

const authorizationPreview = computed(() => {
  const previewActor = previewActorId.value.trim()
  if (!previewActor) return []
  return buildAuthorizationPreview(authorizations.value, previewActor).map(scope => ({
    ...scope,
    memberName: memberNames.value.get(scope.memberId) ?? '已授权成员',
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

function resetDraft(): void {
  selectedAuthorizationId.value = null
  formError.value = ''
  draft.memberId = session.members[0]?.id ?? ''
  draft.granteeActorId = ''
  draft.dataFields = ['health_events']
  draft.actions = ['READ_EVENTS']
  draft.purpose = 'family-care'
  draft.validUntil = localDateTimeInput(7)
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
  if (!session.selectedHouseholdId || !canSave.value) {
    formError.value = '请完整选择成员、照护者身份、字段与动作，填写合法用途代码，并设置一个未来的到期时间。'
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
    return { label: `有效至 ${formatDateTime(authorization.valid_until)}`, tone: 'pine' }
  }
  if (authorization.revoked_at) return { label: '已撤回', tone: 'rose' }
  return { label: '已过期', tone: 'plain' }
}

watch(
  () => session.selectedHouseholdId,
  () => {
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
          子女与照护者只能看到被精细授权的字段。授权始终标注可见范围、用途与到期时间，撤回立即生效。
        </p>
      </div>
    </div>
  </section>

  <template v-if="!session.isOwnerView">
    <section class="card">
      <div class="card-heading">
        <div>
          <p class="eyebrow">照护者视图</p>
          <h3 class="card-title">当前身份的可见范围</h3>
        </div>
        <span class="pill sky">API 已过滤</span>
      </div>
      <p class="card-note" style="margin-top: -6px">
        只有 API 决定某位成员或事件是否返回；本页不会推断或展示未授权的字段。你当前可以看到以下成员：
      </p>
      <ul class="list-plain" style="margin-top: 14px">
        <li v-for="member in session.members" :key="member.id" class="row-card">
          <span class="row-title">
            <AppIcon name="members" :size="17" style="color: var(--pine)" />
            {{ member.display_name }}
            <span class="pill sage">{{ memberRoleLabel(member.role) }}</span>
          </span>
        </li>
      </ul>
      <div v-if="session.members.length === 0" class="empty-state">
        <AppIcon class="empty-art" name="lock" :size="38" />
        <strong>当前身份与用途代码下没有可见成员</strong>
        <p>请与家庭管理员确认授权的成员、字段、动作与用途代码是否匹配。</p>
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
          <div v-else-if="authorizations.length === 0" class="empty-state">
            <AppIcon class="empty-art" name="key" :size="38" />
            <strong>还没有为照护者创建授权</strong>
            <p>在右侧创建第一条授权。默认最小权限，不存在「一键开放全部健康资料」。</p>
          </div>
          <ul v-else class="list-plain">
            <li v-for="authorization in authorizations" :key="authorization.id" class="row-card">
              <div class="row-top">
                <span class="row-title">
                  {{ memberNames.get(authorization.member_id) ?? '已授权成员' }}
                  <AppIcon name="arrow-right" :size="14" style="color: var(--ink-faint)" />
                  {{ authorization.grantee_actor_id }}
                </span>
                <span class="pill" :class="grantStatus(authorization).tone">{{ grantStatus(authorization).label }}</span>
              </div>
              <p class="row-meta" style="margin: 0">
                字段：{{ authorization.data_fields.join('、') }} ·
                动作：{{ authorization.actions.map(a => ACTION_OPTIONS.find(o => o.value === a)?.label ?? a).join('、') }}<br />
                用途代码：{{ authorization.purpose }} · 版本 v{{ authorization.version }}
              </p>
              <div class="row-actions">
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
              <p class="eyebrow">照护者预览</p>
              <h3 class="card-title">对方能看到什么</h3>
            </div>
          </div>
          <label class="field">
            输入照护者身份查看其可见范围
            <input v-model="previewActorId" autocomplete="off" placeholder="照护者身份标识，例如 child-1" />
            <small>预览只使用授权元数据，不会加载任何健康事件内容；字段过滤始终由 API 负责。</small>
          </label>
          <p v-if="previewActorId && authorizationPreview.length === 0" class="notice warn" style="margin-top: 12px">
            <AppIcon name="info" :size="15" />
            该照护者当前没有任何有效授权字段。
          </p>
          <ul v-else-if="authorizationPreview.length > 0" class="list-plain" style="margin-top: 12px">
            <li v-for="scope in authorizationPreview" :key="scope.authorizationId" class="row-card">
              <span class="row-title">{{ scope.memberName }}</span>
              <p class="row-meta" style="margin: 0">
                可见字段：{{ scope.fields.join('、') }} · 允许动作：{{ scope.actions.join('、') }}<br />
                用途 {{ scope.purpose }} · 有效至 {{ formatDateTime(scope.validUntil) }}
              </p>
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
                    <span class="timeline-event">{{ audit.operation }} · {{ audit.action }}</span>
                    <span class="pill" :class="audit.outcome === 'SUCCESS' || audit.outcome === 'ALLOWED' ? 'pine' : 'rose'">
                      {{ audit.outcome }}
                    </span>
                  </div>
                  <span class="timeline-meta">
                    {{ audit.actor_id }} · {{ audit.data_field }}{{ audit.reason ? ` · ${audit.reason}` : '' }} ·
                    {{ formatDateTime(audit.created_at) }}
                  </span>
                </div>
              </li>
            </ul>
          </template>
          <p v-else class="card-note" style="margin: 0">
            每一次授权变更与访问判定都会留痕，包括被拒绝的访问及其原因。
          </p>
        </section>
      </div>

      <section class="card" style="align-self: start">
        <div class="card-heading">
          <div>
            <p class="eyebrow">授权编辑器</p>
            <h3 class="card-title">{{ selectedAuthorization ? '编辑授权' : '新建授权' }}</h3>
          </div>
          <button v-if="selectedAuthorization" type="button" class="btn btn-ghost btn-small" @click="resetDraft">
            改为新建
          </button>
        </div>

        <form class="section-stack" @submit.prevent="saveAuthorization">
          <label class="field">
            照护者身份标识
            <input v-model="draft.granteeActorId" autocomplete="off" required placeholder="例如 child-1" :disabled="Boolean(selectedAuthorization)" />
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
            <legend>数据字段</legend>
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
            <legend>允许动作</legend>
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
            用途代码
            <input v-model="draft.purpose" pattern="[A-Za-z0-9][A-Za-z0-9._:-]{0,63}" required placeholder="family-care" />
            <small>ASCII 代码，1–64 位：字母、数字、点、下划线、冒号或连字符。照护者访问时需携带一致的用途。</small>
          </label>
          <label class="field">
            到期时间
            <input v-model="draft.validUntil" type="datetime-local" required />
          </label>
          <p v-if="formError" class="notice error" role="alert">
            <AppIcon name="alert" :size="16" />
            {{ formError }}
          </p>
          <button type="submit" class="btn btn-primary" :disabled="saving || !canSave">
            {{ saving ? '正在保存' : selectedAuthorization ? '保存修改' : '创建授权' }}
          </button>
          <p class="text-faint" style="font-size: 12px; line-height: 1.6; margin: 0">
            默认最小权限。授权、修改与撤回全部写入审计记录；撤回后照护者页面与 API 会立即隐藏相应字段。
          </p>
        </form>
      </section>
    </div>
  </template>
</template>
