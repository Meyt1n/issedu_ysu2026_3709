import { ref } from 'vue'

export type ThemeId = 'warm' | 'classic' | 'dusk' | 'sakura' | 'ocean'

export interface ThemeOption {
  id: ThemeId
  name: string
  tagline: string
  /** 切换器里的三个色点：背景 / 主色 / 点缀色 */
  swatches: [string, string, string]
}

export const THEMES: ThemeOption[] = [
  { id: 'warm', name: '暖阳纸笺', tagline: '默认 · 温馨纸感', swatches: ['#f6f1e6', '#38665a', '#c26744'] },
  { id: 'classic', name: '晨雾简白', tagline: '致敬第一版界面', swatches: ['#f3f6f4', '#0c5265', '#218269'] },
  { id: 'dusk', name: '青珀夜航', tagline: '夜间守护 · 深色', swatches: ['#1a231f', '#4fa98a', '#e0916a'] },
  { id: 'sakura', name: '樱语粉黛', tagline: '柔软粉调', swatches: ['#faf3f1', '#a8506c', '#d98a5f'] },
  { id: 'ocean', name: '海盐晨风', tagline: '清爽蓝绿', swatches: ['#edf3f4', '#1f6579', '#dd6f52'] },
]

const STORAGE_KEY = 'hct-theme'
const VALID_IDS = new Set<string>(THEMES.map(theme => theme.id))

export const currentTheme = ref<ThemeId>('warm')

export function applyTheme(id: ThemeId): void {
  currentTheme.value = id
  const root = globalThis.document?.documentElement
  if (root) {
    if (id === 'warm') root.removeAttribute('data-theme')
    else root.setAttribute('data-theme', id)
  }
  try {
    globalThis.localStorage?.setItem(STORAGE_KEY, id)
  } catch {
    // 无法持久化时主题仅对当前会话生效。
  }
}

export function initTheme(): void {
  let saved: string | null = null
  try {
    saved = globalThis.localStorage?.getItem(STORAGE_KEY) ?? null
  } catch {
    saved = null
  }
  if (saved && VALID_IDS.has(saved)) {
    applyTheme(saved as ThemeId)
  }
}
