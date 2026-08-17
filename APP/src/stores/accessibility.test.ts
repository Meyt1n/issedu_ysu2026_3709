import { beforeEach, describe, expect, it } from 'vitest'

import {
  A11Y_STORAGE_KEY,
  DEFAULT_SETTINGS,
  applySettingsToDocument,
  loadSettings,
  normalizeSettings,
  resetAccessibility,
  resolveTheme,
  setElderMode,
  setFontScale,
  setHighContrast,
  setTheme,
  useA11y,
} from './accessibility'

describe('无障碍设置 store', () => {
  beforeEach(() => {
    localStorage.clear()
    resetAccessibility()
  })

  it('默认关闭所有无障碍增强', () => {
    const { settings } = useA11y()
    expect(settings.elderMode).toBe(false)
    expect(settings.fontScale).toBe('standard')
    expect(settings.highContrast).toBe(false)
    expect(settings.voiceBroadcast).toBe(false)
    expect(settings.reduceMotion).toBe(false)
  })

  it('normalizeSettings 对异常输入回退默认值', () => {
    expect(normalizeSettings(null)).toEqual(DEFAULT_SETTINGS)
    expect(normalizeSettings('bad')).toEqual(DEFAULT_SETTINGS)
    expect(normalizeSettings({ fontScale: 'huge', elderMode: 'yes' })).toEqual(DEFAULT_SETTINGS)
    expect(normalizeSettings({ fontScale: 'large', highContrast: true })).toEqual({
      ...DEFAULT_SETTINGS,
      fontScale: 'large',
      highContrast: true,
    })
  })

  it('开启长辈模式会联动特大字号与语音播报，并写到 <html> 属性', () => {
    const { settings } = useA11y()
    setElderMode(true)

    expect(settings.elderMode).toBe(true)
    expect(settings.fontScale).toBe('xlarge')
    expect(settings.voiceBroadcast).toBe(true)

    const root = document.documentElement
    expect(root.dataset.elder).toBe('on')
    expect(root.dataset.fontScale).toBe('xlarge')
  })

  it('关闭长辈模式恢复字号与语音默认值，但保留对比度选择', () => {
    setHighContrast(true)
    setElderMode(true)
    setElderMode(false)

    const { settings } = useA11y()
    expect(settings.fontScale).toBe('standard')
    expect(settings.voiceBroadcast).toBe(false)
    expect(settings.highContrast).toBe(true)
  })

  it('设置会持久化到 localStorage 并可重新加载', () => {
    setFontScale('large')
    setHighContrast(true)

    const stored = localStorage.getItem(A11Y_STORAGE_KEY)
    expect(stored).toBeTruthy()

    const restored = loadSettings(localStorage)
    expect(restored.fontScale).toBe('large')
    expect(restored.highContrast).toBe(true)
  })

  it('applySettingsToDocument 写入对比度与动效属性', () => {
    applySettingsToDocument(
      { ...DEFAULT_SETTINGS, highContrast: true, reduceMotion: true },
      document,
    )
    expect(document.documentElement.dataset.contrast).toBe('high')
    expect(document.documentElement.dataset.motion).toBe('reduced')
  })

  it('外观默认为跟随系统，可切换为深色并写入 <html>', () => {
    const { settings } = useA11y()
    expect(settings.theme).toBe('auto')

    setTheme('dark')
    expect(settings.theme).toBe('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')

    setTheme('light')
    expect(document.documentElement.dataset.theme).toBe('light')
  })

  it('resolveTheme：auto 模式跟随系统深浅色，显式模式不受系统影响', () => {
    expect(resolveTheme('auto', true)).toBe('dark')
    expect(resolveTheme('auto', false)).toBe('light')
    expect(resolveTheme('dark', false)).toBe('dark')
    expect(resolveTheme('light', true)).toBe('light')
  })

  it('auto 模式下 apply 按系统深浅写入解析结果', () => {
    applySettingsToDocument({ ...DEFAULT_SETTINGS, theme: 'auto' }, document, true)
    expect(document.documentElement.dataset.theme).toBe('dark')
    applySettingsToDocument({ ...DEFAULT_SETTINGS, theme: 'auto' }, document, false)
    expect(document.documentElement.dataset.theme).toBe('light')
  })

  it('normalizeSettings 拒绝非法主题值', () => {
    expect(normalizeSettings({ theme: 'neon' }).theme).toBe('auto')
    expect(normalizeSettings({ theme: 'dark' }).theme).toBe('dark')
  })
})
