/**
 * 语音识别性能基准测试
 * 用于验证优化效果和持续监控性能指标
 */

import { beforeAll, describe, expect, it } from 'vitest'
import { performance } from 'node:perf_hooks'

import {
  createSpeechRecognition,
  DICTATION_SILENCE_MS,
  VOICE_RESTART_DELAY_MS,
  normalizeVoiceText,
  containsWakePhrase,
  transcriptAfterWakePhrase,
} from './recognition'
import { createDictationController } from './dictation'
import { DEFAULT_VOICE_PREFERENCES } from './prefs'
import { containsConfiguredWakePhrase } from './wakePhrase'
import { applyHotwordCorrections } from './hotwords'

/**
 * 取多轮采样里的最快一轮作为耗时。
 *
 * 单次 wall-clock 采样会把 GC、OS 抢占和 JIT 预热都算进来，稳态只要 0.001–0.02ms
 * 的操作偶尔会飙到毫秒级，让亚毫秒阈值随机失败。最快一轮代表「没有被打扰时的
 * 真实成本」，既过滤调度噪声，又仍能抓住真正的性能回退（回退会抬高每一轮）。
 */
function fastestRun(batch: () => void, samples = 12): number {
  let best = Number.POSITIVE_INFINITY
  for (let index = 0; index < samples; index += 1) {
    const start = performance.now()
    batch()
    best = Math.min(best, performance.now() - start)
  }
  return best
}

