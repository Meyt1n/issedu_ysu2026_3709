import { describe, expect, it } from 'vitest'

import {
  isMemberTaskActive,
  isMemberTaskNeedsRetake,
  memberVisionStatusHint,
  memberVisionStatusLabel,
} from './memberStatus'

const INTERNAL_CODES = [
  'queued',
  'running',
  'succeeded',
  'failed',
  'timeout',
  'cancelled',
  'MATCHED',
  'CONFLICT',
  'UNKNOWN',
  'REVIEW',
  'LOW_QUALITY',
  'READY_FOR_FUSION',
  'PENDING_REVIEW',
  'UNCONFIRMED',
  'OCR',
]

describe('成员前台状态文案映射（HCT-439 阶段二）', () => {
  it('把排队/处理中的任务映射为生活化“正在看照片”', () => {
    expect(memberVisionStatusLabel('queued')).toBe('正在看照片')
    expect(memberVisionStatusLabel('running')).toBe('正在看照片')
    expect(isMemberTaskActive('queued')).toBe(true)
    expect(isMemberTaskActive('running')).toBe(true)
    expect(isMemberTaskActive('succeeded')).toBe(false)
  })

  it('处理完成后提示等待家人确认，而不是暴露 succeeded', () => {
    expect(memberVisionStatusLabel('succeeded')).toBe('已交给家人，等待确认')
    expect(memberVisionStatusLabel('REVIEW_REQUIRED')).toBe('已交给家人，等待确认')
    expect(memberVisionStatusHint('succeeded')).toContain('我的记录')
  })

  it('冲突与未知状态映射为生活化提示', () => {
    expect(memberVisionStatusLabel('CONFLICT')).toBe('信息和药盒不太一样，等家人核对')
    expect(memberVisionStatusLabel('UNKNOWN')).toBe('暂时认不出药名，等家人帮忙')
    expect(memberVisionStatusHint('CONFLICT')).toContain('对照')
    expect(memberVisionStatusHint('UNKNOWN')).toContain('重新拍')
  })

  it('家人确认后的照片显示“家人已确认”，覆盖任务自身状态', () => {
    expect(memberVisionStatusLabel('succeeded', true)).toBe('家人已确认')
    expect(memberVisionStatusHint('succeeded', true)).toContain('家庭本子')
  })

  it('失败与超时提示重拍，不出现英文错误码', () => {
    for (const status of ['failed', 'timeout']) {
      expect(memberVisionStatusLabel(status)).toBe('没看清楚，请重新拍一张')
      expect(memberVisionStatusHint(status)).toContain('再拍一次')
      expect(isMemberTaskNeedsRetake(status)).toBe(true)
    }
    expect(isMemberTaskNeedsRetake('cancelled')).toBe(true)
    expect(isMemberTaskNeedsRetake('succeeded')).toBe(false)
    expect(isMemberTaskNeedsRetake('CONFLICT')).toBe(false)
    expect(isMemberTaskNeedsRetake('LOW_QUALITY')).toBe(true)
  })

  it('未知/内部状态一律回落到兜底文案，绝不透出内部代码', () => {
    for (const code of [
      'MATCHED',
      'LOW_QUALITY',
      'READY_FOR_FUSION',
      'SOMETHING_ELSE',
      '',
      null,
      undefined,
    ]) {
      const label = memberVisionStatusLabel(code as string)
      const hint = memberVisionStatusHint(code as string)
      for (const internal of INTERNAL_CODES) {
        expect(label).not.toContain(internal)
        expect(hint).not.toContain(internal)
      }
      expect(label.length).toBeGreaterThan(0)
      expect(/^[\u4e00-\u9fa5“”、。，！？·\s]+$/.test(label)).toBe(true)
    }
  })
})
