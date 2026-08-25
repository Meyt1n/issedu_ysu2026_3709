import { describe, expect, it } from 'vitest'

import {
  FACE_CAPTURE_STEPS,
  faceCaptureDoneSpeech,
  faceCaptureIntro,
  faceStepLabel,
} from './faceCaptureGuidance'

describe('faceCaptureGuidance', () => {
  it('provides three elder-friendly capture steps with speech', () => {
    expect(FACE_CAPTURE_STEPS).toHaveLength(3)
    for (const step of FACE_CAPTURE_STEPS) {
      expect(step.title.length).toBeGreaterThan(4)
      expect(step.speech.includes('圆圈') || step.speech.includes('转')).toBe(true)
    }
  })

  it('keeps login and registration intros short and actionable', () => {
    const login = faceCaptureIntro('login')
    const registration = faceCaptureIntro('registration')
    expect(login.bullets.length).toBeGreaterThanOrEqual(3)
    expect(registration.bullets.some(item => item.includes('PIN'))).toBe(true)
    expect(faceStepLabel(0)).toContain('第 1 步')
    expect(faceCaptureDoneSpeech('login')).toContain('稍等')
  })
})
