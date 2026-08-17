import { reactive } from 'vue'

export type DataMode = 'demo' | 'live'

export interface SessionSettings {
  /** demo=内置虚构演示数据；live=连接家庭服务器（主仓库 FastAPI） */
  dataMode: DataMode
  /** 联机模式 API 基地址；留空表示同源（配合部署或 dev 代理） */
  serverBaseUrl: string
  actorId: string
  accessPurpose: string
  /** 紧急联系人（本地保存，仅用于拨号按钮） */
  caregiverName: string
  caregiverPhone: string
  /** 当前正在查看/照护的成员 */
  currentMemberId: string
}

export const SESSION_STORAGE_KEY = 'hct-mobile.session.v1'

export const DEFAULT_SESSION: SessionSettings = {
  dataMode: 'demo',
  serverBaseUrl: '',
  actorId: '',
  accessPurpose: 'family-care',
  caregiverName: '',
  caregiverPhone: '',
  currentMemberId: '',
}

export function normalizeSession(raw: unknown): SessionSettings {
  if (typeof raw !== 'object' || raw === null) return { ...DEFAULT_SESSION }
  const record = raw as Record<string, unknown>
  const text = (value: unknown, fallback: string): string =>
    typeof value === 'string' ? value : fallback
  return {
    dataMode: record.dataMode === 'live' ? 'live' : 'demo',
    serverBaseUrl: text(record.serverBaseUrl, ''),
    actorId: text(record.actorId, ''),
    accessPurpose: text(record.accessPurpose, 'family-care') || 'family-care',
    caregiverName: text(record.caregiverName, ''),
    caregiverPhone: text(record.caregiverPhone, ''),
    currentMemberId: text(record.currentMemberId, ''),
  }
}

function load(): SessionSettings {
  if (typeof localStorage === 'undefined') return { ...DEFAULT_SESSION }
  try {
    const text = localStorage.getItem(SESSION_STORAGE_KEY)
    if (!text) return { ...DEFAULT_SESSION }
    return normalizeSession(JSON.parse(text))
  } catch {
    return { ...DEFAULT_SESSION }
  }
}

const state = reactive<SessionSettings>(load())

function persist(): void {
  if (typeof localStorage === 'undefined') return
  try {
    localStorage.setItem(SESSION_STORAGE_KEY, JSON.stringify(state))
  } catch {
    // 存储不可用时静默降级。
  }
}

export function updateSession(patch: Partial<SessionSettings>): void {
  Object.assign(state, patch)
  persist()
}

export function resetSession(): void {
  Object.assign(state, { ...DEFAULT_SESSION })
  persist()
}

export function useSession() {
  return { session: state, updateSession, resetSession }
}
