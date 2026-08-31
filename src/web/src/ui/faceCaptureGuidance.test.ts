import { describe, expect, it } from 'vitest'

import {
  FACE_CAPTURE_LOGIN_STEPS,
  FACE_CAPTURE_REGISTRATION_STEPS,
  faceCaptureDoneSpeech,
  faceCaptureIntro,
  faceCaptureStartLabel,
  faceCaptureSteps,
  faceStepLabel,
} from './faceCaptureGuidance'

describe('faceCaptureGuidance', () => {
  it('keeps registration on three elder-friendly steps', () => {
    expect(FACE_CAPTURE_REGISTRATION_STEPS).toHaveLength(3)
    expect(faceCaptureSteps('registration')).toHaveLength(3)
    for (const step of FACE_CAPTURE_REGISTRATION_STEPS) {
      expect(step.title.length).toBeGreaterThan(4)
      expect(step.speech.includes('圆圈') || step.speech.includes('转')).toBe(true)
    }
  })

  it('uses a shorter two-step login path', () => {
    expect(FACE_CAPTURE_LOGIN_STEPS).toHaveLength(2)
    expect(faceCaptureSteps('login')).toHaveLength(2)
    expect(faceCaptureStartLabel('login')).toBe('刷脸进入')
    expect(faceCaptureStartLabel('registration')).toContain('录入')
  })

  it('keeps every spoken step to one short utterance without step numbering', () => {
    const steps = [...FACE_CAPTURE_REGISTRATION_STEPS, ...FACE_CAPTURE_LOGIN_STEPS]
    for (const step of steps) {
      expect(step.speech.length).toBeLessThanOrEqual(14)
      expect(step.speech).not.toMatch(/第\s*[0-9一二三]\s*步/)
      expect(step.speech).not.toContain('请保持这个姿势')
      // 一步一条短句：至多一个句号，不再拼多句长播报。
      expect(step.speech.split('。').filter(part => part.trim()).length).toBeLessThanOrEqual(1)
    }
  })

  it('merges the login intro into step one instead of a separate spoken opening', () => {
    const login = faceCaptureIntro('login')
    expect(login.speech).toBe('')
    expect(FACE_CAPTURE_LOGIN_STEPS[0]!.speech).toContain('圆圈')
    const registration = faceCaptureIntro('registration')
    expect(registration.speech.length).toBeLessThanOrEqual(16)
  })

  it('keeps login and registration intros short and actionable', () => {
    const login = faceCaptureIntro('login')
    const registration = faceCaptureIntro('registration')
    expect(login.title).toContain('刷脸')
    expect(login.bullets.length).toBeGreaterThanOrEqual(2)
    expect(registration.bullets.some(item => item.includes('数字密码'))).toBe(false)
    expect(faceStepLabel(0, 2)).toBe('第 1 步，共 2 步')
    expect(faceCaptureDoneSpeech('login')).toContain('稍等')
    expect(faceCaptureDoneSpeech('registration')).toContain('稍等')
  })
})