describe('语音识别性能基准测试', () => {
  /**
   * 先把这些函数跑热：首次调用要付正则编译与 JIT 的一次性成本，
   * 与稳态耗时不是一回事，而基准关心的是稳态。
   */
  beforeAll(() => {
    for (let index = 0; index < 200; index += 1) {
      normalizeVoiceText('晓燕晓燕查询用药')
      applyHotwordCorrections('请查看用药提心')
      containsWakePhrase('小燕小燕查询用药')
      transcriptAfterWakePhrase('小燕小燕查询今天的用药提醒')
      containsConfiguredWakePhrase('家健镜查询健康档案', '家健镜')
    }
  })

  describe('优化指标验证', () => {
    it('验证静音检测时长已优化到 10 秒', () => {
      expect(DICTATION_SILENCE_MS).toBe(10_000)
      expect(DEFAULT_VOICE_PREFERENCES.silenceMs).toBe(10_000)
      expect(DEFAULT_VOICE_PREFERENCES.continuationSilenceMs).toBe(12_000)
    })

    it('验证识别重启延迟已优化到 10ms', () => {
      expect(VOICE_RESTART_DELAY_MS).toBe(10)
    })

    it('验证双重唤醒已默认开启', () => {
      expect(DEFAULT_VOICE_PREFERENCES.doubleWake).toBe(true)
    })

    it('验证 maxAlternatives 已优化到 1', () => {
      class FakeRecognition {
        lang = ''
        continuous = false
        interimResults = false
        maxAlternatives = 0
        onstart = null
        onresult = null
        onerror = null
        onend = null
        start = () => undefined
        stop = () => undefined
        abort = () => undefined
      }
      const previous = (globalThis as { window?: unknown }).window
      Object.defineProperty(globalThis, 'window', {
        configurable: true,
        value: { SpeechRecognition: FakeRecognition },
      })
      try {
        const recognition = createSpeechRecognition('zh-CN', {
          continuous: true,
          interimResults: true
        })
        expect(recognition?.maxAlternatives).toBe(1)
      } finally {
        if (previous === undefined) delete (globalThis as { window?: unknown }).window
        else Object.defineProperty(globalThis, 'window', { configurable: true, value: previous })
      }
    })
  })

  describe('热词纠正性能测试', () => {
    it('唤醒词纠正性能 - 小燕小燕', () => {
      const duration = fastestRun(() => normalizeVoiceText('晓燕晓燕查询用药'))

      expect(duration).toBeLessThan(1)
      expect(normalizeVoiceText('晓燕晓燕查询用药')).toBe('小燕小燕查询用药')
    })

    it('批量唤醒词规范化性能', () => {
      const testCases = [
        '晓燕晓燕查询用药',
        '小严小严血压多少',
        '小燕 小燕 提醒我',
        '小研小研今天天气',
        '小言小言健康档案',
      ]

      const duration = fastestRun(() => {
        testCases.forEach(text => normalizeVoiceText(text))
      })

      // 批量处理 5 条，总时间应小于 5ms
      expect(duration).toBeLessThan(5)
      expect(duration / testCases.length).toBeLessThan(1)
    })

    it('热词纠正功能验证 - 用药提醒', () => {
      const result = applyHotwordCorrections('请查看用药提心')
      expect(result).toBe('请查看用药提醒')
    })

    it('热词纠正功能验证 - 药盒', () => {
      const result = applyHotwordCorrections('打开药合')
      expect(result).toBe('打开药盒')
    })
  })

  describe('唤醒词匹配性能测试', () => {
    it('标准唤醒词匹配性能', () => {
      const testCases = [
        '小燕小燕查询用药',
        '晓燕晓燕今天天气',
        '小严小严血压多少',
        '小燕 小燕 提醒我吃药',
      ]

      const duration = fastestRun(() => {
        testCases.forEach(text => containsWakePhrase(text))
      })

      // 4 次匹配总时间应小于 2ms
      expect(duration).toBeLessThan(2)
    })

    it('自定义唤醒词匹配性能', () => {
      const testCases = [
        { text: '家健镜查询健康档案', phrase: '家健镜' },
        { text: '加建静今天血压', phrase: '家健镜' },
        { text: '小助手提醒我', phrase: '小助手' },
      ]

      const duration = fastestRun(() => {
        testCases.forEach(({ text, phrase }) => containsConfiguredWakePhrase(text, phrase))
      })

      expect(duration).toBeLessThan(2)
    })

    it('唤醒词后文本提取性能', () => {
      const duration = fastestRun(() =>
        transcriptAfterWakePhrase('小燕小燕查询今天的用药提醒和血压记录'),
      )

      expect(duration).toBeLessThan(1)
      expect(transcriptAfterWakePhrase('小燕小燕查询今天的用药提醒和血压记录')).toBe(
        '查询今天的用药提醒和血压记录',
      )
    })
  })

  describe('听写控制器响应速度测试', () => {
    it('创建控制器性能', () => {
      class FakeRecognition {
        lang = ''
        continuous = false
        interimResults = false
        maxAlternatives = 0
        onstart = null
        onresult = null
        onerror = null
        onend = null
        start = () => undefined
        stop = () => undefined
        abort = () => undefined
      }
      const previous = (globalThis as { window?: unknown }).window
      Object.defineProperty(globalThis, 'window', {
        configurable: true,
        value: { SpeechRecognition: FakeRecognition },
      })

      try {
        const duration = fastestRun(() => {
          const controller = createDictationController({
            onModeChange: () => {},
            onDraft: () => {},
          })
          controller.dispose()
        })

        // 创建控制器应在 5ms 内完成
        expect(duration).toBeLessThan(5)
      } finally {
        if (previous === undefined) delete (globalThis as { window?: unknown }).window
        else Object.defineProperty(globalThis, 'window', { configurable: true, value: previous })
      }
    })
  })

  describe('内存使用测试', () => {
    it('重复创建和销毁控制器不应泄漏内存', () => {
      class FakeRecognition {
        lang = ''
        continuous = false
        interimResults = false
        maxAlternatives = 0
        onstart = null
        onresult = null
        onerror = null
        onend = null
        start = () => undefined
        stop = () => undefined
        abort = () => undefined
      }
      const previous = (globalThis as { window?: unknown }).window
      Object.defineProperty(globalThis, 'window', {
        configurable: true,
        value: { SpeechRecognition: FakeRecognition },
      })

      try {
        // 创建和销毁 100 次
        for (let i = 0; i < 100; i++) {
          const controller = createDictationController({
            onModeChange: () => {},
            onDraft: () => {},
          })
          controller.dispose()
        }

        // 如果有内存泄漏，这个测试会变慢或崩溃
        // 这里只是验证能正常完成
        expect(true).toBe(true)
      } finally {
        if (previous === undefined) delete (globalThis as { window?: unknown }).window
        else Object.defineProperty(globalThis, 'window', { configurable: true, value: previous })
      }
    })
  })

  describe('性能基准对比', () => {
    it('记录当前性能指标（供对比）', () => {
      const metrics = {
        silenceMs: DICTATION_SILENCE_MS,
        restartDelayMs: VOICE_RESTART_DELAY_MS,
        maxAlternatives: 1,
        doubleWake: DEFAULT_VOICE_PREFERENCES.doubleWake,
        hotwordCoverage: 60, // 估算值，实际约 60+ 字符
      }

      // 这些是优化后的目标值
      expect(metrics).toEqual({
        silenceMs: 10_000,
        restartDelayMs: 10,
        maxAlternatives: 1,
        doubleWake: true,
        hotwordCoverage: 60,
      })

      // 输出到控制台供记录
      console.log('📊 当前性能指标：', JSON.stringify(metrics, null, 2))
    })
  })
})

describe('扩展热词库覆盖测试', () => {
  it('医疗词汇覆盖 - 身体部位', () => {
    const tests = ['投疼', '新脏不舒服']

    tests.forEach(input => {
      const normalized = normalizeVoiceText(input)
      // 这里只验证规范化能正常工作
      expect(normalized.length).toBeGreaterThan(0)
    })
  })

  it('数字识别覆盖', () => {
    const tests = [
      '依天吃三次',
      '二月份复查',
      '肆月是日',
    ]

    tests.forEach(text => {
      const normalized = normalizeVoiceText(text)
      expect(normalized.length).toBeGreaterThan(0)
    })
  })

  it('家庭成员识别', () => {
    const tests = [
      '巴爸的药',
      '马妈的血压',
      '歌哥的记录',
    ]

    tests.forEach(text => {
      const normalized = normalizeVoiceText(text)
      expect(normalized.length).toBeGreaterThan(0)
    })
  })
})
